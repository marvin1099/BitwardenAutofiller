"""Resolve the stable app ID used by Bitwarden ``pcprocess://`` mappings."""

from __future__ import annotations

import os
import sys
from importlib import import_module


class ActiveApplicationUnavailable(RuntimeError):
    """No safe app identity could be obtained for the active window."""


def resolve_app_id(explicit_app_id: str | None = None) -> str:
    """Use an explicit ID, or best-effort foreground-window detection.

    Generic Wayland protocols intentionally do not expose a global foreground
    process name. Wayland callers should provide an app ID explicitly instead
    of attempting to bypass the compositor's privacy boundary.
    """
    if explicit_app_id and explicit_app_id.strip():
        value = explicit_app_id.strip()
        if value.casefold().startswith("pcprocess://"):
            value = value[len("pcprocess://") :]
        return value.rstrip("/")

    is_wayland = sys.platform == "linux" and (
        bool(os.environ.get("WAYLAND_DISPLAY"))
        or os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland"
    )
    if is_wayland:
        raise ActiveApplicationUnavailable(
            "Wayland does not expose the active app ID; enter it explicitly"
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
