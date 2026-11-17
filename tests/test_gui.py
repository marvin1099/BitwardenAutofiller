import json
import os
import sys
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from bitwarden_autofiller.desktop import app_identity
from bitwarden_autofiller.desktop import gui as gui_module
from bitwarden_autofiller.desktop.app_identity import (
    ActiveApplicationUnavailable,
    ActiveWindowIdentity,
)
from bitwarden_autofiller.desktop.diagnostics import DiagnosticItem
from bitwarden_autofiller.desktop.gui import (
    AccountRow,
    BitwardenAutofillerWindow,
    _operation_error_message,
)
from bitwarden_autofiller.desktop.platforms import InputBackendError, LazyInputAdapter
from bitwarden_autofiller.filling.actions import parse_action_sequence
from bitwarden_autofiller.filling.execution import PartialFillError
from bitwarden_autofiller.filling.workflow import FillResult
from bitwarden_autofiller.vault.bitwarden import BitwardenCLI
from bitwarden_autofiller.vault.items import LoginCredentials, LoginSummary


class FakeVaultService:
    def __init__(self, summary: LoginSummary) -> None:
        self.summary = summary
        self.events: list[str] = []

    def list_matches(self, _app_id: str) -> tuple[LoginSummary, ...]:
        self.events.append("list_matches")
        return (self.summary,)

    def sync(self) -> None:
        self.events.append("sync")

    def get_login(self, _app_id: str, item_id: str) -> LoginCredentials:
        return LoginCredentials(item_id, username="alice", password="secret-password")

    def get_totp(self, _app_id: str, _item_id: str) -> str:
        return "123456"

    def close(self) -> None:
        self.events.append("close")


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
    assert window.bw_system_ca_check.isChecked()
    assert not window.bw_ca_certificate_edit.text()
    assert window.page_stack.currentWidget() is window.vault_page
    assert not window.advanced_settings.toggle_button.isChecked()
    assert window.advanced_settings.content_widget.isHidden()
    assert window.findChild(QLineEdit, "masterPasswordEdit") is window.password_edit
    assert window.password_edit.echoMode() == QLineEdit.EchoMode.Password
    assert not window.fill_button.isEnabled()
    assert not window.refresh_accounts_button.isEnabled()
    assert not window.sync_vault_button.isEnabled()
    assert window.last_sync_label.text() == "Last successful sync: never"
    assert window.account_search_edit.placeholderText() == "Search by name or username"
    assert window.account_sort_combo.count() == 2
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
    window.accounts_page_button.click()
    assert window.page_stack.currentWidget() is window.accounts_page
    window.vault_page_button.click()
    assert window.page_stack.currentWidget() is window.vault_page

    window.email_edit.setText("alice@example.test")
    window.active_app_command_edit.setText("printf 4242")
    window.bw_system_ca_check.setChecked(False)
    window.bw_ca_certificate_edit.setText("/tmp/local-ca.pem")
    window.allow_unverified_target_check.setChecked(True)
    window.password_edit.setText("do-not-persist-this-password")
    window.close()
    app.processEvents()
    settings.sync()

    assert not settings.contains("password")
    assert settings.value("active_app_command") == "printf 4242"
    assert settings.value("bw_system_ca") is False
    assert settings.value("bw_ca_certificate") == "/tmp/local-ca.pem"
    assert not settings.contains("allow_unverified_target")
    assert "do-not-persist-this-password" not in settings_path.read_text(
        encoding="utf-8"
    )


