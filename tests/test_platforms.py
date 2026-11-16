from __future__ import annotations

import logging
import subprocess
import sys
from ctypes import RTLD_GLOBAL
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from bitwarden_autofiller.desktop import app_identity, platforms, wayland_identity
from bitwarden_autofiller.desktop.app_identity import (
    ActiveApplicationUnavailable,
    ActiveApplicationVerifier,
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
        self.unsupported_chars: set[str] = set()

    def type_text(self, text: str) -> None:
        if text in self.unsupported_chars:
            raise RuntimeError(f"Character not found in keymap: {text}")
        self.calls.append(("type", text))

    def press_key(self, key: str) -> None:
        self.calls.append(("key", key))

    def hold_modifier(self, modifier: str) -> None:
        self.calls.append(("hold", modifier))

    def release_modifiers(self) -> None:
        self.calls.append(("release", ""))


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
    assert typer.calls == [
        ("type", "h"),
        ("type", "e"),
        ("type", "l"),
        ("type", "l"),
        ("type", "o"),
        ("key", "Tab"),
    ]
    assert copied == ["secret"]


def test_wayland_pastes_only_the_unmappable_character_then_resumes_eitype(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typer = FakeEiType()
    typer.unsupported_chars.add("☃")
    eitype = ModuleType("eitype")
    eitype.EiType = SimpleNamespace(connect_portal=lambda: typer)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "eitype", eitype)
    monkeypatch.setattr("bitwarden_autofiller.desktop.platforms.sys.platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.shutil.which", lambda _: None
    )
    copied: list[str] = []

    adapter = WaylandInputAdapter(clipboard_copy=copied.append)
    adapter.type_text("abc☃tail")

    assert typer.calls == [
        ("type", "a"),
        ("type", "b"),
        ("type", "c"),
        ("hold", "ctrl"),
        ("type", "v"),
        ("release", ""),
        ("type", "t"),
        ("type", "a"),
        ("type", "i"),
        ("type", "l"),
    ]
    assert copied == ["☃"]


def test_wayland_unicode_paste_reports_unavailable_clipboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typer = FakeEiType()
    typer.unsupported_chars.add("☃")
    eitype = ModuleType("eitype")
    eitype.EiType = SimpleNamespace(connect_portal=lambda: typer)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "eitype", eitype)
    monkeypatch.setattr("bitwarden_autofiller.desktop.platforms.sys.platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.shutil.which", lambda _: None
    )

    def unavailable_clipboard(_text: str) -> None:
        raise InputBackendError("clipboard unavailable")

    adapter = WaylandInputAdapter(clipboard_copy=unavailable_clipboard)

    with pytest.raises(InputBackendError, match="clipboard unavailable"):
        adapter.type_text("before☃after")

    assert typer.calls == [
        ("type", "b"),
        ("type", "e"),
        ("type", "f"),
        ("type", "o"),
        ("type", "r"),
        ("type", "e"),
    ]


def test_wayland_unicode_paste_prefers_one_shot_wl_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[list[str], dict[str, object]]] = []
    copy_callback: list[str] = []

    class FakeStdin:
        def __init__(self) -> None:
            self.value = ""
            self.closed = False

        def write(self, text: str) -> int:
            self.value += text
            return len(text)

        def close(self) -> None:
            self.closed = True

    class FakeClipboardProcess:
        def __init__(self) -> None:
            self.stdin = FakeStdin()
            self.waited = False

        def poll(self) -> int | None:
            return None

        def wait(self, timeout: float) -> int:
            assert timeout == 2.0
            self.waited = True
            return 0

        def terminate(self) -> None:
            raise AssertionError("Clipboard process should exit after paste")

        def kill(self) -> None:
            raise AssertionError("Clipboard process should exit after paste")

    process = FakeClipboardProcess()

    def fake_popen(command: list[str], **kwargs: object) -> FakeClipboardProcess:
        commands.append((command, kwargs))
        return process

    monkeypatch.setattr("bitwarden_autofiller.desktop.platforms.sys.platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.shutil.which",
        lambda _: "/usr/bin/wl-copy",
    )
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.subprocess.Popen", fake_popen
    )

    started = platforms._copy_text_for_wayland_paste("你好😀", copy_callback.append)

    assert commands == [
        (
            [
                "/usr/bin/wl-copy",
                "--foreground",
                "--paste-once",
                "--sensitive",
            ],
            {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "text": True,
                "encoding": "utf-8",
            },
        )
    ]
    started_process = cast(FakeClipboardProcess, started)
    assert started_process is process
    assert started_process.stdin.value == "你好😀"
    assert started_process.stdin.closed
    assert not started_process.waited
    assert copy_callback == []

    platforms._finish_wl_copy_once(cast(Any, started_process))
    assert process.waited


def test_wayland_system_clipboard_uses_pyperclip_when_wl_copy_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    pyperclip = SimpleNamespace(copy=copied.append)
    monkeypatch.setattr("bitwarden_autofiller.desktop.platforms.sys.platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.shutil.which", lambda _: None
    )
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.import_module",
        lambda name: pyperclip,
    )

    platforms._copy_to_system_clipboard("clipboard value")

    assert copied == ["clipboard value"]


