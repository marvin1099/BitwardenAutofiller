"""Desktop input backends with a consent-based first-class Wayland path."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from ctypes import CDLL, RTLD_GLOBAL
from ctypes.util import find_library
from importlib import import_module
from typing import Any

from bitwarden_autofiller.filling.execution import InputAdapter


class InputBackendError(RuntimeError):
    """A desktop input backend is unsupported or unavailable."""


class WaylandInputAdapter:
    """Type through eitype's XDG RemoteDesktop portal integration."""

    def __init__(self, *, clipboard_copy: Callable[[str], None] | None = None) -> None:
        try:
            eitype = import_module("eitype")
        except ImportError as error:
            if isinstance(error, ModuleNotFoundError) and error.name == "eitype":
                raise InputBackendError(
                    "Wayland input requires the optional 'wayland' extra (eitype)"
                ) from error
            # Some eitype manylinux wheels bundle libxkbcommon without making
            # it globally visible, although the extension expects its symbols
            # from the process namespace. Loading the system ABI globally first
            # lets the extension resolve that dependency without changing the
            # user's library installation.
            xkbcommon = find_library("xkbcommon")
            if xkbcommon:
                try:
                    CDLL(xkbcommon, mode=RTLD_GLOBAL)
                    eitype = import_module("eitype")
                except (ImportError, OSError) as retry_error:
                    raise InputBackendError(
                        "Wayland input could not load eitype with system libxkbcommon"
                    ) from retry_error
            else:
                raise InputBackendError(
                    "Wayland input requires the optional 'wayland' extra (eitype)"
                ) from error

        try:
            self._typer = eitype.EiType.connect_portal()
        except Exception as error:
            raise InputBackendError(
                "Could not obtain Wayland input permission from the desktop portal"
            ) from error
        self._clipboard_copy = clipboard_copy or _copy_to_system_clipboard

    def type_text(self, text: str) -> None:
        for character in text:
            try:
                self._typer.type_text(character)
            except Exception as error:
                if not _is_character_missing_from_keymap(error):
                    raise InputBackendError("Wayland text input failed") from error
                # Paste only this character, then keep using eitype for the
                # remaining characters it can represent in the active keymap.
                self._paste_text(character)

    def _paste_text(self, text: str) -> None:
        clipboard_process: subprocess.Popen[str] | None = None
        try:
            clipboard_process = _copy_text_for_wayland_paste(text, self._clipboard_copy)
            self._typer.hold_modifier("ctrl")
            try:
                # Use eitype's active-keymap mapping for the paste shortcut.
                self._typer.type_text("v")
            finally:
                self._typer.release_modifiers()
            if clipboard_process is not None:
                _finish_wl_copy_once(clipboard_process)
        except InputBackendError:
            if clipboard_process is not None:
                _stop_wl_copy_once(clipboard_process)
            raise
        except Exception as error:
            if clipboard_process is not None:
                _stop_wl_copy_once(clipboard_process)
            raise InputBackendError("Wayland Unicode clipboard paste failed") from error

    def press_key(self, key: str) -> None:
        try:
            self._typer.press_key(key)
        except Exception as error:
            raise InputBackendError("Wayland key input failed") from error

    def copy_text(self, text: str) -> None:
        self._clipboard_copy(text)

    def close(self) -> None:
        close = getattr(self._typer, "close", None)
        if callable(close):
            close()


class PyAutoGuiInputAdapter:
    """Compatibility adapter for X11 and Windows desktop sessions."""

    def __init__(self, *, clipboard_copy: Callable[[str], None] | None = None) -> None:
        try:
            pyautogui = import_module("pyautogui")
        except ImportError as error:
            raise InputBackendError(
                "X11/Windows input requires the optional 'desktop' extra"
            ) from error
        self._pyautogui: Any = pyautogui
        self._clipboard_copy = clipboard_copy or _copy_to_system_clipboard

    def type_text(self, text: str) -> None:
        try:
            self._pyautogui.write(text)
        except Exception as error:
            raise InputBackendError("Desktop text input failed") from error

    def press_key(self, key: str) -> None:
        normalized = {"Return": "enter", "Tab": "tab"}.get(key, key.casefold())
        try:
            self._pyautogui.press(normalized)
        except Exception as error:
            raise InputBackendError("Desktop key input failed") from error

    def copy_text(self, text: str) -> None:
        self._clipboard_copy(text)


