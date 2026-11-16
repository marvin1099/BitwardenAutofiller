"""Resolve the stable app ID used by Bitwarden ``pcprocess://`` mappings."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable
from importlib import import_module

from bitwarden_autofiller.app_uri import APP_URI_SCHEME, normalize_app_id
from bitwarden_autofiller.desktop.wayland_identity import (
    detect_kwin_active_app_id,
    detect_wlr_active_app_id,
    process_name_for_pid,
)

_LOGGER = logging.getLogger(__name__)
_CUSTOM_COMMAND_TIMEOUT_SECONDS = 2.0


class ActiveApplicationUnavailable(RuntimeError):
    """No safe app identity could be obtained for the active window."""


class ActiveApplicationVerifier:
    """Check the focused app immediately before each desktop input operation."""

    def __init__(
        self,
        expected_app_id: str,
        *,
        active_app_command: str | None = None,
        allow_unverified: bool = False,
        on_unverified: Callable[[], None] | None = None,
    ) -> None:
        self._expected_app_id = normalize_app_id(expected_app_id)
        if not self._expected_app_id:
            raise ValueError("An application ID is required for focus verification")
        self._active_app_command = active_app_command
        self._allow_unverified = allow_unverified
        self._on_unverified = on_unverified
        self.unverified = False

    def verify(self) -> None:
        """Raise before input if focus changed or cannot be verified safely."""
        if self.unverified:
            return
        try:
            active_app_id = resolve_app_id(active_app_command=self._active_app_command)
        except ActiveApplicationUnavailable as error:
            if not self._allow_unverified:
                raise ActiveApplicationUnavailable(
                    "Could not verify the active application; configure active-app "
                    "detection or explicitly allow an unverified target"
                ) from error
            self.unverified = True
            if self._on_unverified is not None:
                self._on_unverified()
            return

        if normalize_app_id(active_app_id) != self._expected_app_id:
            raise ActiveApplicationUnavailable(
                "The focused application does not match the selected app ID; "
                "autofill was cancelled"
            )


def resolve_app_id(
    explicit_app_id: str | None = None,
    *,
    active_app_command: str | None = None,
) -> str:
    """Resolve an explicit ID, configured PID command, or native window API.

    A configured command is tried first and must print only the active window's
    PID. Its process name is used as the app ID, matching PyWinCtl's Linux
    ``getAppName()`` behavior. Native detection remains the fallback.
    """
    if explicit_app_id and explicit_app_id.strip():
        value = explicit_app_id.strip()
        if value.casefold().startswith(APP_URI_SCHEME):
            value = normalize_app_id(value)
            if not value:
                raise ActiveApplicationUnavailable("Enter a valid application ID")
        return value.rstrip("/")

    if active_app_command and active_app_command.strip():
        try:
            return _detect_app_id_from_command(active_app_command)
        except Exception as error:
            # Do not log the configured command or its output; either may
            # contain user-specific values. Keep only a safe failure summary.
            _LOGGER.debug(
                "Custom active-app command unavailable (%s)", type(error).__name__
            )

    is_wayland = sys.platform == "linux" and (
        bool(os.environ.get("WAYLAND_DISPLAY"))
        or os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland"
    )
    if is_wayland:
        desktops = " ".join(
            (
                os.environ.get("XDG_CURRENT_DESKTOP", ""),
                os.environ.get("XDG_SESSION_DESKTOP", ""),
            )
        ).casefold()
        is_kde = (
            "kde" in desktops
            or "plasma" in desktops
            or bool(os.environ.get("KDE_FULL_SESSION"))
        )
        backends: tuple[tuple[str, Callable[[], str]], ...] = (
            (
                ("KWin/kdotool", detect_kwin_active_app_id),
                ("foreign-toplevel", detect_wlr_active_app_id),
            )
            if is_kde
            else (
                ("foreign-toplevel", detect_wlr_active_app_id),
                ("KWin/kdotool", detect_kwin_active_app_id),
            )
        )
        for backend_name, detect in backends:
            try:
                app_id = detect().strip()
            except Exception as error:
                _LOGGER.debug(
                    "Wayland active-app backend %s unavailable (%s)",
                    backend_name,
                    type(error).__name__,
                )
                continue
            if app_id:
                return app_id
        raise ActiveApplicationUnavailable(
            "Could not detect the active Wayland application; enter --app-id "
            "explicitly, or configure an active-app command that prints its PID "
            "(install kdotool on KDE Plasma 6 or the optional Wayland "
            "dependencies for wlroots)"
        )

    try:
        pywinctl = import_module("pywinctl")
        active_window = pywinctl.getActiveWindow()
        app_name = active_window.getAppName() if active_window is not None else None
    except Exception as error:
        raise ActiveApplicationUnavailable(
            "Could not detect the active application; provide --app-id or "
            "configure an active-app command that prints its PID"
        ) from error
    if not isinstance(app_name, str) or not app_name.strip():
        raise ActiveApplicationUnavailable(
            "Could not detect the active application; provide --app-id or "
            "configure an active-app command that prints its PID"
        )
    return app_name.strip()


def _detect_app_id_from_command(command: str) -> str:
    """Run a user-configured shell command and resolve its PID to a process name."""
    result = subprocess.run(
        command,
        shell=True,
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=_CUSTOM_COMMAND_TIMEOUT_SECONDS,
    )
    try:
        pid = int(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError(
            "Custom active-app command returned an invalid PID"
        ) from error
    app_name = process_name_for_pid(pid)
    if not app_name:
        raise RuntimeError("Could not read the active process name")
    return app_name
