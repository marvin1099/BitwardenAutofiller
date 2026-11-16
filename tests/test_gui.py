import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QLineEdit

from bitwarden_autofiller.desktop import app_identity
from bitwarden_autofiller.desktop.app_identity import (
    ActiveApplicationUnavailable,
    ActiveWindowIdentity,
)
from bitwarden_autofiller.desktop.gui import (
    AccountRow,
    BitwardenAutofillerWindow,
    _OperationWorker,
)
from bitwarden_autofiller.desktop.platforms import InputBackendError
from bitwarden_autofiller.filling.actions import parse_action_sequence
from bitwarden_autofiller.filling.execution import PartialFillError
from bitwarden_autofiller.vault.items import LoginCredentials, LoginSummary


class FakeVaultService:
    def __init__(self, summary: LoginSummary) -> None:
        self.summary = summary

    def list_matches(self, _app_id: str) -> tuple[LoginSummary, ...]:
        return (self.summary,)

    def get_login(self, _app_id: str, item_id: str) -> LoginCredentials:
        return LoginCredentials(item_id, username="alice", password="secret-password")

    def get_totp(self, _app_id: str, _item_id: str) -> str:
        return "123456"

    def close(self) -> None:
        pass


def test_gui_builds_without_connecting_to_a_real_vault(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    settings_path = tmp_path / "settings.ini"
    settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    settings.setValue("active_app_command", "initial-pid-command")

    window = BitwardenAutofillerWindow(settings=settings)

    assert window.windowTitle() == "Bitwarden Autofiller"
    assert window.findChild(QLineEdit, "appIdEdit") is window.app_id_edit
    assert (
        window.findChild(QLineEdit, "activeAppCommandEdit")
        is window.active_app_command_edit
    )
    assert window.active_app_command_edit.text() == "initial-pid-command"
    assert not window.allow_unverified_target_check.isChecked()
    assert window.findChild(QLineEdit, "masterPasswordEdit") is window.password_edit
    assert window.password_edit.echoMode() == QLineEdit.EchoMode.Password
    assert not window.fill_button.isEnabled()
    assert not window.refresh_accounts_button.isEnabled()
    with pytest.raises(ValueError, match="app ID"):
        window._current_app_id()
    window.app_id_edit.setText("pcprocess://steam/")
    assert window._current_app_id() == "steam"
    window.actions_edit.setText("147")
    window._generate_uri()
    assert window.generated_uri_edit.text() == "pcprocess://steam?actions=147"
    assert window.copy_uri_button.isEnabled()
    copied_uris: list[str] = []
    window.clipboard_requested.connect(copied_uris.append)
    window._copy_generated_uri()
    assert copied_uris == ["pcprocess://steam?actions=147"]

    window.email_edit.setText("alice@example.test")
    window.active_app_command_edit.setText("printf 4242")
    window.allow_unverified_target_check.setChecked(True)
    window.password_edit.setText("do-not-persist-this-password")
    window.close()
    app.processEvents()
    settings.sync()

    assert not settings.contains("password")
    assert settings.value("active_app_command") == "printf 4242"
    assert not settings.contains("allow_unverified_target")
    assert "do-not-persist-this-password" not in settings_path.read_text(
        encoding="utf-8"
    )


def test_accounts_view_shows_names_and_per_account_actions(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    summary = LoginSummary(
        "steam-entry",
        "Steam Personal",
        "alice",
        ("pcprocess://steam?actions=14",),
    )

    window._accounts_loaded("steam", (summary,))

    assert "1 account(s) mapped to steam" in window.accounts_status_label.text()
    row = window._account_rows["steam-entry"]
    assert isinstance(row, AccountRow)
    assert row.name_label.text() == "Steam Personal"
    emitted: list[tuple[str, str]] = []
    row.action_requested.connect(lambda item, action: emitted.append((item, action)))
    row.autofill_button.click()
    row.copy_username_button.click()
    row.copy_password_button.click()
    row.copy_totp_button.click()
    assert emitted == [
        ("steam-entry", "autofill"),
        ("steam-entry", "copy_username"),
        ("steam-entry", "copy_password"),
        ("steam-entry", "copy_totp"),
    ]
    assert window._actions_for_account(summary, "steam") == parse_action_sequence("14")

    window.close()
    app.processEvents()


def test_active_app_detection_uses_a_focus_countdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("active_app_command", "custom-pid-command")
    window = BitwardenAutofillerWindow(settings=settings)
    detected_commands: list[str | None] = []

    def detect(*, active_app_command: str | None = None) -> str:
        detected_commands.append(active_app_command)
        return "Steam"

    monkeypatch.setattr("bitwarden_autofiller.desktop.gui.resolve_app_id", detect)

    def run_worker(operation: object, on_complete: object) -> None:
        assert callable(operation) and callable(on_complete)
        on_complete(operation())

    monkeypatch.setattr(window, "_start_worker", run_worker)
    window.delay_spin.setValue(0)

    window._start_app_detection()
    assert window._pending_app_detection
    assert window._countdown == 3
    assert window._countdown_timer.isActive()
    window._countdown_timer.stop()
    window._pending_app_detection = False
    window._set_busy(False)
    window._detect_current_app_now()

    assert window.app_id_edit.text() == "Steam"
    assert detected_commands == ["custom-pid-command"]
    assert "Detected app ID" in window.status_label.text()
    window.close()
    app.processEvents()


def test_worker_clipboard_callback_is_synchronized_with_the_gui_thread(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)

    with ThreadPoolExecutor() as executor:
        result = executor.submit(window._copy_to_clipboard_from_worker, "unicode ☃")
        timer.timeout.connect(lambda: loop.quit() if result.done() else None)
        timer.start()
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        timer.stop()

        assert result.done()
        result.result(timeout=0)

    clipboard = QGuiApplication.clipboard()
    assert clipboard is not None
    assert clipboard.text() == "unicode ☃"

    cleanup_loop = QEventLoop()
    cleanup_timer = QTimer()
    with ThreadPoolExecutor() as executor:
        cleanup = executor.submit(
            window._clear_input_clipboard_from_worker, "unicode ☃"
        )
        cleanup_timer.timeout.connect(
            lambda: cleanup_loop.quit() if cleanup.done() else None
        )
        cleanup_timer.start(10)
        QTimer.singleShot(5000, cleanup_loop.quit)
        cleanup_loop.exec()
        cleanup_timer.stop()
        assert cleanup.done()
        cleanup.result(timeout=0)

    assert clipboard.text() == ""
    window.close()
    app.processEvents()


@pytest.mark.parametrize("replacement", ("new clipboard value", "unicode ☃"))
def test_worker_cleanup_preserves_newer_clipboard_contents(
    tmp_path: Path, replacement: str
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    clipboard = QGuiApplication.clipboard()
    assert clipboard is not None
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)

    with ThreadPoolExecutor() as executor:
        copied = executor.submit(window._copy_to_clipboard_from_worker, "unicode ☃")
        timer.timeout.connect(lambda: loop.quit() if copied.done() else None)
        timer.start()
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        timer.stop()
        assert copied.done()
        copied.result(timeout=0)

    clipboard.setText(replacement)
    cleanup_loop = QEventLoop()
    cleanup_timer = QTimer()
    with ThreadPoolExecutor() as executor:
        cleanup = executor.submit(
            window._clear_input_clipboard_from_worker, "unicode ☃"
        )
        cleanup_timer.timeout.connect(
            lambda: cleanup_loop.quit() if cleanup.done() else None
        )
        cleanup_timer.start(10)
        QTimer.singleShot(5000, cleanup_loop.quit)
        cleanup_loop.exec()
        cleanup_timer.stop()
        assert cleanup.done()
        cleanup.result(timeout=0)

    assert clipboard.text() == replacement
    window.close()
    app.processEvents()


def test_worker_clipboard_callback_reports_unavailable_gui_clipboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.gui.QGuiApplication.clipboard",
        staticmethod(lambda: None),
    )

    with pytest.raises(InputBackendError, match="Could not set text"):
        window._copy_to_clipboard_from_worker("unicode ☃")

    window.close()
    app.processEvents()


def test_active_app_detection_explains_wayland_manual_id_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    def unavailable(*, active_app_command: str | None = None) -> str:
        del active_app_command
        raise ActiveApplicationUnavailable("Wayland needs an explicit ID")

    monkeypatch.setattr("bitwarden_autofiller.desktop.gui.resolve_app_id", unavailable)
    window = BitwardenAutofillerWindow(settings=settings)

    def run_worker(operation: object, on_complete: object) -> None:
        assert callable(operation) and callable(on_complete)
        try:
            on_complete(operation())
        except ActiveApplicationUnavailable as error:
            window._operation_failed(str(error))

    monkeypatch.setattr(window, "_start_worker", run_worker)

    window._detect_current_app_now()

    assert "explicit ID" in window.status_label.text()
    window.close()
    app.processEvents()


def test_account_copy_actions_retrieve_only_the_requested_value(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    service = FakeVaultService(
        LoginSummary("steam-entry", "Steam Personal", "alice", ("pcprocess://steam",))
    )

    assert (
        window._copy_account_value(service, "steam", "steam-entry", "copy_username")
        == "alice"
    )
    assert (
        window._copy_account_value(service, "steam", "steam-entry", "copy_password")
        == "secret-password"
    )
    assert (
        window._copy_account_value(service, "steam", "steam-entry", "copy_totp")
        == "123456"
    )

    window.close()
    app.processEvents()


def test_gui_aborts_fill_if_focused_app_does_not_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    service = FakeVaultService(
        LoginSummary("steam-entry", "Steam Personal", "alice", ("pcprocess://steam",))
    )
    window._service = service  # type: ignore[assignment]
    window.app_id_edit.setText("steam")
    input_events: list[tuple[str, str]] = []

    class RecordingInput:
        def type_text(self, text: str) -> None:
            input_events.append(("type", text))

        def press_key(self, key: str) -> None:
            input_events.append(("key", key))

        def copy_text(self, text: str) -> None:
            input_events.append(("copy", text))

    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.gui.resolve_app_id",
        lambda explicit_app_id=None, **_: explicit_app_id or "browser",
    )
    monkeypatch.setattr(
        app_identity,
        "resolve_app_id",
        lambda explicit_app_id=None, **_: explicit_app_id or "browser",
    )
    monkeypatch.setattr(
        app_identity,
        "resolve_active_window_identity",
        lambda **_: ActiveWindowIdentity("browser", "test-window", "test"),
    )
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.gui.create_input_adapter",
        lambda **_: RecordingInput(),
    )

    def run_worker(operation: object, on_complete: object) -> None:
        assert callable(operation) and callable(on_complete)
        try:
            on_complete(operation())
        except ActiveApplicationUnavailable as error:
            window._operation_failed(str(error))

    monkeypatch.setattr(window, "_start_worker", run_worker)
    window._begin_fill(parse_action_sequence("14"), "steam-entry", "steam")

    assert input_events == []
    assert "focused application does not match" in window.status_label.text()
    window._service = None
    window.close()
    app.processEvents()


