"""Compositor-supported Wayland active-window identity backends."""

from __future__ import annotations

import contextlib
import select
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from importlib import import_module
from pathlib import Path
from typing import Any

WLR_FOREIGN_TOPLEVEL_INTERFACE = "zwlr_foreign_toplevel_manager_v1"
WLR_ACTIVATED_STATE = 2
_WLR_TIMEOUT_SECONDS = 1.0
_KWIN_TIMEOUT_SECONDS = 2.0


def detect_wlr_active_app_id(
    *,
    display_factory: Callable[[], Any] | None = None,
    manager_interface: Any | None = None,
    timeout: float = _WLR_TIMEOUT_SECONDS,
) -> str:
    """Read the activated app ID through the wlr foreign-toplevel protocol.

    This is a read-only client of a compositor-advertised protocol. It does
    not inspect process lists or window titles. PyWayland and the generated
    protocol binding are optional so non-Wayland installations stay lean.
    """
    if display_factory is None or manager_interface is None:
        try:
            from bitwarden_autofiller.desktop._protocols.wlr_foreign_toplevel_management_unstable_v1 import (  # noqa: E501
                ZwlrForeignToplevelHandleV1,
                ZwlrForeignToplevelManagerV1,
            )

            Display = import_module("pywayland.client").Display
        except ImportError as error:
            raise RuntimeError(
                "Install the optional Wayland detection dependencies"
            ) from error
        display_factory = display_factory or Display
        manager_interface = manager_interface or ZwlrForeignToplevelManagerV1
        activated_state = int(ZwlrForeignToplevelHandleV1.state.activated)
    else:
        activated_state = WLR_ACTIVATED_STATE

    display = display_factory()
    manager: Any | None = None
    windows: dict[Any, dict[str, Any]] = {}

    def on_toplevel(_manager: Any, handle: Any) -> None:
        record: dict[str, Any] = {"app_id": "", "activated": False}
        windows[handle] = record

        def set_app_id(_handle: Any, app_id: str) -> None:
            record["app_id"] = app_id

        def set_state(_handle: Any, states: Sequence[int]) -> None:
            record["activated"] = activated_state in states

        def on_closed(closed_handle: Any) -> None:
            windows.pop(closed_handle, None)

        handle.dispatcher["app_id"] = set_app_id
        handle.dispatcher["state"] = set_state
        handle.dispatcher["closed"] = on_closed

    def on_global(registry: Any, name: int, interface: str, version: int) -> None:
        nonlocal manager
        if interface == WLR_FOREIGN_TOPLEVEL_INTERFACE and manager is None:
            manager = registry.bind(
                name, manager_interface, min(version, manager_interface.version)
            )
            manager.dispatcher["toplevel"] = on_toplevel

    try:
        display.connect()
        registry = display.get_registry()
        registry.dispatcher["global"] = on_global
        _timed_roundtrip(display, timeout)
        if manager is None:
            raise RuntimeError(
                "The compositor does not advertise the foreign-toplevel protocol"
            )

        # Binding the manager happens in the registry callback; the second
        # sync receives its initial toplevel list and active-state events.
        _timed_roundtrip(display, timeout)
        active_ids = {
            str(window["app_id"]).strip()
            for window in windows.values()
            if window["activated"] and str(window["app_id"]).strip()
        }
        if len(active_ids) != 1:
            raise RuntimeError("The compositor did not report one active app ID")
        return next(iter(active_ids))
    finally:
        if manager is not None:
            with contextlib.suppress(Exception):
                manager.stop()
                display.flush()
        with contextlib.suppress(Exception):
            display.disconnect()


def detect_kwin_active_app_id(*, timeout: float = _KWIN_TIMEOUT_SECONDS) -> str:
    """Get KWin's active process name, matching PyWinCtl's old app-name IDs.

    ``kdotool`` exposes the active window PID through KWin's scripting API.
    PyWinCtl's Linux ``getAppName()`` used that PID to read the process
    ``comm`` name, so use the same value to keep existing ``pcprocess://``
    mappings compatible. Fall back to KWin's window class when a window has no
    readable PID.
    """
    process_id = _run_kdotool(("getactivewindow", "getwindowpid"), timeout=timeout)
    try:
        pid = int(process_id)
    except ValueError:
        pid = 0

    if pid > 0:
        app_name = process_name_for_pid(pid)
        if app_name:
            return app_name

    window_class = _run_kdotool(
        ("getactivewindow", "getwindowclassname"), timeout=timeout
    )
    if window_class:
        return window_class
    raise RuntimeError("KWin did not report an active application name or class")


def _run_kdotool(arguments: Sequence[str], *, timeout: float) -> str:
    try:
        result = subprocess.run(
            ["kdotool", *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("kdotool could not query KWin's active window") from error
    return result.stdout.strip()


def process_name_for_pid(pid: int, *, proc_root: Path = Path("/proc")) -> str:
    """Return a process name for a PID, using the Linux-compatible name first."""
    if pid <= 0:
        return ""
    try:
        return (proc_root / str(pid) / "comm").read_text(encoding="utf-8").strip()
    except OSError:
        pass

    try:
        if sys.platform == "win32":
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-Process -Id {pid}).ProcessName",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            return result.stdout.strip()
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            check=True,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return Path(result.stdout.strip()).name


def _timed_roundtrip(display: Any, timeout: float) -> None:
    """Perform a Wayland sync without blocking indefinitely on a dead socket."""
    callback = display.sync()
    complete = False

    def on_done(_callback: Any, _serial: int) -> None:
        nonlocal complete
        complete = True

    callback.dispatcher["done"] = on_done
    display.flush()
    deadline = time.monotonic() + timeout
    while not complete:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("The Wayland compositor did not answer")
        readable, _, _ = select.select([display.get_fd()], [], [], remaining)
        if not readable:
            raise TimeoutError("The Wayland compositor did not answer")
        display.dispatch(block=True)