def test_gui_ignores_invalid_sync_time_and_toggles_advanced_controls(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("last_sync_at", "not-a-timestamp")
    window = BitwardenAutofillerWindow(settings=settings)

    assert window.last_sync_label.text() == "Last successful sync: never"
    with pytest.raises(ValueError, match="Unknown app page"):
        window._show_page("missing")

    window.advanced_settings.toggle_button.click()
    assert not window.advanced_settings.content_widget.isHidden()
    window.advanced_settings.toggle_button.click()
    assert window.advanced_settings.content_widget.isHidden()

    window.close()
    app.processEvents()


def test_gui_passes_ca_settings_to_bitwarden_cli_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    created: list[tuple[str | Path, bool, str | Path | None]] = []
    service = FakeVaultService(
        LoginSummary("entry", "Example", "alice", ("pcprocess://steam",))
    )

    def cli_factory(
        executable: str | Path,
        *,
        use_system_ca: bool = True,
        ca_certificate: str | Path | None = None,
    ) -> BitwardenCLI:
        created.append((executable, use_system_ca, ca_certificate))
        return cast(BitwardenCLI, object())

    window = BitwardenAutofillerWindow(settings=settings, cli_factory=cli_factory)
    window.bw_path_edit.setText("/usr/bin/bw")
    window.bw_system_ca_check.setChecked(False)
    window.bw_ca_certificate_edit.setText("/tmp/local-ca.pem")
    monkeypatch.setattr(
        gui_module, "authenticate_vault", lambda *_args, **_kwargs: service
    )
    monkeypatch.setattr(window, "_connected", lambda _service: None)

    def run_worker(operation: object, on_complete: object) -> None:
        assert callable(operation) and callable(on_complete)
        on_complete(operation())

    monkeypatch.setattr(window, "_start_worker", run_worker)
    window._connect_to_vault()

    assert created == [("/usr/bin/bw", False, "/tmp/local-ca.pem")]
    window.close()
    app.processEvents()


def test_sync_button_syncs_vault_then_reloads_mapped_accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    summary = LoginSummary("entry", "Example", "alice", ("pcprocess://steam",))
    service = FakeVaultService(summary)
    window = BitwardenAutofillerWindow(settings=settings)
    window._service = service  # type: ignore[assignment]
    window.app_id_edit.setText("steam")
    window._refresh_buttons()

    def run_worker(operation: object, on_complete: object) -> None:
        assert callable(operation) and callable(on_complete)
        on_complete(operation())

    monkeypatch.setattr(window, "_start_worker", run_worker)
    assert window.sync_vault_button.isEnabled()

    window.sync_vault_button.click()

    assert service.events == ["sync", "list_matches"]
    assert window._matches == (summary,)
    assert window.status_label.text() == "Mapped accounts refreshed."
    window.close()
    app.processEvents()


def test_gui_handles_missing_vault_and_target_state(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)

    window._sync_vault()
    assert "Connect to the vault" in window.status_label.text()
    window._load_accounts()
    assert "Connect to the vault" in window.status_label.text()
    window._select_target_after_connection()
    window._start_fill_countdown()
    assert "Connect to the vault first" in window.status_label.text()
    window._account_action_requested("missing", "copy_password")
    assert "Connect to the vault" in window.status_label.text()
    window._disconnect_from_vault()
    assert window.page_stack.currentWidget() is window.vault_page
    assert (
        window.accounts_status_label.text() == "Connect to the vault to load accounts."
    )

    service = FakeVaultService(
        LoginSummary("entry", "Example", "alice", ("pcprocess://steam",))
    )
    window._service = service  # type: ignore[assignment]
    window._load_accounts()
    assert "Enter the target application's app ID first" in window.status_label.text()
    window.app_id_edit.setText("steam")
    load_requests: list[bool] = []
    window._load_accounts = lambda: load_requests.append(True)  # type: ignore[method-assign]
    window._start_fill_countdown()
    assert load_requests == [True]
    window._loaded_app_id = "steam"
    window._matches = ()
    window._start_fill_countdown()
    assert "No Bitwarden login is mapped" in window.status_label.text()

    window._service = None
    window.close()
    app.processEvents()
    assert service.events == []


def test_successful_sync_without_target_is_timestamped(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)

    window._vault_synced(None)

    assert settings.value("last_sync_at")
    assert window.last_sync_label.text().startswith("Last successful sync:")
    assert "Enter an application ID" in window.status_label.text()
    assert window.page_stack.currentWidget() is window.accounts_page
    window.close()
    app.processEvents()


def test_gui_browse_ca_and_worker_error_are_reported_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    selected_paths = iter(("", str(tmp_path / "test-ca.pem")))
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (next(selected_paths), ""),
    )

    window._browse_bw_ca_certificate()
    assert not window.bw_ca_certificate_edit.text()
    window._browse_bw_ca_certificate()
    assert window.bw_ca_certificate_edit.text() == str(tmp_path / "test-ca.pem")

    def fail() -> None:
        raise RuntimeError("private error details")

    window._run_operation(fail, lambda _result: None)
    assert window.status_label.text() == (
        "The operation failed; check Bitwarden and desktop permissions."
    )
    assert not window._busy
    window.close()
    app.processEvents()


