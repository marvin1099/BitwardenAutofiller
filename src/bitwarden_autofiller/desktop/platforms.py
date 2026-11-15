"""Desktop input backends with a consent-based first-class Wayland path."""

from __future__ import annotations

import os
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
        try:
            self._typer.type_text(text)
        except Exception as error:
            raise InputBackendError("Wayland text input failed") from error

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
    try:
        import_module("pyperclip").copy(text)
    except Exception as error:
        raise InputBackendError(
            "Could not access the system clipboard; install clipboard support"
        ) from error