class LazyInputAdapter:
    """Defer desktop permissions and imports until input is actually needed."""

    def __init__(self, factory: Callable[[], InputAdapter]) -> None:
        self._factory = factory
        self._adapter: InputAdapter | None = None

    def _get_adapter(self) -> InputAdapter:
        if self._adapter is None:
            self._adapter = self._factory()
        return self._adapter

    def prepare(self) -> None:
        """Initialize permissions/backends before a focus-sensitive input check."""
        self._get_adapter()

    def type_text(self, text: str) -> None:
        self._get_adapter().type_text(text)

    def press_key(self, key: str) -> None:
        self._get_adapter().press_key(key)

    def copy_text(self, text: str) -> None:
        self._get_adapter().copy_text(text)

    def close(self) -> None:
        if self._adapter is not None:
            close = getattr(self._adapter, "close", None)
            if callable(close):
                close()


def create_input_adapter(
    *, clipboard_copy: Callable[[str], None] | None = None
) -> WaylandInputAdapter | PyAutoGuiInputAdapter:
    """Choose the current session backend without unsafe Wayland fallback."""
    if sys.platform == "linux":
        if (
            os.environ.get("WAYLAND_DISPLAY")
            or os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland"
        ):
            return WaylandInputAdapter(clipboard_copy=clipboard_copy)
        if os.environ.get("DISPLAY"):
            return PyAutoGuiInputAdapter(clipboard_copy=clipboard_copy)
        raise InputBackendError("No supported Linux desktop session was detected")
    if sys.platform == "win32":
        return PyAutoGuiInputAdapter(clipboard_copy=clipboard_copy)
    raise InputBackendError(f"Unsupported desktop platform: {sys.platform}")


def _copy_to_system_clipboard(text: str) -> None:
    if sys.platform == "linux" and _is_wayland_session():
        wl_copy = shutil.which("wl-copy")
        if wl_copy is not None:
            try:
                _run_wl_copy(wl_copy, text)
                return
            except (OSError, subprocess.SubprocessError):
                pass
    try:
        import_module("pyperclip").copy(text)
    except Exception as error:
        raise InputBackendError(
            "Could not access the clipboard; install wl-clipboard (wl-copy) "
            "or the optional desktop clipboard support"
        ) from error


def _copy_text_for_wayland_paste(
    text: str, clipboard_copy: Callable[[str], None]
) -> subprocess.Popen[str] | None:
    wl_copy = shutil.which("wl-copy") if sys.platform == "linux" else None
    if wl_copy is not None:
        try:
            return _start_wl_copy_once(wl_copy, text)
        except (OSError, subprocess.SubprocessError):
            # A GUI-provided clipboard callback can still work when wl-copy is
            # installed but its Wayland connection is unavailable.
            pass
    try:
        clipboard_copy(text)
    except InputBackendError:
        raise
    except Exception as error:
        raise InputBackendError(
            "Unicode text is not in the active keymap and clipboard paste "
            "is unavailable; install wl-clipboard or clipboard support"
        ) from error
    return None


def _start_wl_copy_once(executable: str, text: str) -> subprocess.Popen[str]:
    command = [executable, "--foreground", "--paste-once", "--sensitive"]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    try:
        if process.stdin is None:
            raise OSError("wl-copy did not provide a stdin pipe")
        process.stdin.write(text)
        process.stdin.close()
    except (OSError, ValueError):
        _stop_wl_copy_once(process)
        raise
    if process.poll() not in (None, 0):
        raise subprocess.CalledProcessError(process.returncode or 1, command)
    return process


def _finish_wl_copy_once(process: subprocess.Popen[str]) -> None:
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        # If the target did not request clipboard data, don't leave a helper
        # process holding the user's clipboard indefinitely.
        _stop_wl_copy_once(process)


def _stop_wl_copy_once(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _run_wl_copy(executable: str, text: str) -> None:
    command = [executable, "--sensitive"]
    subprocess.run(
        command,
        input=text,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5.0,
    )


def _is_wayland_session() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")) or (
        os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland"
    )


def _is_character_missing_from_keymap(error: Exception) -> bool:
    # eitype wraps its Rust CharNotFound error in RuntimeError. Do not log or
    # surface its message: it contains the character from the user's credential.
    return type(error) is RuntimeError and str(error).startswith(
        "Character not found in keymap:"
    )
