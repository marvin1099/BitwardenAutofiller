"""Responsive Qt desktop interface for Bitwarden autofill."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import (
    QByteArray,
    QMimeData,
    QObject,
    QSettings,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QCloseEvent, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bitwarden_autofiller.app_uri import build_app_uri, profile_actions_for_uris
from bitwarden_autofiller.desktop.app_identity import (
    ActiveApplicationUnavailable,
    ActiveApplicationVerifier,
    resolve_app_id,
)
from bitwarden_autofiller.desktop.diagnostics import (
    collect_diagnostics,
    format_diagnostics,
)
from bitwarden_autofiller.desktop.platforms import (
    InputBackendError,
    LazyInputAdapter,
    create_input_adapter,
)
from bitwarden_autofiller.filling.actions import (
    DEFAULT_ACTIONS,
    Action,
    parse_action_sequence,
)
from bitwarden_autofiller.filling.execution import PartialFillError
from bitwarden_autofiller.filling.workflow import (
    FillResult,
    FillService,
    fill_for_app,
    fill_selected_login,
)
from bitwarden_autofiller.logging_config import configure_logging
from bitwarden_autofiller.vault.authentication import (
    AuthenticationError,
    authenticate_vault,
)
from bitwarden_autofiller.vault.bitwarden import BitwardenCLI, BitwardenCLIError
from bitwarden_autofiller.vault.items import LoginSummary
from bitwarden_autofiller.vault.service import VaultService

_LOGGER = logging.getLogger(__name__)
APP_DETECTION_MINIMUM_SECONDS = 3
_TEMPORARY_CLIPBOARD_MARKER = "application/x-bitwarden-autofiller-temporary"


@dataclass(frozen=True, slots=True)
class _FillOutcome:
    result: FillResult
    active_app_unverified: bool


class _OperationWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self._operation = operation

    @Slot()
    def run(self) -> None:
        try:
            result = self._operation()
        except Exception as error:
            _LOGGER.warning("GUI operation failed (%s)", type(error).__name__)
            if isinstance(
                error,
                (
                    ActiveApplicationUnavailable,
                    AuthenticationError,
                    BitwardenCLIError,
                    InputBackendError,
                    PartialFillError,
                    ValueError,
                ),
            ):
                message = str(error)
            else:
                message = (
                    "The operation failed; check Bitwarden and desktop permissions."
                )
            self.failed.emit(message)
        else:
            self.completed.emit(result)


class AccountRow(QWidget):
    """A non-secret account label with explicit per-account actions."""

    action_requested = Signal(str, str)

    def __init__(self, summary: LoginSummary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item_id = summary.id
        self.name_label = QLabel(summary.name)
        self.name_label.setObjectName("accountNameLabel")
        self.name_label.setWordWrap(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.addWidget(self.name_label, 1)
        self.autofill_button = self._add_action(layout, "Autofill", "autofill")
        self.copy_username_button = self._add_action(
            layout, "Copy username", "copy_username"
        )
        self.copy_password_button = self._add_action(
            layout, "Copy password", "copy_password"
        )
        self.copy_totp_button = self._add_action(layout, "Copy TOTP", "copy_totp")

    def _add_action(self, layout: QHBoxLayout, label: str, action: str) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName(f"account_{action}_button")
        button.clicked.connect(
            lambda _checked=False, operation=action: self.action_requested.emit(
                self.item_id, operation
            )
        )
        layout.addWidget(button)
        return button


class BitwardenAutofillerWindow(QMainWindow):
    """One-window local autofill client; credentials are not stored in settings."""

    clipboard_requested = Signal(str)
    _input_clipboard_requested = Signal(str, object)
    _input_clipboard_cleanup_requested = Signal(str, object)

    def __init__(
        self,
        *,
        settings: QSettings | None = None,
        cli_factory: Callable[..., BitwardenCLI] = BitwardenCLI,
    ) -> None:
        super().__init__()
        self._settings = settings or QSettings("BitwardenAutofiller", "DesktopClient")
        self._cli_factory = cli_factory
        self._service: VaultService | None = None
        self._thread: QThread | None = None
        self._worker: _OperationWorker | None = None
        self._busy = False
        self._matches: tuple[LoginSummary, ...] = ()
        self._loaded_app_id: str | None = None
        self._account_rows: dict[str, AccountRow] = {}
        self._pending_fill_item_id: str | None = None
        self._pending_fill_actions: tuple[Action, ...] | None = None
        self._pending_fill_app_id: str | None = None
        self._pending_app_detection = False
        self._temporary_clipboard_text: str | None = None
        self._temporary_clipboard_token: str | None = None
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._countdown_tick)
        self._countdown = 0

        self.setWindowTitle("Bitwarden Autofiller")
        icon_path = Path(__file__).with_name("fillericon.png")
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(680, 540)
        self.resize(900, 720)
        self.clipboard_requested.connect(self._copy_to_clipboard)
        self._build_ui()
        self._input_clipboard_requested.connect(self._set_input_clipboard)
        self._input_clipboard_cleanup_requested.connect(self._clear_input_clipboard)
        self._restore_settings()

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        title = QLabel("Bitwarden Autofiller")
        title.setObjectName("windowTitle")
        title.setStyleSheet("font-size: 22px; font-weight: 600")
        layout.addWidget(title)

        explanation = QLabel(
            "Fill a desktop app login explicitly mapped in Bitwarden. "
            "On Wayland, configure detection or enter the app ID; the compositor "
            "controls input permission."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("introLabel")
        layout.addWidget(explanation)

        vault_box = QGroupBox("Vault")
        vault_form = QFormLayout(vault_box)
        self.email_edit = QLineEdit()
        self.email_edit.setObjectName("emailEdit")
        self.email_edit.setPlaceholderText("name@example.com")
        self.password_edit = QLineEdit()
        self.password_edit.setObjectName("masterPasswordEdit")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Asked for each connection; never saved")
        self.bw_path_edit = QLineEdit("bw")
        self.bw_path_edit.setObjectName("bitwardenCliPathEdit")
        self.bw_path_edit.setPlaceholderText("bw")
        self.bw_system_ca_check = QCheckBox("Use the system CA store for Bitwarden CLI")
        self.bw_system_ca_check.setObjectName("bwSystemCaCheck")
        self.bw_system_ca_check.setChecked(True)
        self.bw_system_ca_check.setToolTip(
            "Adds Node.js --use-system-ca when running bw. Existing NODE_OPTIONS "
            "are preserved; options already set in the environment remain active "
            "even if this is unchecked."
        )
        self.bw_ca_certificate_edit = QLineEdit()
        self.bw_ca_certificate_edit.setObjectName("bwCaCertificateEdit")
        self.bw_ca_certificate_edit.setPlaceholderText(
            "Optional additional PEM CA certificate"
        )
        self.bw_ca_certificate_edit.setToolTip(
            "Optional CA certificate passed to Node.js through "
            "NODE_EXTRA_CA_CERTS. It is added alongside the system CA store."
        )
        self.browse_bw_ca_button = QPushButton("Browse…")
        self.browse_bw_ca_button.setObjectName("browseBwCaCertificateButton")
        bw_ca_row = QHBoxLayout()
        bw_ca_row.addWidget(self.bw_ca_certificate_edit, 1)
        bw_ca_row.addWidget(self.browse_bw_ca_button)
        vault_form.addRow("Email", self.email_edit)
        vault_form.addRow("Master password", self.password_edit)
        vault_form.addRow("Bitwarden CLI", self.bw_path_edit)
        vault_form.addRow(self.bw_system_ca_check)
        vault_form.addRow("Additional CA certificate", bw_ca_row)
        layout.addWidget(vault_box)

        fill_box = QGroupBox("Target and fill sequence")
        fill_form = QFormLayout(fill_box)
        self.app_id_edit = QLineEdit()
        self.app_id_edit.setObjectName("appIdEdit")
        self.app_id_edit.setPlaceholderText(
            "e.g. steam or pcprocess://steam (Wayland: enter explicitly)"
        )
        self.active_app_command_edit = QLineEdit()
        self.active_app_command_edit.setObjectName("activeAppCommandEdit")
        self.active_app_command_edit.setPlaceholderText(
            "Optional shell command that prints the active window PID"
        )
        self.active_app_command_edit.setToolTip(
            "Custom detector for unsupported desktops. When set, the command is "
            "tried first and must print only the active window PID; its process "
            "name becomes the app ID. It runs through your shell, so only enter "
            "commands you trust and do not include credentials."
        )
        self.allow_unverified_target_check = QCheckBox(
            "Allow fill if active app cannot be verified"
        )
        self.allow_unverified_target_check.setObjectName("allowUnverifiedTargetCheck")
        self.allow_unverified_target_check.setToolTip(
            "Bypasses the focus check only when active-app detection is unavailable. "
            "Credentials will be sent to whichever window has focus."
        )
        self.actions_edit = QLineEdit("C14724635")
        self.actions_edit.setObjectName("fillActionsEdit")
        self.actions_edit.setToolTip(
            "1=username, 2=password, 3=current TOTP, 4=type, 5=copy, "
            "6=Enter, 7=Tab, A/B=next/previous, C/D=first/last login"
        )
        self.prefer_uri_profile_check = QCheckBox(
            "Use account URI actions when available"
        )
        self.prefer_uri_profile_check.setObjectName("preferUriProfileCheck")
        self.prefer_uri_profile_check.setChecked(True)
        self.delay_spin = QSpinBox()
        self.delay_spin.setObjectName("focusDelaySpin")
        self.delay_spin.setRange(0, 15)
        self.delay_spin.setValue(3)
        self.delay_spin.setSuffix(" s")
        app_buttons = QHBoxLayout()
        self.detect_app_button = QPushButton("Detect active app")
        self.detect_app_button.setObjectName("detectAppButton")
        self.refresh_accounts_button = QPushButton("Load accounts")
        self.refresh_accounts_button.setObjectName("loadAccountsButton")
        self.refresh_accounts_button.setEnabled(False)
        app_buttons.addWidget(self.detect_app_button)
        app_buttons.addWidget(self.refresh_accounts_button)
        app_buttons.addStretch(1)
        fill_form.addRow("Application ID", self.app_id_edit)
        fill_form.addRow(app_buttons)
        fill_form.addRow("Active-app PID command", self.active_app_command_edit)
        fill_form.addRow(self.allow_unverified_target_check)
        fill_form.addRow("Actions", self.actions_edit)
        fill_form.addRow("Profile", self.prefer_uri_profile_check)
        fill_form.addRow("Focus delay", self.delay_spin)

        self.generated_uri_edit = QLineEdit()
        self.generated_uri_edit.setObjectName("generatedUriEdit")
        self.generated_uri_edit.setReadOnly(True)
        self.generated_uri_edit.setPlaceholderText("Generated mapping URI appears here")
        uri_buttons = QHBoxLayout()
        self.generate_uri_button = QPushButton("Generate mapping URI")
        self.generate_uri_button.setObjectName("generateUriButton")
        self.copy_uri_button = QPushButton("Copy URI")
        self.copy_uri_button.setObjectName("copyUriButton")
        self.copy_uri_button.setEnabled(False)
        uri_buttons.addWidget(self.generate_uri_button)
        uri_buttons.addWidget(self.copy_uri_button)
        uri_buttons.addStretch(1)
        fill_form.addRow("Bitwarden URI", self.generated_uri_edit)
        fill_form.addRow(uri_buttons)
        layout.addWidget(fill_box)

        accounts_box = QGroupBox("Accounts mapped to this application")
        accounts_layout = QVBoxLayout(accounts_box)
        self.accounts_status_label = QLabel(
            "Connect to the vault and load accounts for an application."
        )
        self.accounts_status_label.setObjectName("accountsStatusLabel")
        accounts_layout.addWidget(self.accounts_status_label)
        self.accounts_scroll = QScrollArea()
        self.accounts_scroll.setObjectName("accountsScrollArea")
        self.accounts_scroll.setWidgetResizable(True)
        self.accounts_scroll.setMinimumHeight(120)
        self.accounts_content = QWidget()
        self.accounts_rows_layout = QVBoxLayout(self.accounts_content)
        self.accounts_rows_layout.setContentsMargins(2, 2, 2, 2)
        self.accounts_rows_layout.setSpacing(2)
        self.accounts_scroll.setWidget(self.accounts_content)
        accounts_layout.addWidget(self.accounts_scroll)
        layout.addWidget(accounts_box, 1)

        buttons = QHBoxLayout()
        self.connect_button = QPushButton("Connect to vault")
        self.connect_button.setObjectName("connectButton")
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setObjectName("disconnectButton")
        self.disconnect_button.setEnabled(False)
        self.fill_button = QPushButton("Fill now")
        self.fill_button.setObjectName("fillButton")
        self.fill_button.setEnabled(False)
        self.diagnostics_button = QPushButton("Desktop diagnostics")
        self.diagnostics_button.setObjectName("desktopDiagnosticsButton")
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.disconnect_button)
        buttons.addWidget(self.diagnostics_button)
        buttons.addStretch(1)
        buttons.addWidget(self.fill_button)
        layout.addLayout(buttons)

        self.status_label = QLabel("Ready. Your master password is never saved.")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(38)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        self.setCentralWidget(central)
        self.connect_button.clicked.connect(self._connect_to_vault)
        self.disconnect_button.clicked.connect(self._disconnect_from_vault)
        self.fill_button.clicked.connect(self._start_fill_countdown)
        self.diagnostics_button.clicked.connect(self._run_diagnostics)
        self.detect_app_button.clicked.connect(self._start_app_detection)
        self.refresh_accounts_button.clicked.connect(self._load_accounts)
        self.app_id_edit.returnPressed.connect(self._load_accounts)
        self.generate_uri_button.clicked.connect(self._generate_uri)
        self.copy_uri_button.clicked.connect(self._copy_generated_uri)
        self.browse_bw_ca_button.clicked.connect(self._browse_bw_ca_certificate)

    def _restore_settings(self) -> None:
        self.email_edit.setText(str(self._settings.value("email", "")))
        self.app_id_edit.setText(str(self._settings.value("app_id", "")))
        self.active_app_command_edit.setText(
            str(self._settings.value("active_app_command", ""))
        )
        self.bw_ca_certificate_edit.setText(
            str(self._settings.value("bw_ca_certificate", ""))
        )
        use_system_ca = self._settings.value("bw_system_ca", True)
        if isinstance(use_system_ca, bool):
            self.bw_system_ca_check.setChecked(use_system_ca)
        else:
            self.bw_system_ca_check.setChecked(
                str(use_system_ca).casefold() not in {"0", "false", "no"}
            )
        self.actions_edit.setText(str(self._settings.value("actions", "C14724635")))
        self.bw_path_edit.setText(str(self._settings.value("bw_path", "bw")))
        prefer_profile = self._settings.value("prefer_uri_profile", True)
        if isinstance(prefer_profile, bool):
            self.prefer_uri_profile_check.setChecked(prefer_profile)
        else:
            self.prefer_uri_profile_check.setChecked(
                str(prefer_profile).casefold() not in {"0", "false", "no"}
            )

    def _browse_bw_ca_certificate(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose additional CA certificate",
            self.bw_ca_certificate_edit.text(),
            "Certificate files (*.pem *.crt *.cer);;All files (*)",
        )
        if path:
            self.bw_ca_certificate_edit.setText(path)

    def _connect_to_vault(self) -> None:
        email = self.email_edit.text().strip() or None
        password = self.password_edit.text() or None
        cli_path = self.bw_path_edit.text().strip() or "bw"
        use_system_ca = self.bw_system_ca_check.isChecked()
        ca_certificate = self.bw_ca_certificate_edit.text().strip() or None
        self.password_edit.clear()
        self.status_label.setText("Checking Bitwarden vault status…")
        self._set_busy(True)

        def connect() -> VaultService:
            cli = self._cli_factory(
                cli_path,
                use_system_ca=use_system_ca,
                ca_certificate=ca_certificate,
            )
            return authenticate_vault(
                cli,
                email=email,
                password=password,
                prompt_email=lambda _: "",
                password_prompt=lambda _: "",
            )

        self._start_worker(connect, self._connected)

    def _connected(self, service: VaultService) -> None:
        if self._service is not None:
            self._service.close()
        self._service = service
        self.status_label.setText("Connected. Detect or enter the target app ID.")
        self._set_busy(False)
        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.finished.connect(self._select_target_after_connection)
        else:
            self._select_target_after_connection()

    def _select_target_after_connection(self) -> None:
        if self._service is None:
            return
        if self.app_id_edit.text().strip():
            self._load_accounts()
        else:
            self._start_app_detection()

    def _run_diagnostics(self) -> None:
        clipboard_available = QGuiApplication.clipboard() is not None
        command = self.active_app_command_edit.text().strip() or None
        self.status_label.setText(
            "Checking desktop integrations without sending input…"
        )
        self._set_busy(True)
        self._start_worker(
            lambda: format_diagnostics(
                collect_diagnostics(
                    active_app_command=command,
                    gui_clipboard_available=clipboard_available,
                )
            ),
            self._diagnostics_completed,
        )

    def _diagnostics_completed(self, report: str) -> None:
        self.status_label.setText("Desktop diagnostics complete; no input was sent.")
        self._set_busy(False)
        QMessageBox.information(self, "Desktop diagnostics", report)

    def _start_app_detection(self) -> None:
        if self._busy:
            return
        self._pending_app_detection = True
        self._countdown = max(APP_DETECTION_MINIMUM_SECONDS, self.delay_spin.value())
        self._set_busy(True)
        self.status_label.setText(
            "Switch to the target application; detecting it in "
            f"{self._countdown} seconds…"
        )
        self._countdown_timer.start()

    def _detect_current_app_now(self) -> None:
        self.status_label.setText("Detecting the active application…")
        self._set_busy(True)
        command = self.active_app_command_edit.text().strip() or None
        self._start_worker(
            lambda: resolve_app_id(active_app_command=command),
            self._active_app_detected,
        )

    def _active_app_detected(self, app_id: str) -> None:
        self.app_id_edit.setText(app_id)
        if self._service is not None:
            self.status_label.setText("Detected app ID. Loading mapped accounts…")
        else:
            self.status_label.setText("Detected app ID.")
        thread = self._thread
        service = self._service
        self._set_busy(False)
        if service is None:
            return
        if thread is not None and thread.isRunning():
            thread.finished.connect(self._load_accounts)
        else:
            self._load_accounts()

    def _load_accounts(self) -> None:
        service = self._service
        if service is None:
            self.status_label.setText("Connect to the vault before loading accounts.")
            return
        try:
            app_id = self._current_app_id()
        except (RuntimeError, ValueError) as error:
            self.status_label.setText(str(error))
            return

        self.accounts_status_label.setText("Loading mapped accounts…")
        self.status_label.setText("Checking Bitwarden mappings…")
        self._set_busy(True)
        self._start_worker(
            lambda: tuple(service.list_matches(app_id)),
            lambda matches: self._accounts_loaded(app_id, matches),
        )

    def _accounts_loaded(self, app_id: str, matches: Sequence[LoginSummary]) -> None:
        self._matches = tuple(matches)
        self._loaded_app_id = app_id
        self._clear_account_rows()
        for summary in self._matches:
            row = AccountRow(summary, self.accounts_content)
            row.action_requested.connect(self._account_action_requested)
            self._account_rows[summary.id] = row
            self.accounts_rows_layout.addWidget(row)
        self.accounts_rows_layout.addStretch(1)
        self.accounts_status_label.setText(
            f"{len(self._matches)} account(s) mapped to {app_id}. "
            "Choose an action on an account."
            if self._matches
            else f"No accounts are mapped to {app_id}."
        )
        self.status_label.setText("Mapped accounts refreshed.")
        self._set_busy(False)

    def _clear_account_rows(self) -> None:
        while self.accounts_rows_layout.count():
            item = self.accounts_rows_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._account_rows.clear()

    def _generate_uri(self) -> None:
        try:
            app_id = self._current_app_id()
            actions = parse_action_sequence(self.actions_edit.text())
            uri = build_app_uri(app_id, actions)
        except (RuntimeError, ValueError) as error:
            self.status_label.setText(str(error))
            return
        self.generated_uri_edit.setText(uri)
        self.copy_uri_button.setEnabled(True)
        self.status_label.setText("Generated a Bitwarden application mapping URI.")

    def _copy_generated_uri(self) -> None:
        uri = self.generated_uri_edit.text()
        if uri:
            self.clipboard_requested.emit(uri)
            self.status_label.setText("Copied the mapping URI to the clipboard.")

    def _disconnect_from_vault(self) -> None:
        if self._service is not None:
            self._service.close()
            self._service = None
        self._matches = ()
        self._loaded_app_id = None
        self._clear_account_rows()
        self.accounts_status_label.setText("Connect to the vault to load accounts.")
        self.status_label.setText("Disconnected. No vault session is active.")
        self._refresh_buttons()

    def _start_fill_countdown(self) -> None:
        if self._service is None:
            self.status_label.setText("Connect to the vault first.")
            return
        try:
            app_id = self._current_app_id()
        except (ValueError, RuntimeError) as error:
            self.status_label.setText(str(error))
            return

        if self._loaded_app_id != app_id:
            self.status_label.setText("Load the mapped accounts before filling.")
            self._load_accounts()
            return
        if not self._matches:
            self.status_label.setText("No Bitwarden login is mapped to this app ID.")
            return

        first_match = self._matches[0]
        try:
            profile_actions = (
                profile_actions_for_uris(first_match.uris, app_id)
                if self.prefer_uri_profile_check.isChecked()
                else None
            )
        except ValueError as error:
            self.status_label.setText(str(error))
            return
        if profile_actions is not None:
            self._queue_fill(first_match.id, profile_actions, app_id)
            return
        actions_text = self.actions_edit.text().strip()
        try:
            actions = (
                parse_action_sequence(actions_text) if actions_text else DEFAULT_ACTIONS
            )
        except ValueError as error:
            self.status_label.setText(str(error))
            return
        self._queue_fill(None, actions, app_id)

    def _actions_for_account(
        self, summary: LoginSummary, app_id: str
    ) -> tuple[Action, ...]:
        if self.prefer_uri_profile_check.isChecked():
            profile_actions = profile_actions_for_uris(summary.uris, app_id)
            if profile_actions is not None:
                return profile_actions
        actions_text = self.actions_edit.text().strip()
        return parse_action_sequence(actions_text) if actions_text else DEFAULT_ACTIONS

    def _queue_fill(
        self,
        item_id: str | None,
        actions: tuple[Action, ...],
        app_id: str,
    ) -> None:
        self._pending_app_detection = False
        self._pending_fill_item_id = item_id
        self._pending_fill_actions = actions
        self._pending_fill_app_id = app_id
        self._countdown = self.delay_spin.value()
        if not self._countdown:
            self._begin_fill(actions, item_id, app_id)
            return
        self._set_busy(True)
        self.status_label.setText(
            (
                "Warning: unverified filling is enabled. "
                if self.allow_unverified_target_check.isChecked()
                else ""
            )
            + f"Switch to the target app now; filling in {self._countdown} seconds…"
        )
        self._countdown_timer.start()

    def _countdown_tick(self) -> None:
        self._countdown -= 1
        if self._countdown <= 0:
            self._countdown_timer.stop()
            if self._pending_app_detection:
                self._pending_app_detection = False
                self._set_busy(False)
                self._detect_current_app_now()
                return
            actions = self._pending_fill_actions
            app_id = self._pending_fill_app_id
            item_id = self._pending_fill_item_id
            if actions is None or app_id is None:
                self._set_busy(False)
                return
            self._begin_fill(actions, item_id, app_id)
        elif self._pending_app_detection:
            self.status_label.setText(
                "Switch to the target application; detecting it in "
                f"{self._countdown} seconds…"
            )
        else:
            self.status_label.setText(
                (
                    "Warning: unverified filling is enabled. "
                    if self.allow_unverified_target_check.isChecked()
                    else ""
                )
                + f"Switch to the target app now; filling in {self._countdown} seconds…"
            )

    def _begin_fill(
        self,
        actions: Sequence[Action],
        item_id: str | None,
        expected_app_id: str,
    ) -> None:
        service = self._service
        if service is None:
            self.status_label.setText("Vault disconnected before filling could start.")
            self._set_busy(False)
            return
        try:
            app_id = self._current_app_id()
        except (RuntimeError, ValueError) as error:
            self.status_label.setText(str(error))
            self._set_busy(False)
            return
        if app_id != expected_app_id:
            self.status_label.setText(
                "The target app ID changed; refresh accounts first."
            )
            self._set_busy(False)
            return

        self.status_label.setText("Matching vault items and preparing desktop input…")
        self._set_busy(True)
        self._pending_fill_item_id = None
        self._pending_fill_actions = None
        self._pending_fill_app_id = None
        verifier = ActiveApplicationVerifier(
            app_id,
            active_app_command=self.active_app_command_edit.text().strip() or None,
            allow_unverified=self.allow_unverified_target_check.isChecked(),
        )

        def fill() -> _FillOutcome:
            adapter = LazyInputAdapter(
                lambda: create_input_adapter(
                    clipboard_copy=self._copy_to_clipboard_from_worker,
                    clipboard_cleanup=self._clear_input_clipboard_from_worker,
                )
            )
            try:
                if item_id is not None:
                    result = fill_selected_login(
                        service,
                        app_id,
                        item_id,
                        actions,
                        adapter,
                        before_input=verifier.verify,
                    )
                else:
                    result = fill_for_app(
                        service,
                        app_id,
                        actions,
                        adapter,
                        before_input=verifier.verify,
                    )
                return _FillOutcome(result, verifier.unverified)
            finally:
                close = getattr(adapter, "close", None)
                if callable(close):
                    close()

        self._start_worker(fill, self._fill_completed)

    def _current_app_id(self) -> str:
        value = self.app_id_edit.text().strip()
        if not value:
            raise ValueError("Enter the target application's app ID first.")
        return resolve_app_id(value)

    def _account_action_requested(self, item_id: str, action: str) -> None:
        service = self._service
        if service is None:
            self.status_label.setText("Connect to the vault before using an account.")
            return
        try:
            app_id = self._current_app_id()
        except (RuntimeError, ValueError) as error:
            self.status_label.setText(str(error))
            return
        if app_id != self._loaded_app_id:
            self.status_label.setText("Load accounts for the selected app ID first.")
            return
        summary = next((entry for entry in self._matches if entry.id == item_id), None)
        if summary is None:
            self.status_label.setText(
                "That account is no longer in the current mapping."
            )
            return
        if action == "autofill":
            try:
                actions = self._actions_for_account(summary, app_id)
            except ValueError as error:
                self.status_label.setText(str(error))
                return
            self._queue_fill(item_id, actions, app_id)
            return

        if action not in {"copy_username", "copy_password", "copy_totp"}:
            self.status_label.setText("Unknown account action.")
            return
        self.status_label.setText("Retrieving the requested account value…")
        self._set_busy(True)
        self._start_worker(
            lambda: self._copy_account_value(service, app_id, item_id, action),
            self._copy_completed,
        )

    def _copy_account_value(
        self, service: FillService, app_id: str, item_id: str, action: str
    ) -> str:
        if action == "copy_username":
            summary = next(
                (
                    entry
                    for entry in service.list_matches(app_id)
                    if entry.id == item_id
                ),
                None,
            )
            value = summary.username if summary is not None else None
        elif action == "copy_password":
            value = service.get_login(app_id, item_id).password
        else:
            value = service.get_totp(app_id, item_id)
        if not value:
            field_name = action.removeprefix("copy_")
            raise ValueError(f"The selected login has no {field_name} value.")
        return value

    def _copy_completed(self, value: str) -> None:
        self.clipboard_requested.emit(value)
        self.status_label.setText(
            "Copied the requested account value to the clipboard."
        )
        self._set_busy(False)

    def _fill_completed(self, outcome: _FillOutcome) -> None:
        result = outcome.result
        if result.matched_items == 0:
            message = (
                "No login is mapped to this app ID. Add a matching "
                "pcprocess:// URI in Bitwarden."
            )
        else:
            message = (
                f"Done: {result.selected_items} login action group(s), "
                f"{result.input_operations} input operation(s)."
            )
        if outcome.active_app_unverified:
            message = f"Warning: active application could not be verified; {message}"
        self.status_label.setText(message)
        self.allow_unverified_target_check.setChecked(False)
        self._set_busy(False)

    def _start_worker(
        self, operation: Callable[[], Any], on_complete: Callable[[Any], None]
    ) -> None:
        thread = QThread(self)
        worker = _OperationWorker(operation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(on_complete)
        worker.failed.connect(self._operation_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._thread_finished(thread))
        self._thread = thread
        self._worker = worker
        thread.start()

    def _operation_failed(self, message: str) -> None:
        self.status_label.setText(message)
        self.allow_unverified_target_check.setChecked(False)
        self._set_busy(False)

    def _thread_finished(self, thread: QThread) -> None:
        if self._thread is thread:
            self._thread = None
            self._worker = None
            self._refresh_buttons()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        busy = self._busy or (self._thread is not None and self._thread.isRunning())
        self.connect_button.setEnabled(not busy)
        self.disconnect_button.setEnabled(not busy and self._service is not None)
        self.fill_button.setEnabled(not busy and self._service is not None)
        self.diagnostics_button.setEnabled(not busy)
        self.app_id_edit.setEnabled(not busy)
        self.active_app_command_edit.setEnabled(not busy)
        self.bw_system_ca_check.setEnabled(not busy)
        self.bw_ca_certificate_edit.setEnabled(not busy)
        self.browse_bw_ca_button.setEnabled(not busy)
        self.allow_unverified_target_check.setEnabled(not busy)
        self.actions_edit.setEnabled(not busy)
        self.delay_spin.setEnabled(not busy)
        self.prefer_uri_profile_check.setEnabled(not busy)
        self.detect_app_button.setEnabled(not busy)
        self.refresh_accounts_button.setEnabled(not busy and self._service is not None)
        for row in self._account_rows.values():
            row.setEnabled(not busy)

    @Slot(str)
    def _copy_to_clipboard(self, text: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    def _copy_to_clipboard_from_worker(self, text: str) -> None:
        """Set clipboard text on Qt's GUI thread before sending Ctrl+V."""
        completed: Future[None] = Future()
        self._input_clipboard_requested.emit(text, completed)
        try:
            completed.result(timeout=5.0)
        except Exception as error:
            raise InputBackendError(
                "Could not set text on the desktop clipboard"
            ) from error

    def _clear_input_clipboard_from_worker(self, text: str) -> None:
        """Clear temporary paste text on Qt's thread if it is still ours."""
        completed: Future[None] = Future()
        self._input_clipboard_cleanup_requested.emit(text, completed)
        try:
            completed.result(timeout=5.0)
        except Exception as error:
            raise InputBackendError(
                "Could not safely clear temporary clipboard text"
            ) from error

    @Slot(str, object)
    def _set_input_clipboard(self, text: str, completed: object) -> None:
        if not isinstance(completed, Future):
            return
        try:
            clipboard = QGuiApplication.clipboard()
            if clipboard is None:
                raise InputBackendError("The desktop clipboard is unavailable")
            token = uuid4().hex
            mime_data = QMimeData()
            mime_data.setText(text)
            mime_data.setData(_TEMPORARY_CLIPBOARD_MARKER, token.encode("ascii"))
            clipboard.setMimeData(mime_data)
            self._temporary_clipboard_text = text
            self._temporary_clipboard_token = token
        except Exception as error:
            completed.set_exception(error)
        else:
            completed.set_result(None)

    @Slot(str, object)
    def _clear_input_clipboard(self, text: str, completed: object) -> None:
        if not isinstance(completed, Future):
            return
        token = self._temporary_clipboard_token
        temporary_text = self._temporary_clipboard_text
        try:
            clipboard = QGuiApplication.clipboard()
            if clipboard is None:
                raise InputBackendError("The desktop clipboard is unavailable")
            mime_data = clipboard.mimeData()
            if (
                token is not None
                and temporary_text == text
                and mime_data is not None
                and mime_data.hasFormat(_TEMPORARY_CLIPBOARD_MARKER)
                and mime_data.data(_TEMPORARY_CLIPBOARD_MARKER)
                == QByteArray(token.encode("ascii"))
                and mime_data.text() == text
            ):
                clipboard.clear()
        except Exception as error:
            completed.set_exception(error)
        else:
            completed.set_result(None)
        finally:
            if self._temporary_clipboard_token == token:
                self._temporary_clipboard_token = None
                self._temporary_clipboard_text = None

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.status_label.setText("Please wait for the active operation to finish.")
            event.ignore()
            return
        self._countdown_timer.stop()
        if self._service is not None:
            self._service.close()
            self._service = None
        self._settings.setValue("email", self.email_edit.text())
        self._settings.setValue("app_id", self.app_id_edit.text())
        self._settings.setValue(
            "active_app_command", self.active_app_command_edit.text()
        )
        self._settings.setValue("actions", self.actions_edit.text())
        self._settings.setValue(
            "prefer_uri_profile", self.prefer_uri_profile_check.isChecked()
        )
        self._settings.setValue("bw_path", self.bw_path_edit.text())
        self._settings.setValue("bw_system_ca", self.bw_system_ca_check.isChecked())
        self._settings.setValue("bw_ca_certificate", self.bw_ca_certificate_edit.text())
        self._settings.sync()
        event.accept()


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    arguments = list(sys.argv if argv is None else [sys.argv[0], *argv])
    app = QApplication(arguments)
    app.setApplicationName("Bitwarden Autofiller")
    window = BitwardenAutofillerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
