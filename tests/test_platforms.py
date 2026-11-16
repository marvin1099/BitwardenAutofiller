from __future__ import annotations

import asyncio
import sys
from ctypes import RTLD_GLOBAL
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from bitwarden_autofiller.desktop import app_identity, platforms, wayland_identity
from bitwarden_autofiller.desktop.app_identity import (
    ActiveApplicationUnavailable,
    resolve_app_id,
)
from bitwarden_autofiller.desktop.platforms import (
    InputBackendError,
    LazyInputAdapter,
    PyAutoGuiInputAdapter,
    WaylandInputAdapter,
    create_input_adapter,
)


class FakeEiType:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def type_text(self, text: str) -> None:
        self.calls.append(("type", text))

    def press_key(self, key: str) -> None:
        self.calls.append(("key", key))


def test_wayland_factory_uses_eitype_and_clipboard_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typer = FakeEiType()
    eitype = ModuleType("eitype")
    eitype.EiType = SimpleNamespace(connect_portal=lambda: typer)  # type: ignore[attr-defined]
    copied: list[str] = []
    monkeypatch.setitem(sys.modules, "eitype", eitype)
    monkeypatch.setattr("bitwarden_autofiller.desktop.platforms.sys.platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("DISPLAY", raising=False)

    adapter = create_input_adapter(clipboard_copy=copied.append)

    assert isinstance(adapter, WaylandInputAdapter)
    adapter.type_text("hello")
    adapter.press_key("Tab")
    adapter.copy_text("secret")
    assert typer.calls == [("type", "hello"), ("key", "Tab")]
    assert copied == ["secret"]


def test_wayland_does_not_silently_fall_back_to_x11(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(self: object, **_: object) -> None:
        raise InputBackendError("Wayland portal is unavailable")

    monkeypatch.setattr(platforms.WaylandInputAdapter, "__init__", unavailable)
    monkeypatch.setattr("bitwarden_autofiller.desktop.platforms.sys.platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")

    with pytest.raises(InputBackendError, match="Wayland"):
        create_input_adapter()


def test_wayland_requires_explicit_app_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.app_identity.sys.platform", "linux"
    )
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.setattr(
        app_identity,
        "detect_wlr_active_app_id",
        lambda: (_ for _ in ()).throw(RuntimeError("no wlr protocol")),
    )
    monkeypatch.setattr(
        app_identity,
        "detect_kwin_active_app_id",
        lambda: (_ for _ in ()).throw(RuntimeError("no KWin session")),
    )

    assert resolve_app_id("pcprocess://steam/") == "steam"
    with pytest.raises(ActiveApplicationUnavailable, match="explicitly"):
        resolve_app_id()


def test_wayland_prefers_kwin_backend_on_a_kde_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.app_identity.sys.platform", "linux"
    )
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr(app_identity, "detect_kwin_active_app_id", lambda: "Steam")

    def unexpected_wlr_call() -> str:
        raise AssertionError("KWin should be tried first on KDE")

    monkeypatch.setattr(app_identity, "detect_wlr_active_app_id", unexpected_wlr_call)

    assert resolve_app_id() == "Steam"


def test_wayland_falls_back_from_kwin_to_foreign_toplevel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.app_identity.sys.platform", "linux"
    )
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr(
        app_identity,
        "detect_kwin_active_app_id",
        lambda: (_ for _ in ()).throw(RuntimeError("no KWin service")),
    )
    monkeypatch.setattr(
        app_identity, "detect_wlr_active_app_id", lambda: "com.example.Game"
    )

    assert resolve_app_id() == "com.example.Game"


class _FakeWaylandCallback:
    def __init__(self) -> None:
        self.dispatcher: dict[str, object] = {}


class _FakeWaylandHandle:
    def __init__(self) -> None:
        self.dispatcher: dict[str, object] = {}


class _FakeWaylandManager:
    def __init__(self) -> None:
        self.dispatcher: dict[str, object] = {}
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _FakeWaylandRegistry:
    def __init__(self, manager: _FakeWaylandManager) -> None:
        self.dispatcher: dict[str, object] = {}
        self.manager = manager

    def bind(
        self, _name: int, _interface: object, _version: int
    ) -> _FakeWaylandManager:
        return self.manager