def test_gui_close_waits_for_active_worker(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    window._active_future = Future()

    assert not window.close()
    assert "wait for the active operation" in window.status_label.text()

    window._active_future = None
    window.close()
    app.processEvents()


def test_main_configures_and_runs_the_qt_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    class FakeApplication:
        def __init__(self, arguments: list[str]) -> None:
            calls.append(arguments)

        def setApplicationName(self, name: str) -> None:
            calls.append(name)

        def exec(self) -> int:
            calls.append("exec")
            return 23

    class FakeWindow:
        def __init__(self) -> None:
            calls.append("window")

        def show(self) -> None:
            calls.append("show")

    monkeypatch.setattr(gui_module, "configure_logging", lambda: calls.append("log"))
    monkeypatch.setattr(gui_module, "QApplication", FakeApplication)
    monkeypatch.setattr(gui_module, "BitwardenAutofillerWindow", FakeWindow)

    assert gui_module.main(["--mock-argument"]) == 23
    assert calls == [
        "log",
        [sys.argv[0], "--mock-argument"],
        "Bitwarden Autofiller",
        "window",
        "show",
        "exec",
    ]


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
    assert not row.isWindow()
    assert row.parentWidget() is window.accounts_content
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


def test_accounts_can_be_searched_and_sorted_without_displaying_usernames(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    summaries = (
        LoginSummary("gamma", "Gamma", "alice@example.test", ("pcprocess://steam",)),
        LoginSummary("alpha", "alpha", "zed@example.test", ("pcprocess://steam",)),
        LoginSummary("beta", "Beta", "bob@example.test", ("pcprocess://steam",)),
    )

    window._accounts_loaded("steam", summaries)

    assert [
        window._account_rows[item_id].name_label.text()
        for item_id in ("alpha", "beta", "gamma")
    ] == ["alpha", "Beta", "Gamma"]
    assert window._account_rows["gamma"].name_label.text() == "Gamma"
    assert "alice@example.test" not in window._account_rows["gamma"].name_label.text()

    window.account_search_edit.setText("BOB@EXAMPLE.TEST")

    assert not window._account_rows["beta"].isHidden()
    assert window._account_rows["alpha"].isHidden()
    assert window._account_rows["gamma"].isHidden()
    assert "Showing 1 of 3" in window.accounts_status_label.text()

    window.account_search_edit.setText("not-a-match")
    assert all(row.isHidden() for row in window._account_rows.values())
    assert "No accounts match the search" in window.accounts_status_label.text()

    window.account_search_edit.clear()
    window.account_sort_combo.setCurrentIndex(1)
    assert [
        window.accounts_rows_layout.indexOf(window._account_rows[item_id])
        for item_id in ("gamma", "beta", "alpha")
    ] == [0, 1, 2]

    window.close()
    app.processEvents()


def test_account_actions_validate_mapping_and_copy_only_requested_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    summary = LoginSummary("entry", "Example", "alice", ("pcprocess://steam",))
    service = FakeVaultService(summary)
    window._service = service  # type: ignore[assignment]
    window._matches = (summary,)
    window._loaded_app_id = "steam"
    window.app_id_edit.setText("steam")

    copied_values: list[str] = []
    window.clipboard_requested.connect(copied_values.append)

    def run_worker(operation: object, on_complete: object) -> None:
        assert callable(operation) and callable(on_complete)
        on_complete(operation())

    monkeypatch.setattr(window, "_start_worker", run_worker)

    window._account_action_requested("stale", "copy_username")
    assert "no longer in the current mapping" in window.status_label.text()
    window._account_action_requested("entry", "unknown")
    assert "Unknown account action" in window.status_label.text()

    window.app_id_edit.setText("other-app")
    window._account_action_requested("entry", "copy_username")
    assert "Load accounts for the selected app ID first" in window.status_label.text()
    window.app_id_edit.setText("steam")
    window._account_action_requested("entry", "copy_username")

    assert copied_values == ["alice"]
    assert (
        window.status_label.text()
        == "Copied the requested account value to the clipboard."
    )
    assert service.events == ["list_matches"]

    missing_username = FakeVaultService(
        LoginSummary("empty", "No username", "", ("pcprocess://steam",))
    )
    with pytest.raises(ValueError, match="no username value"):
        window._copy_account_value(missing_username, "steam", "empty", "copy_username")

    window._service = None
    window.close()
    app.processEvents()


def test_accounts_loaded_from_worker_stay_embedded_in_accounts_page(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    summary = LoginSummary("entry", "Example", "alice", ("pcprocess://steam",))
    window._service = FakeVaultService(summary)  # type: ignore[assignment]
    window.app_id_edit.setText("steam")
    window._show_page("accounts")
    loop = QEventLoop()
    window._load_accounts()
    monitor = QTimer()
    monitor.setInterval(10)
    monitor.timeout.connect(
        lambda: (
            loop.quit() if window._matches and window._active_future is None else None
        )
    )
    monitor.start()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    monitor.stop()

    assert window._active_future is None
    row = window._account_rows["entry"]
    assert not row.isWindow()
    assert row.parentWidget() is window.accounts_content
    assert window.page_stack.currentWidget() is window.accounts_page
    window._service = None
    window.close()
    app.processEvents()


def test_gui_smoke_uses_only_a_mock_bw_for_connect_sync_and_account_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings_path = tmp_path / "settings.ini"
    settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    fake_bw = tmp_path / "fake_bw.py"
    invocation_log = tmp_path / "fake_bw_invocations.jsonl"
    fake_bw.write_text(
        "import json, os, sys\n"
        "arguments = sys.argv[1:]\n"
        "command = arguments[0]\n"
        "record = {'arguments': arguments, 'password_present': bool(os.environ.get("
        "'BW_AUTOFILLER_MASTER_PASSWORD')), 'session': os.environ.get('BW_SESSION')}\n"
        "with open(os.environ['BW_FAKE_LOG'], 'a', encoding='utf-8') as log:\n"
        "    log.write(json.dumps(record) + '\\n')\n"
        "if command == 'status':\n"
        "    data = {'template': {'status': 'locked'}}\n"
        "elif command == 'unlock':\n"
        "    data = {'raw': 'mock-session-key'}\n"
        "elif command == 'list':\n"
        "    data = [{'id': 'mock-steam-login', 'type': 1, "
        "'name': 'Mock Steam Account', 'login': {'username': 'mock-user', "
        "'password': 'never-fetch-this-password', "
        "'uris': [{'uri': 'pcprocess://steam'}]}}]\n"
        "elif command == 'sync':\n"
        "    data = None\n"
        "else:\n"
        "    raise SystemExit(3)\n"
        "print(json.dumps({'success': True, 'data': data}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BW_FAKE_LOG", str(invocation_log))
    monkeypatch.delenv("BW_SESSION", raising=False)
    monkeypatch.delenv("BW_AUTOFILLER_MASTER_PASSWORD", raising=False)

    def mock_cli_factory(
        executable: str | Path,
        *,
        use_system_ca: bool = True,
        ca_certificate: str | Path | None = None,
    ) -> BitwardenCLI:
        assert str(executable) == "mock-bw"
        return BitwardenCLI(
            (sys.executable, str(fake_bw)),
            use_system_ca=use_system_ca,
            ca_certificate=ca_certificate,
        )

    def wait_until(condition: Callable[[], bool]) -> None:
        loop = QEventLoop()
        poll = QTimer()
        timeout = QTimer()

        def check_condition() -> None:
            if condition():
                loop.quit()

        poll.setInterval(10)
        poll.timeout.connect(check_condition)
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        poll.start()
        timeout.start(5000)
        check_condition()
        if not condition():
            loop.exec()
        poll.stop()
        timeout.stop()
        assert condition(), "GUI operation did not complete before the timeout"

    window = BitwardenAutofillerWindow(settings=settings, cli_factory=mock_cli_factory)
    window.bw_path_edit.setText("mock-bw")
    window.email_edit.setText("mock@example.test")
    window.password_edit.setText("mock-only-password")
    window.app_id_edit.setText("steam")
    try:
        window.connect_button.click()
        wait_until(
            lambda: (
                window._service is not None
                and window._loaded_app_id == "steam"
                and window._active_future is None
            )
        )

        assert window.password_edit.text() == ""
        assert window.page_stack.currentWidget() is window.accounts_page
        assert window._matches[0].id == "mock-steam-login"
        assert not window._account_rows["mock-steam-login"].isWindow()

        window.account_search_edit.setText("MOCK-USER")
        assert not window._account_rows["mock-steam-login"].isHidden()
        window.account_search_edit.clear()

        window.sync_vault_button.click()

        def sync_and_reload_completed() -> bool:
            if not invocation_log.exists():
                return False
            calls = [
                json.loads(line)
                for line in invocation_log.read_text(encoding="utf-8").splitlines()
            ]
            return (
                any(call["arguments"][0] == "sync" for call in calls)
                and sum(call["arguments"][0] == "list" for call in calls) >= 2
                and window._active_future is None
            )

        wait_until(sync_and_reload_completed)

        calls = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        assert [call["arguments"][0] for call in calls] == [
            "status",
            "unlock",
            "list",
            "sync",
            "list",
        ]
        assert calls[1]["password_present"]
        assert calls[1]["session"] is None
        assert all(
            "mock-only-password" not in " ".join(call["arguments"]) for call in calls
        )
        assert calls[2]["session"] == "mock-session-key"
        assert calls[3]["session"] == "mock-session-key"
        assert "Last successful sync: never" not in window.last_sync_label.text()
        assert settings.value("last_sync_at")
        assert "never-fetch-this-password" not in invocation_log.read_text(
            encoding="utf-8"
        )
    finally:
        window.close()
        app.processEvents()

    restored_settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    restored_window = BitwardenAutofillerWindow(settings=restored_settings)
    assert "Last successful sync: never" not in restored_window.last_sync_label.text()
    restored_window.close()
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


def test_gui_diagnostics_button_shows_report_without_creating_input_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    calls: list[tuple[str | None, bool | None]] = []
    dialogs: list[tuple[str, str]] = []

    def collect(
        *,
        active_app_command: str | None = None,
        gui_clipboard_available: bool | None = None,
    ) -> tuple[DiagnosticItem, ...]:
        calls.append((active_app_command, gui_clipboard_available))
        return (DiagnosticItem("Clipboard", "available", "Not read."),)

    def unexpected_adapter(**_kwargs: object) -> object:
        raise AssertionError("Diagnostics must not initialize input")

    def run_worker(operation: object, on_complete: object) -> None:
        assert callable(operation) and callable(on_complete)
        on_complete(operation())

    def show_dialog(
        _parent: QWidget, title: str, text: str
    ) -> QMessageBox.StandardButton:
        dialogs.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(gui_module, "collect_diagnostics", collect)
    monkeypatch.setattr(gui_module, "create_input_adapter", unexpected_adapter)
    monkeypatch.setattr(window, "_start_worker", run_worker)
    monkeypatch.setattr(QMessageBox, "information", show_dialog)
    window.active_app_command_edit.setText("trusted-active-pid-command")

    window.diagnostics_button.click()

    assert calls == [("trusted-active-pid-command", True)]
    assert dialogs and dialogs[0][0] == "Desktop diagnostics"
    assert "no input was sent" in dialogs[0][1]
    assert "Clipboard: available" in dialogs[0][1]
    assert "no input was sent" in window.status_label.text()
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
    message = _operation_error_message(PartialFillError(1, 1))

    assert "Earlier fields or clipboard contents may have changed" in message
    assert _operation_error_message(ValueError("invalid setting")) == "invalid setting"
    assert _operation_error_message(RuntimeError("private failure")) == (
        "The operation failed; check Bitwarden and desktop permissions."
    )


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
    assert window._active_future is None
    window._service = None
    window.close()
    app.processEvents()


def test_fill_countdown_handles_profiles_and_releases_queued_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = BitwardenAutofillerWindow(settings=settings)
    window._service = FakeVaultService(
        LoginSummary("entry", "Example", "alice", ("pcprocess://steam",))
    )  # type: ignore[assignment]
    window._loaded_app_id = "steam"
    window.app_id_edit.setText("steam")
    window._matches = (
        LoginSummary(
            "entry",
            "Example",
            "alice",
            (
                "pcprocess://steam?actions=14",
                "pcprocess://steam?actions=24",
            ),
        ),
    )

    window._start_fill_countdown()
    assert "Conflicting autofill profiles" in window.status_label.text()

    window._matches = (
        LoginSummary("entry", "Example", "alice", ("pcprocess://steam",)),
    )
    window.actions_edit.setText("not-an-action")
    window._start_fill_countdown()
    assert "Unknown fill action" in window.status_label.text()

    window.actions_edit.clear()
    window.delay_spin.setValue(2)
    window.allow_unverified_target_check.setChecked(True)
    fill_calls: list[tuple[str | None, str]] = []

    def record_fill(_actions: object, item_id: str | None, app_id: str) -> None:
        fill_calls.append((item_id, app_id))

    monkeypatch.setattr(
        window,
        "_begin_fill",
        record_fill,
    )
    window._start_fill_countdown()
    assert window._countdown_timer.isActive()
    assert "Warning: unverified filling is enabled" in window.status_label.text()

    window._countdown_tick()
    assert window._countdown == 1
    window._countdown_tick()
    assert len(fill_calls) == 1
    assert fill_calls == [(None, "steam")]
    window._countdown_timer.stop()

    detection_calls: list[bool] = []
    monkeypatch.setattr(
        window, "_detect_current_app_now", lambda: detection_calls.append(True)
    )
    window._pending_app_detection = True
    window._countdown = 1
    window._countdown_tick()
    assert detection_calls == [True]
    assert not window._pending_app_detection

    window._countdown = 1
    window._pending_fill_actions = None
    window._pending_fill_app_id = None
    window._countdown_tick()
    assert not window._busy

    window._service = None
    window.close()
    app.processEvents()


@pytest.mark.parametrize("item_id", ("entry", None))
def test_begin_fill_uses_selected_or_all_mapped_workflow_and_closes_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, item_id: str | None
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / f"settings-{item_id}.ini"), QSettings.Format.IniFormat
    )
    window = BitwardenAutofillerWindow(settings=settings)
    window._service = FakeVaultService(
        LoginSummary("entry", "Example", "alice", ("pcprocess://steam",))
    )  # type: ignore[assignment]
    window.app_id_edit.setText("steam")

    class RecordingAdapter:
        closed = False

        def type_text(self, _text: str) -> None:
            return

        def press_key(self, _key: str) -> None:
            return

        def copy_text(self, _text: str) -> None:
            return

        def close(self) -> None:
            self.closed = True

    adapter = RecordingAdapter()
    verifier_calls: list[str] = []

    class FakeVerifier:
        unverified = True

        def __init__(self, app_id: str, **_kwargs: object) -> None:
            verifier_calls.append(app_id)

        def verify(self) -> None:
            verifier_calls.append("verified")

    workflow_calls: list[str] = []

    def run_fill(*args: object, **kwargs: object) -> FillResult:
        workflow_calls.append("selected" if item_id is not None else "all")
        input_adapter = args[4] if item_id is not None else args[3]
        cast(LazyInputAdapter, input_adapter).prepare()
        before_input = kwargs["before_input"]
        assert callable(before_input)
        before_input()
        return FillResult(1, 1, 2)

    def run_worker(operation: object, on_complete: object) -> None:
        assert callable(operation) and callable(on_complete)
        on_complete(operation())

    monkeypatch.setattr(gui_module, "ActiveApplicationVerifier", FakeVerifier)
    monkeypatch.setattr(gui_module, "create_input_adapter", lambda **_kwargs: adapter)
    monkeypatch.setattr(gui_module, "fill_selected_login", run_fill)
    monkeypatch.setattr(gui_module, "fill_for_app", run_fill)
    monkeypatch.setattr(window, "_start_worker", run_worker)
    window.allow_unverified_target_check.setChecked(True)

    window._begin_fill(parse_action_sequence("14"), item_id, "steam")

    assert workflow_calls == ["selected" if item_id is not None else "all"]
    assert verifier_calls == ["steam", "verified"]
    assert adapter.closed
    assert "Warning: active application could not be verified" in (
        window.status_label.text()
    )
    assert not window.allow_unverified_target_check.isChecked()
    window._service = None
    window.close()
    app.processEvents()
