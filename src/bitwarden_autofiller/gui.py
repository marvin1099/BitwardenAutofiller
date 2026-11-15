"""Responsive Qt desktop interface for Bitwarden autofill."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bitwarden_autofiller.actions import Action, parse_action_sequence
from bitwarden_autofiller.app_identity import resolve_app_id
from bitwarden_autofiller.authentication import (
    AuthenticationError,
    authenticate_vault,
)
from bitwarden_autofiller.bitwarden import BitwardenCLI, BitwardenCLIError
from bitwarden_autofiller.platforms import (
    InputBackendError,
    LazyInputAdapter,
    create_input_adapter,
)
from bitwarden_autofiller.service import VaultService
from bitwarden_autofiller.workflow import FillResult, fill_for_app


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
            if isinstance(
                error,
                (AuthenticationError, BitwardenCLIError, InputBackendError, ValueError),
            ):
                message = str(error)
            else:
                message = (
                    "The operation failed; check Bitwarden and desktop permissions."
                )
            self.failed.emit(message)
        else:
            self.completed.emit(result)


class BitwardenAutofillerWindow(QMainWindow):
    """One-window local autofill client; credentials are not stored in settings."""

    clipboard_requested = Signal(str)

    def __init__(
        self,
        *,
        settings: QSettings | None = None,
        cli_factory: Callable[[str | Path], BitwardenCLI] = BitwardenCLI,
    ) -> None:
        super().__init__()
        self._settings = settings or QSettings("BitwardenAutofiller", "DesktopClient")
        self._cli_factory = cli_factory
        self._service: VaultService | None = None
        self._thread: QThread | None = None
        self._worker: _OperationWorker | None = None
        self._busy = False
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._countdown_tick)
        self._countdown = 0

        self.setWindowTitle("Bitwarden Autofiller")
        icon_path = Path(__file__).with_name("fillericon.png")
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(520, 390)
        self.resize(600, 460)
        self.clipboard_requested.connect(self._copy_to_clipboard)
        self._build_ui()
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
            "On Wayland, enter the app ID; the compositor controls input permission."
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
        vault_form.addRow("Email", self.email_edit)
        vault_form.addRow("Master password", self.password_edit)
        vault_form.addRow("Bitwarden CLI", self.bw_path_edit)
        layout.addWidget(vault_box)

        fill_box = QGroupBox("Target and fill sequence")
        fill_form = QFormLayout(fill_box)
        self.app_id_edit = QLineEdit()
        self.app_id_edit.setObjectName("appIdEdit")
        self.app_id_edit.setPlaceholderText("e.g. steam (maps pcprocess://steam)")
        self.actions_edit = QLineEdit("C14724635")
        self.actions_edit.setObjectName("fillActionsEdit")
        self.actions_edit.setToolTip(
            "1=username, 2=password, 3=current TOTP, 4=type, 5=copy, "
            "6=Enter, 7=Tab, A/B=next/previous, C/D=first/last login"
        )
        self.delay_spin = QSpinBox()
        self.delay_spin.setObjectName("focusDelaySpin")
        self.delay_spin.setRange(0, 15)
        self.delay_spin.setValue(3)
        self.delay_spin.setSuffix(" s")
        fill_form.addRow("Application ID", self.app_id_edit)
        fill_form.addRow("Actions", self.actions_edit)
        fill_form.addRow("Focus delay", self.delay_spin)
        layout.addWidget(fill_box)

        buttons = QHBoxLayout()
        self.connect_button = QPushButton("Connect to vault")
        self.connect_button.setObjectName("connectButton")
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setObjectName("disconnectButton")
        self.disconnect_button.setEnabled(False)
        self.fill_button = QPushButton("Fill now")
        self.fill_button.setObjectName("fillButton")
        self.fill_button.setEnabled(False)
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.disconnect_button)
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

    def _restore_settings(self) -> None:
        self.email_edit.setText(str(self._settings.value("email", "")))
        self.app_id_edit.setText(str(self._settings.value("app_id", "")))
        self.actions_edit.setText(str(self._settings.value("actions", "C14724635")))
        self.bw_path_edit.setText(str(self._settings.value("bw_path", "bw")))

    def _connect_to_vault(self) -> None:
        email = self.email_edit.text().strip() or None
        password = self.password_edit.text() or None
        cli_path = self.bw_path_edit.text().strip() or "bw"
        self.password_edit.clear()
        self.status_label.setText("Checking Bitwarden vault status…")
        self._set_busy(True)

        def connect() -> VaultService:
            cli = self._cli_factory(cli_path)
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
        self.status_label.setText("Connected. Enter an app ID and choose Fill now.")
        self.fill_button.setEnabled(True)
        self.disconnect_button.setEnabled(True)
        self._set_busy(False)

    def _disconnect_from_vault(self) -> None:
        if self._service is not None:
            self._service.close()
            self._service = None
        self.fill_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.status_label.setText("Disconnected. No vault session is active.")

    def _start_fill_countdown(self) -> None:
        if self._service is None:
            self.status_label.setText("Connect to the vault first.")
            return
        try:
            self._current_app_id()
            actions = parse_action_sequence(self.actions_edit.text())
        except (ValueError, RuntimeError) as error:
            self.status_label.setText(str(error))
            return

        self._countdown = self.delay_spin.value()
        if not self._countdown:
            self._begin_fill(actions)
            return
        self.fill_button.setEnabled(False)
        self.status_label.setText(
            f"Switch to the target app now; filling in {self._countdown} seconds…"
        )
        self._countdown_timer.start()

    def _countdown_tick(self) -> None:
        self._countdown -= 1
        if self._countdown <= 0:
            self._countdown_timer.stop()
            try:
                actions = parse_action_sequence(self.actions_edit.text())
            except ValueError as error:
                self.status_label.setText(str(error))
                self.fill_button.setEnabled(True)
                return
            self._begin_fill(actions)
        else:
            self.status_label.setText(
                f"Switch to the target app now; filling in {self._countdown} seconds…"
            )

    def _begin_fill(self, actions: Sequence[Action]) -> None:
        service = self._service
        if service is None:
            self.status_label.setText("Vault disconnected before filling could start.")
            self.fill_button.setEnabled(False)
            return
        try:
            app_id = self._current_app_id()
        except (RuntimeError, ValueError) as error:
            self.status_label.setText(str(error))
            self.fill_button.setEnabled(True)
            return

        self.status_label.setText("Matching vault items and preparing desktop input…")
        self._set_busy(True)

        def fill() -> FillResult:
            adapter = LazyInputAdapter(
                lambda: create_input_adapter(
                    clipboard_copy=lambda text: self.clipboard_requested.emit(text)
                )
            )
            try:
                return fill_for_app(service, app_id, actions, adapter)
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

    def _fill_completed(self, result: FillResult) -> None:
        if result.matched_items == 0:
            self.status_label.setText(
                "No login is mapped to this app ID. Add a Bitwarden URI "
                f"pcprocess://{self.app_id_edit.text().strip()}."
            )
        else:
            self.status_label.setText(
                f"Done: {result.selected_items} login action group(s), "
                f"{result.input_operations} input operation(s)."
            )
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

    @Slot(str)
    def _copy_to_clipboard(self, text: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

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
        self._settings.setValue("actions", self.actions_edit.text())
        self._settings.setValue("bw_path", self.bw_path_edit.text())
        self._settings.sync()
        event.accept()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else [sys.argv[0], *argv])
    app = QApplication(arguments)
    app.setApplicationName("Bitwarden Autofiller")
    window = BitwardenAutofillerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