class _FakeWaylandDisplay:
    def __init__(self, *, advertise_protocol: bool = True, active: bool = True) -> None:
        self.manager = _FakeWaylandManager()
        self.registry = _FakeWaylandRegistry(self.manager)
        self.advertise_protocol = advertise_protocol
        self.active = active
        self._callback: _FakeWaylandCallback | None = None
        self._roundtrip = 0
        self.disconnected = False

    def connect(self) -> None:
        pass

    def get_registry(self) -> _FakeWaylandRegistry:
        return self.registry

    def sync(self) -> _FakeWaylandCallback:
        self._roundtrip += 1
        self._callback = _FakeWaylandCallback()
        return self._callback

    def get_fd(self) -> int:
        return 1

    def flush(self) -> None:
        pass

    def dispatch(self, *, block: bool) -> None:
        assert block
        if self._roundtrip == 1 and self.advertise_protocol:
            callback = self.registry.dispatcher["global"]
            assert callable(callback)
            callback(
                self.registry,
                7,
                wayland_identity.WLR_FOREIGN_TOPLEVEL_INTERFACE,
                3,
            )
        elif self._roundtrip == 2:
            create_toplevel = self.manager.dispatcher["toplevel"]
            assert callable(create_toplevel)
            handle = _FakeWaylandHandle()
            create_toplevel(self.manager, handle)
            app_id = handle.dispatcher["app_id"]
            state = handle.dispatcher["state"]
            assert callable(app_id) and callable(state)
            app_id(handle, "com.example.Game")
            state(handle, [wayland_identity.WLR_ACTIVATED_STATE] if self.active else [])
        if self._callback is not None:
            callback = self._callback.dispatcher["done"]
            assert callable(callback)
            callback(self._callback, 1)

    def disconnect(self) -> None:
        self.disconnected = True


class _FakeManagerInterface:
    version = 3


def test_wlr_foreign_toplevel_detection_returns_active_app_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    display = _FakeWaylandDisplay()
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.wayland_identity.select.select",
        lambda *_: ([1], [], []),
    )

    app_id = wayland_identity.detect_wlr_active_app_id(
        display_factory=lambda: display,
        manager_interface=_FakeManagerInterface,
    )

    assert app_id == "com.example.Game"
    assert display.disconnected
    assert display.manager.stopped


@pytest.mark.parametrize(
    ("advertise_protocol", "active"),
    ((False, False), (True, False)),
)
def test_wlr_foreign_toplevel_detection_fails_without_a_unique_active_app(
    monkeypatch: pytest.MonkeyPatch,
    advertise_protocol: bool,
    active: bool,
) -> None:
    display = _FakeWaylandDisplay(advertise_protocol=advertise_protocol, active=active)
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.wayland_identity.select.select",
        lambda *_: ([1], [], []),
    )

    with pytest.raises(RuntimeError):
        wayland_identity.detect_wlr_active_app_id(
            display_factory=lambda: display,
            manager_interface=_FakeManagerInterface,
        )

    assert display.disconnected


def test_kwin_script_queries_only_the_active_window_app_identity() -> None:
    script = wayland_identity._kwin_detection_script(
        "org.bitwardenautofiller.ActiveApp.P123",
        "/org/bitwardenautofiller/ActiveApp",
        "org.bitwardenautofiller.ActiveApp",
    )

    assert "workspace.activeWindow" in script
    assert "active.resourceClass" in script
    assert "ReturnActiveAppId" in script
    assert "active.caption" not in script


class _FakeDBusMessage:
    message_type: int
    path: str
    interface: str
    member: str
    signature: str
    body: list[object]

    def __init__(self, **values: object) -> None:
        message_type = values.get("message_type", 0)
        self.message_type = message_type if isinstance(message_type, int) else 0
        self.path = str(values.get("path", ""))
        self.interface = str(values.get("interface", ""))
        self.member = str(values.get("member", ""))
        self.signature = str(values.get("signature", ""))
        body = values.get("body", [])
        self.body = body if isinstance(body, list) else []

    @classmethod
    def new_method_return(cls, _message: object) -> _FakeDBusMessage:
        return cls(message_type=0)


