import sys
from types import ModuleType, SimpleNamespace

import pytest

from bitwarden_autofiller.app_identity import (
    ActiveApplicationUnavailable,
    resolve_app_id,
)
from bitwarden_autofiller.platforms import (
    InputBackendError,
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
    monkeypatch.setattr("bitwarden_autofiller.platforms.sys.platform", "linux")
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
    monkeypatch.delitem(sys.modules, "eitype", raising=False)
    monkeypatch.setattr("bitwarden_autofiller.platforms.sys.platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")

    with pytest.raises(InputBackendError, match="wayland"):
        create_input_adapter()


def test_wayland_requires_explicit_app_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bitwarden_autofiller.app_identity.sys.platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)

    assert resolve_app_id("pcprocess://steam/") == "steam"
    with pytest.raises(ActiveApplicationUnavailable, match="explicitly"):
        resolve_app_id()