def test_wayland_system_clipboard_uses_sensitive_wl_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        commands.append(command)
        assert kwargs["input"] == "clipboard value"
        assert kwargs["check"] is True

    monkeypatch.setattr("bitwarden_autofiller.desktop.platforms.sys.platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.shutil.which",
        lambda _: "/usr/bin/wl-copy",
    )
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.platforms.subprocess.run", fake_run
    )

    platforms._copy_to_system_clipboard("clipboard value")

    assert commands == [["/usr/bin/wl-copy", "--sensitive"]]


def test_unconsumed_one_shot_clipboard_process_is_terminated() -> None:
    class UnconsumedClipboardProcess:
        returncode: int | None = None
        terminated = False

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float) -> int:
            if timeout == 2.0 and self.returncode is None:
                raise subprocess.TimeoutExpired("wl-copy", timeout)
            assert timeout == 1.0
            assert self.returncode is not None
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        def kill(self) -> None:
            raise AssertionError("Clipboard process should terminate cleanly")

    process = UnconsumedClipboardProcess()

    platforms._finish_wl_copy_once(cast(Any, process))

    assert process.terminated


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


def test_kwin_detection_uses_process_name_for_pywinctl_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs["timeout"] == 0.1
        assert kwargs["check"] is True
        return subprocess.CompletedProcess(command, 0, stdout="4242\n", stderr="")

    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.wayland_identity.subprocess.run", fake_run
    )
    monkeypatch.setattr(wayland_identity, "process_name_for_pid", lambda pid: "steam")

    assert wayland_identity.detect_kwin_active_app_id(timeout=0.1) == "steam"
    assert calls == [["kdotool", "getactivewindow", "getwindowpid"]]


def test_process_name_for_pid_reads_proc_comm(tmp_path: Path) -> None:
    process = tmp_path / "4242"
    process.mkdir()
    (process / "comm").write_text("steam\n", encoding="utf-8")

    assert wayland_identity.process_name_for_pid(4242, proc_root=tmp_path) == "steam"


@pytest.mark.parametrize("process_id", ("0\n", "4242\n"))
def test_kwin_detection_falls_back_to_window_class_without_process_name(
    monkeypatch: pytest.MonkeyPatch,
    process_id: str,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        output = process_id if len(calls) == 1 else "org.kde.dolphin\n"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.wayland_identity.subprocess.run", fake_run
    )
    monkeypatch.setattr(wayland_identity, "process_name_for_pid", lambda _: "")

    assert wayland_identity.detect_kwin_active_app_id() == "org.kde.dolphin"
    assert calls == [
        ["kdotool", "getactivewindow", "getwindowpid"],
        ["kdotool", "getactivewindow", "getwindowclassname"],
    ]


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


def test_custom_active_app_command_resolves_pid_to_compatible_process_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []

    def fake_run(command: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert kwargs["shell"] is True
        assert kwargs["check"] is True
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 2.0
        return subprocess.CompletedProcess(command, 0, stdout="4242\n", stderr="")

    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.app_identity.subprocess.run", fake_run
    )
    monkeypatch.setattr(app_identity, "process_name_for_pid", lambda pid: "steam")

    assert resolve_app_id(active_app_command="active-window-pid") == "steam"
    assert commands == ["active-window-pid"]


def test_failed_custom_active_app_command_falls_back_to_pywinctl(
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
        "bitwarden_autofiller.desktop.app_identity.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, "private-command", stderr="private output")
        ),
    )
    monkeypatch.setattr(app_identity, "import_module", lambda _: pywinctl)

    assert resolve_app_id(active_app_command="private-command") == "Steam"


def test_custom_active_app_command_failure_is_safe_when_native_detection_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.app_identity.sys.platform", "linux"
    )
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.app_identity.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            "private-command", 0, stdout="not-a-pid\n", stderr="private-output"
        ),
    )
    monkeypatch.setattr(
        app_identity,
        "detect_wlr_active_app_id",
        lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    monkeypatch.setattr(
        app_identity,
        "detect_kwin_active_app_id",
        lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )

    with pytest.raises(ActiveApplicationUnavailable):
        resolve_app_id(active_app_command="private-command")

    assert "private-command" not in caplog.text
    assert "private-output" not in caplog.text


def test_active_app_verifier_compares_normalized_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_identity, "resolve_app_id", lambda **_: "Steam")
    verifier = ActiveApplicationVerifier("pcprocess://steam?actions=14")

    verifier.verify()

    assert not verifier.unverified


def test_active_app_verifier_cancels_when_focus_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_identity, "resolve_app_id", lambda **_: "browser")
    verifier = ActiveApplicationVerifier("steam")

    with pytest.raises(ActiveApplicationUnavailable, match="focused application"):
        verifier.verify()


def test_active_app_verifier_requires_opt_in_when_detection_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(**_: object) -> str:
        raise ActiveApplicationUnavailable("native detector unavailable")

    monkeypatch.setattr(app_identity, "resolve_app_id", unavailable)
    verifier = ActiveApplicationVerifier("steam")
    allowed_verifier = ActiveApplicationVerifier("steam", allow_unverified=True)

    with pytest.raises(ActiveApplicationUnavailable, match="explicitly allow"):
        verifier.verify()

    allowed_verifier.verify()
    allowed_verifier.verify()
    assert allowed_verifier.unverified
