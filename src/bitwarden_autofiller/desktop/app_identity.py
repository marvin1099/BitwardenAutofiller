"""Resolve the stable app ID used by Bitwarden ``pcprocess://`` mappings."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from importlib import import_module

from bitwarden_autofiller.app_uri import APP_URI_SCHEME, normalize_app_id
from bitwarden_autofiller.desktop.wayland_identity import (
    detect_kwin_active_app_id,
    detect_wlr_active_app_id,
)

_LOGGER = logging.getLogger(__name__)


class ActiveApplicationUnavailable(RuntimeError):
    """No safe app identity could be obtained for the active window."""


def resolve_app_id(explicit_app_id: str | None = None) -> str:
    """Use an explicit ID or a compositor-supported foreground-window API."""
    if explicit_app_id and explicit_app_id.strip():
        value = explicit_app_id.strip()
        if value.casefold().startswith(APP_URI_SCHEME):
            value = normalize_app_id(value)
            if not value:
                raise ActiveApplicationUnavailable("Enter a valid application ID")
        return value.rstrip("/")

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
                ("KWin", detect_kwin_active_app_id),
                ("foreign-toplevel", detect_wlr_active_app_id),
            )
            if is_kde
            else (
                ("foreign-toplevel", detect_wlr_active_app_id),
                ("KWin", detect_kwin_active_app_id),
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
            "explicitly or install the optional Wayland detection dependencies"
        )

    try:
        pywinctl = import_module("pywinctl")
        active_window = pywinctl.getActiveWindow()
        app_name = active_window.getAppName() if active_window is not None else None
    except Exception as error:
        raise ActiveApplicationUnavailable(
            "Could not detect the active application; provide --app-id"
        ) from error
    if not isinstance(app_name, str) or not app_name.strip():
        raise ActiveApplicationUnavailable(
            "Could not detect the active application; provide --app-id"
        )
    return app_name.strip()