class _FakeDBusBus:
    def __init__(self, app_id: str) -> None:
        self.app_id = app_id
        self.handler: object | None = None
        self.script_path: Path | None = None
        self.disconnected = False
        self.called_members: list[str] = []

    async def connect(self) -> _FakeDBusBus:
        return self

    async def request_name(self, _name: str) -> int:
        return 1

    def add_message_handler(self, handler: object) -> None:
        self.handler = handler

    async def call(self, message: _FakeDBusMessage) -> _FakeDBusMessage:
        self.called_members.append(str(message.member))
        if message.member == "loadScript":
            self.script_path = Path(str(message.body[0]))
            assert self.script_path.is_file()
            return _FakeDBusMessage(message_type=0, body=[42])
        if message.member == "run":
            assert self.script_path is not None
            script = self.script_path.read_text(encoding="utf-8")
            assert "workspace.activeWindow" in script
            assert callable(self.handler)
            incoming = _FakeDBusMessage(
                message_type=1,
                path="/org/bitwardenautofiller/ActiveApp",
                interface="org.bitwardenautofiller.ActiveApp",
                member="ReturnActiveAppId",
                signature="s",
                body=[self.app_id],
            )
            self.handler(incoming)
        return _FakeDBusMessage(message_type=0, body=[])

    def disconnect(self) -> None:
        self.disconnected = True


@pytest.mark.parametrize(("app_id", "should_succeed"), (("Steam", True), ("", False)))
def test_kwin_active_app_query_uses_a_temporary_script_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    app_id: str,
    should_succeed: bool,
) -> None:
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.wayland_identity.tempfile.tempdir",
        str(tmp_path),
    )
    bus = _FakeDBusBus(app_id)
    message_types = SimpleNamespace(METHOD_CALL=1, ERROR=2)

    query = wayland_identity._detect_kwin_active_app_id(
        lambda: bus,
        _FakeDBusMessage,
        message_types,
        timeout=0.1,
    )
    if should_succeed:
        assert asyncio.run(query) == "Steam"
    else:
        with pytest.raises(RuntimeError, match="active application"):
            asyncio.run(query)

    assert bus.disconnected
    assert bus.called_members == ["loadScript", "run", "stop", "unloadScript"]
    assert bus.script_path is not None
    assert not bus.script_path.exists()


def test_eitype_loader_uses_system_xkbcommon_for_wheel_symbol_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typer = FakeEiType()
    eitype = SimpleNamespace(EiType=SimpleNamespace(connect_portal=lambda: typer))
    imports = 0

    def import_eitype(name: str) -> object:
        nonlocal imports
        assert name == "eitype"
        imports += 1
        if imports == 1:
            raise ImportError("undefined xkbcommon symbol")
        return eitype

    loaded: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.import_module", import_eitype
    )
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.find_library",
        lambda _: "libxkbcommon.so.0",
    )
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.CDLL",
        lambda name, mode: loaded.append((name, mode)),
    )

    adapter = WaylandInputAdapter(clipboard_copy=lambda _: None)

    assert isinstance(adapter, WaylandInputAdapter)
    assert imports == 2
    assert loaded == [("libxkbcommon.so.0", RTLD_GLOBAL)]


def test_pyautogui_backend_maps_keys_and_uses_clipboard_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str]] = []
    fake_pyautogui = SimpleNamespace(
        write=lambda text: events.append(("write", text)),
        press=lambda key: events.append(("press", key)),
    )
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.import_module", lambda _: fake_pyautogui
    )
    copied: list[str] = []
    adapter = PyAutoGuiInputAdapter(clipboard_copy=copied.append)

    adapter.type_text("alice")
    adapter.press_key("Return")
    adapter.press_key("Tab")
    adapter.press_key("Escape")
    adapter.copy_text("secret")

    assert events == [
        ("write", "alice"),
        ("press", "enter"),
        ("press", "tab"),
        ("press", "escape"),
    ]
    assert copied == ["secret"]


def test_lazy_input_backend_does_not_initialize_until_requested() -> None:
    events: list[tuple[str, str]] = []
    created: list[str] = []

    class RecordingAdapter:
        def type_text(self, text: str) -> None:
            events.append(("type", text))

        def press_key(self, key: str) -> None:
            events.append(("key", key))

        def copy_text(self, text: str) -> None:
            events.append(("copy", text))

        def close(self) -> None:
            events.append(("close", ""))

    def factory() -> RecordingAdapter:
        created.append("created")
        return RecordingAdapter()

    adapter = LazyInputAdapter(factory)
    adapter.close()
    assert created == []

    adapter.type_text("sensitive value")
    adapter.close()

    assert created == ["created"]
    assert events == [("type", "sensitive value"), ("close", "")]


def test_app_identity_uses_active_window_on_x11(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = SimpleNamespace(getAppName=lambda: "Steam")
    pywinctl = SimpleNamespace(getActiveWindow=lambda: window)
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.app_identity.sys.platform", "linux"
    )
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.app_identity.import_module", lambda _: pywinctl
    )

    assert resolve_app_id() == "Steam"
