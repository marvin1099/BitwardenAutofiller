import sys
from ctypes import RTLD_GLOBAL
from types import ModuleType, SimpleNamespace

import pytest

from bitwarden_autofiller.desktop import platforms
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

    assert resolve_app_id("pcprocess://steam/") == "steam"
    with pytest.raises(ActiveApplicationUnavailable, match="explicitly"):
        resolve_app_id()


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
