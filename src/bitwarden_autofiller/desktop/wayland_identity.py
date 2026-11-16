"""Compositor-supported Wayland active-window identity backends."""

from __future__ import annotations

import asyncio
import contextlib
import json
import select
import tempfile
import time
import uuid
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
    """Ask KWin's documented scripting API for its active window's app ID."""
    try:
        from dbus_fast import Message, MessageType
        from dbus_fast.aio import MessageBus
    except ImportError as error:
        raise RuntimeError(
            "Install the optional Wayland detection dependencies"
        ) from error

    return asyncio.run(
        _detect_kwin_active_app_id(MessageBus, Message, MessageType, timeout)
    )


async def _detect_kwin_active_app_id(
    bus_factory: Callable[[], Any],
    message_type: type[Any],
    message_types: Any,
    timeout: float,
) -> str:
    bus = await bus_factory().connect()
    token = uuid.uuid4().hex
    bus_name = f"org.bitwardenautofiller.ActiveApp.P{token}"
    object_path = "/org/bitwardenautofiller/ActiveApp"
    interface = "org.bitwardenautofiller.ActiveApp"
    plugin_name = f"bitwarden_autofiller_{token}"
    result: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    script_id: int | None = None
    script_path: Path | None = None

    def receive_app_id(message: Any) -> Any:
        if (
            message.message_type == message_types.METHOD_CALL
            and message.path == object_path
            and message.interface == interface
            and message.member == "ReturnActiveAppId"
            and message.signature == "s"
            and len(message.body) == 1
        ):
            app_id = message.body[0]
            if isinstance(app_id, str) and not result.done():
                result.set_result(app_id)
            return message_type.new_method_return(message)
        return None

    bus.add_message_handler(receive_app_id)
    try:
        await asyncio.wait_for(bus.request_name(bus_name), timeout)
        script = _kwin_detection_script(bus_name, object_path, interface)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="bitwarden-autofiller-kwin-",
            suffix=".js",
            delete=False,
        ) as script_file:
            script_file.write(script)
            script_path = Path(script_file.name)

        load_reply = await _kwin_call(
            bus,
            message_type(
                destination="org.kde.KWin",
                path="/Scripting",
                interface="org.kde.kwin.Scripting",
                member="loadScript",
                signature="ss",
                body=[str(script_path), plugin_name],
            ),
            timeout,
            message_types,
        )
        script_id = int(load_reply.body[0])
        if script_id < 0:
            raise RuntimeError("KWin refused to load its active-window script")

        await _kwin_call(
            bus,
            message_type(
                destination="org.kde.KWin",
                path=f"/Scripting/Script{script_id}",
                interface="org.kde.kwin.Script",
                member="run",
            ),
            timeout,
            message_types,
        )
        app_id = await asyncio.wait_for(result, timeout)
        if not app_id.strip():
            raise RuntimeError("KWin did not report an active application")
        return app_id.strip()
    finally:
        if script_id is not None and script_id >= 0:
            with contextlib.suppress(Exception):
                await _kwin_call(
                    bus,
                    message_type(
                        destination="org.kde.KWin",
                        path=f"/Scripting/Script{script_id}",
                        interface="org.kde.kwin.Script",
                        member="stop",
                    ),
                    timeout,
                    message_types,
                )
            with contextlib.suppress(Exception):
                await _kwin_call(
                    bus,
                    message_type(
                        destination="org.kde.KWin",
                        path="/Scripting",
                        interface="org.kde.kwin.Scripting",
                        member="unloadScript",
                        signature="s",
                        body=[plugin_name],
                    ),
                    timeout,
                    message_types,
                )
        if script_path is not None:
            with contextlib.suppress(OSError):
                script_path.unlink(missing_ok=True)
        with contextlib.suppress(Exception):
            bus.disconnect()


async def _kwin_call(bus: Any, message: Any, timeout: float, message_types: Any) -> Any:
    reply = await asyncio.wait_for(bus.call(message), timeout)
    if reply.message_type == message_types.ERROR:
        raise RuntimeError("KWin active-window query failed")
    return reply


def _kwin_detection_script(bus_name: str, object_path: str, interface: str) -> str:
    """Create a one-shot script; its only output is the active app identity."""
    return "\n".join(
        (
            "var active = workspace.activeWindow || workspace.activeClient;",
            "var appId = active ? (active.resourceClass || "
            "active.resourceName || active.desktopFileName || '') : '';",
            "callDBus("
            f"{json.dumps(bus_name)}, {json.dumps(object_path)}, "
            f"{json.dumps(interface)}, 'ReturnActiveAppId', appId);",
        )
    )


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
