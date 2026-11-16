import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLineEdit

from bitwarden_autofiller.desktop.app_identity import ActiveApplicationUnavailable
from bitwarden_autofiller.desktop.gui import AccountRow, BitwardenAutofillerWindow
from bitwarden_autofiller.filling.actions import parse_action_sequence
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

    window = BitwardenAutofillerWindow(settings=settings)

    assert window.windowTitle() == "Bitwarden Autofiller"
    assert window.findChild(QLineEdit, "appIdEdit") is window.app_id_edit
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
    window.password_edit.setText("do-not-persist-this-password")
    window.close()
    app.processEvents()
    settings.sync()

    assert not settings.contains("password")
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
    window = BitwardenAutofillerWindow(settings=settings)
    monkeypatch.setattr(
        "bitwarden_autofiller.desktop.gui.resolve_app_id", lambda: "Steam"
    )

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
    assert "Detected app ID" in window.status_label.text()
    window.close()
    app.processEvents()


def test_active_app_detection_explains_wayland_manual_id_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    def unavailable() -> str:
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
