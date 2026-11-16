"""Read-only checks for desktop integration readiness."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from ctypes.util import find_library
from dataclasses import dataclass
from importlib import import_module, util

from bitwarden_autofiller.desktop.app_identity import (
    resolve_active_window_identity,
)

_PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_REMOTE_DESKTOP_INTERFACE = "org.freedesktop.portal.RemoteDesktop"


@dataclass(frozen=True, slots=True)
class DiagnosticItem:
    """One safe, user-facing diagnostic result."""

    component: str
    status: str
    detail: str


def collect_diagnostics(
    *,
    active_app_command: str | None = None,
    gui_clipboard_available: bool | None = None,
) -> tuple[DiagnosticItem, ...]:
    """Inspect prerequisites without opening a session or sending input."""
    is_wayland = _is_wayland_session()
    return (
        _diagnose_portal(is_wayland),
        _diagnose_keymap(is_wayland),
        _diagnose_clipboard(is_wayland, gui_clipboard_available),
        _diagnose_active_app(active_app_command),
    )


def format_diagnostics(items: tuple[DiagnosticItem, ...]) -> str:
    """Render diagnostic results without printing app IDs or clipboard contents."""
    lines = ["Desktop diagnostics (no input was sent):"]
    lines.extend(f"- {item.component}: {item.status} — {item.detail}" for item in items)
    return "\n".join(lines)


def _diagnose_portal(is_wayland: bool) -> DiagnosticItem:
    if not is_wayland:
        return DiagnosticItem(
            "Remote Desktop portal", "not required", "Only used for Wayland input."
        )
    busctl = shutil.which("busctl")
    if busctl is None:
        return DiagnosticItem(
            "Remote Desktop portal",
            "unknown",
            "busctl is unavailable, so the portal service could not be checked.",
        )
    try:
        result = subprocess.run(
            [
                busctl,
                "--user",
                "introspect",
                _PORTAL_SERVICE,
                _PORTAL_PATH,
                _REMOTE_DESKTOP_INTERFACE,
            ],
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return DiagnosticItem(
            "Remote Desktop portal",
            "unavailable",
            "The desktop portal RemoteDesktop interface did not respond.",
        )
    if "ConnectToEIS" not in result.stdout:
        return DiagnosticItem(
            "Remote Desktop portal",
            "unavailable",
            "The portal is running but does not expose the expected input interface.",
        )
    return DiagnosticItem(
        "Remote Desktop portal",
        "available",
        "The RemoteDesktop input interface is present; no session was requested.",
    )


def _diagnose_keymap(is_wayland: bool) -> DiagnosticItem:
    if not is_wayland:
        return DiagnosticItem(
            "Wayland keymap", "not required", "Only used for Wayland input."
        )
    try:
        xkbcommon = find_library("xkbcommon")
    except (OSError, RuntimeError):
        xkbcommon = None
    try:
        eitype = import_module("eitype")
        input_provider_available = callable(eitype.EiType.connect_portal)
    except Exception:
        input_provider_available = False
    if not xkbcommon or not input_provider_available:
        missing = []
        if not xkbcommon:
            missing.append("libxkbcommon")
        if not input_provider_available:
            missing.append("the eitype Wayland extra")
        return DiagnosticItem(
            "Wayland keymap",
            "unavailable",
            f"Missing {', '.join(missing)}.",
        )
    return DiagnosticItem(
        "Wayland keymap",
        "not probed",
        "Keymap dependencies are present; the active map requires a portal session, "
        "which diagnostics does not open.",
    )


def _diagnose_clipboard(
    is_wayland: bool, gui_clipboard_available: bool | None
) -> DiagnosticItem:
    if gui_clipboard_available is True:
        return DiagnosticItem(
            "Clipboard", "available", "The GUI clipboard object is available."
        )
    if gui_clipboard_available is False:
        return DiagnosticItem(
            "Clipboard", "unavailable", "The GUI clipboard object is unavailable."
        )
    if is_wayland and shutil.which("wl-copy") is not None:
        return DiagnosticItem(
            "Clipboard", "available", "wl-copy is installed; contents were not read."
        )
    try:
        pyperclip_available = util.find_spec("pyperclip") is not None
    except (ImportError, ValueError):
        pyperclip_available = False
    if pyperclip_available:
        return DiagnosticItem(
            "Clipboard",
            "available",
            "pyperclip is installed; clipboard contents were not read.",
        )
    return DiagnosticItem(
        "Clipboard",
        "unavailable",
        "No supported clipboard helper was detected.",
    )


def _diagnose_active_app(active_app_command: str | None) -> DiagnosticItem:
    try:
        identity = resolve_active_window_identity(active_app_command=active_app_command)
    except Exception:
        return DiagnosticItem(
            "Active-app detection",
            "unavailable",
            "No active application could be detected with the current settings.",
        )
    window_detail = (
        "a stable window handle is available"
        if identity.window_id and identity.window_backend
        else "only app identity is available"
    )
    return DiagnosticItem(
        "Active-app detection",
        "available",
        f"An active application was detected; {window_detail}.",
    )


def _is_wayland_session() -> bool:
    return sys.platform == "linux" and (
        bool(os.environ.get("WAYLAND_DISPLAY"))
        or os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland"
    )
