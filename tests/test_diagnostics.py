import subprocess
from types import SimpleNamespace

import pytest

from bitwarden_autofiller.desktop import diagnostics
from bitwarden_autofiller.desktop.app_identity import (
    ActiveApplicationUnavailable,
    ActiveWindowIdentity,
)


def test_diagnostics_are_secret_free_and_report_gui_clipboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.sys.platform", "win32"
    )
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(
        diagnostics,
        "resolve_active_window_identity",
        lambda **_: ActiveWindowIdentity(
            "private-app-name", "private-window-id", "kwin"
        ),
    )

    report = diagnostics.collect_diagnostics(gui_clipboard_available=True)
    rendered = diagnostics.format_diagnostics(report)

    assert [item.status for item in report] == [
        "not required",
        "not required",
        "available",
        "available",
    ]
    assert "no input was sent" in rendered
    assert "private-app-name" not in rendered
    assert "private-window-id" not in rendered
    assert "clipboard contents" not in rendered.casefold()


def test_wayland_diagnostics_probe_portal_without_opening_input_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.sys.platform", "linux"
    )
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.shutil.which",
        lambda name: "/usr/bin/busctl" if name == "busctl" else None,
    )
    commands: list[list[str]] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 2.0
        return subprocess.CompletedProcess(
            command, 0, stdout=".ConnectToEIS method oa{sv}h -\n", stderr=""
        )

    def forbidden_session() -> object:
        raise AssertionError("Diagnostics must not open an input session")

    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.subprocess.run", fake_run
    )
    monkeypatch.setattr(diagnostics, "find_library", lambda _: "/lib/libxkbcommon.so")
    monkeypatch.setattr(
        diagnostics,
        "import_module",
        lambda _: SimpleNamespace(
            EiType=SimpleNamespace(connect_portal=forbidden_session)
        ),
    )
    monkeypatch.setattr(
        diagnostics,
        "resolve_active_window_identity",
        lambda **_: ActiveWindowIdentity("steam", "kwin-window", "kwin"),
    )

    report = diagnostics.collect_diagnostics(gui_clipboard_available=True)

    assert [item.status for item in report] == [
        "available",
        "not probed",
        "available",
        "available",
    ]
    assert commands == [
        [
            "/usr/bin/busctl",
            "--user",
            "introspect",
            diagnostics._PORTAL_SERVICE,
            diagnostics._PORTAL_PATH,
            diagnostics._REMOTE_DESKTOP_INTERFACE,
        ]
    ]


def test_diagnostics_report_missing_wayland_dependencies_without_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.sys.platform", "linux"
    )
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.shutil.which", lambda _: None
    )
    monkeypatch.setattr(diagnostics, "find_library", lambda _: None)
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.import_module",
        lambda _: (_ for _ in ()).throw(ModuleNotFoundError("eitype")),
    )
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.util.find_spec", lambda _: None
    )
    monkeypatch.setattr(
        diagnostics,
        "resolve_active_window_identity",
        lambda **_: (_ for _ in ()).throw(ActiveApplicationUnavailable("not detected")),
    )

    report = diagnostics.collect_diagnostics()

    assert [item.status for item in report] == [
        "unknown",
        "unavailable",
        "unavailable",
        "unavailable",
    ]


def test_diagnostics_report_missing_portal_interface_and_gui_clipboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.sys.platform", "linux"
    )
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.shutil.which",
        lambda name: "/usr/bin/busctl" if name == "busctl" else None,
    )
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.subprocess.run",
        lambda command, **_: subprocess.CompletedProcess(
            command, 0, stdout="No RemoteDesktop interface\n", stderr=""
        ),
    )
    monkeypatch.setattr(diagnostics, "find_library", lambda _: None)
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.diagnostics.import_module",
        lambda _: (_ for _ in ()).throw(ModuleNotFoundError("eitype")),
    )
    monkeypatch.setattr(
        diagnostics,
        "resolve_active_window_identity",
        lambda **_: ActiveWindowIdentity("steam"),
    )

    report = diagnostics.collect_diagnostics(gui_clipboard_available=False)

    assert report[0].status == "unavailable"
    assert report[2].status == "unavailable"
    assert report[2].detail == "The GUI clipboard object is unavailable."