def test_gui_requires_opt_in_and_warns_if_active_app_cannot_be_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    summary = LoginSummary(
        "steam-entry", "Steam Personal", "alice", ("pcprocess://steam",)
    )
    service = FakeVaultService(summary)
    window._service = service  # type: ignore[assignment]
    window.app_id_edit.setText("steam")
    input_events: list[tuple[str, str]] = []
    verification_calls: list[str | None] = []

    class RecordingInput:
        def type_text(self, text: str) -> None:
            input_events.append(("type", text))

        def press_key(self, key: str) -> None:
            input_events.append(("key", key))

        def copy_text(self, text: str) -> None:
            input_events.append(("copy", text))

    def detect(
        explicit_app_id: str | None = None,
        *,
        active_app_command: str | None = None,
    ) -> str:
        if explicit_app_id:
            return explicit_app_id
        verification_calls.append(active_app_command)
        raise ActiveApplicationUnavailable("detector unavailable")

    def detect_identity(
        *, active_app_command: str | None = None
    ) -> ActiveWindowIdentity:
        verification_calls.append(active_app_command)
        raise ActiveApplicationUnavailable("detector unavailable")

    monkeypatch.setattr("bitwarden_autofiller.desktop.gui.resolve_app_id", detect)
    monkeypatch.setattr(app_identity, "resolve_app_id", detect)
    monkeypatch.setattr(app_identity, "resolve_active_window_identity", detect_identity)
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.gui.create_input_adapter",
        lambda **_: RecordingInput(),
    )

    def run_worker(operation: object, on_complete: object) -> None:
        assert callable(operation) and callable(on_complete)
        try:
            on_complete(operation())
        except ActiveApplicationUnavailable as error:
            window._operation_failed(str(error))

    monkeypatch.setattr(window, "_start_worker", run_worker)

    window._begin_fill(parse_action_sequence("14"), summary.id, "steam")
    assert input_events == []
    assert "explicitly allow an unverified target" in window.status_label.text()

    window.allow_unverified_target_check.setChecked(True)
    window._begin_fill(parse_action_sequence("14"), summary.id, "steam")

    assert input_events == [("type", "alice")]
    assert verification_calls == [None, None]
    assert "could not be verified" in window.status_label.text()
    assert not window.allow_unverified_target_check.isChecked()
    window._service = None
    window.close()
    app.processEvents()


def test_gui_shows_partial_fill_warning_instead_of_generic_error() -> None:
    worker = _OperationWorker(lambda: (_ for _ in ()).throw(PartialFillError(1, 1)))
    errors: list[str] = []
    worker.failed.connect(errors.append)

    worker.run()

    assert len(errors) == 1
    assert "Earlier fields or clipboard contents may have changed" in errors[0]


def test_fill_button_reports_invalid_action_sequences_without_starting_work(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    window._service = FakeVaultService(
        LoginSummary("steam-entry", "Steam Personal", "alice", ("pcprocess://steam",))
    )  # type: ignore[assignment]
    window._loaded_app_id = "steam"
    window._matches = (
        LoginSummary("steam-entry", "Steam Personal", "alice", ("pcprocess://steam",)),
    )
    window.app_id_edit.setText("steam")
    window.actions_edit.setText("invalid")

    window._start_fill_countdown()

    assert "Unknown fill action" in window.status_label.text()
    assert window._thread is None
    window._service = None
    window.close()
    app.processEvents()
