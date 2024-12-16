#!/usr/bin/env python

import threading
import clipboard
import time
import sys
import os
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QTabWidget,
    QFileDialog,
    QMessageBox,
    QSpinBox
)
from PySide6.QtCore import (
    Qt,
    QSize,
    QSettings,
    QPoint,
)
from PySide6.QtGui import QIcon

import bitwardenautofiller

class BitwardenAutofillerGUI(QMainWindow):
    def __init__(self):
        self.pass_args(sys.argv[1:]) # bypass the gui on '-cli' argument request

        super().__init__()
        self.dthread = None
        self.setWindowTitle("Bitwarden Autofiller")
        icon = self.resource_path("fillericon.png")
        if os.path.isfile(icon):
            self.setWindowIcon(QIcon(icon))

        # Initialize settings
        self.settings = QSettings('BitwardenAutofiller', 'GUI')

        # Restore window geometry
        self.restore_window_geometry()

        # Minimum size to ensure all elements are visible
        self.setMinimumSize(400, 240)

        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # Create tabs
        self.tab_widget = QTabWidget()
        tab_widget = self.tab_widget
        main_layout.addWidget(tab_widget)

        # Daemon Tab
        daemon_tab = QWidget()
        daemon_layout = QVBoxLayout()
        daemon_tab.setLayout(daemon_layout)

        # Email and Password
        email_layout = QHBoxLayout()
        email_label = QLabel("Bitwarden Email:")
        self.email_input = QLineEdit()
        email_layout.addWidget(email_label)
        email_layout.addWidget(self.email_input)
        daemon_layout.addLayout(email_layout)

        password_layout = QHBoxLayout()
        password_label = QLabel("Vault Password:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        password_layout.addWidget(password_label)
        password_layout.addWidget(self.password_input)
        daemon_layout.addLayout(password_layout)

        # Daemon Timeout Setting
        daemon_settings_layout = QHBoxLayout()
        timeout_label = QLabel("Daemon Timeout (seconds; -1 = infinite):")
        self.timeout_spinbox = QSpinBox()
        self.timeout_spinbox.setRange(-1, 86400)  # infinite to 0 seconds to 1 day
        self.timeout_spinbox.setValue(self.settings.value('daemon_timeout', 3600, type=int))
        daemon_settings_layout.addWidget(timeout_label)
        daemon_settings_layout.addWidget(self.timeout_spinbox)
        daemon_layout.addLayout(daemon_settings_layout)

        # Logout Checkbox
        self.logout_check = QCheckBox("Relogin (helps with sync issues)")
        daemon_layout.addWidget(self.logout_check)

        # Close app but keep daemon
        keep_daemon_layout = QHBoxLayout()
        self.keep_daemon_check = QCheckBox("On GUI exit keep the daemon running in the backround")
        self.keep_daemon_check.setChecked(self.settings.value('keep_daemon_check', False, type=bool))
        keep_daemon_layout.addWidget(self.keep_daemon_check)
        daemon_layout.addLayout(keep_daemon_layout)

        # Run Daemon
        self.daemon_mode = False
        drunner_layout = QHBoxLayout()
        drunner_button = QPushButton("Start Daemon")
        drunner_button.clicked.connect(self.run_daemon)
        drunner_layout.addWidget(drunner_button)
        daemon_layout.addLayout(drunner_layout)

        # Client Tab
        client_tab = QWidget()
        client_layout = QVBoxLayout()
        client_tab.setLayout(client_layout)

        # Sync vault Checkbox
        sync_vault_layout = QHBoxLayout()
        self.sync_vault_check = QCheckBox("Sync Vault")
        sync_vault_layout.addWidget(self.sync_vault_check)
        client_layout.addLayout(sync_vault_layout)

        # Fill Actions
        fill_actions_layout = QHBoxLayout()
        fill_actions_label = QLabel("Fill Actions:")
        self.fill_actions_input = QLineEdit()
        self.fill_actions_input.setText(self.settings.value('fill_actions_input', 'C14724635'))
        fill_actions_layout.addWidget(fill_actions_label)
        fill_actions_layout.addWidget(self.fill_actions_input)
        client_layout.addLayout(fill_actions_layout)

        # IP Network Setting
        ip_network_layout = QHBoxLayout()
        ip_label = QLabel("Local IP:")
        self.ip_input = QLineEdit()
        self.ip_input.setText(self.settings.value('ip_input', '127.0.0.1'))
        ip_network_layout.addWidget(ip_label)
        ip_network_layout.addWidget(self.ip_input)
        client_layout.addLayout(ip_network_layout)

        # Port Network Setting
        port_network_layout = QHBoxLayout()
        port_label = QLabel("Local Port:")
        self.port_input = QLineEdit()
        self.port_input.setText(self.settings.value('port_input', '64756'))
        port_network_layout.addWidget(port_label)
        port_network_layout.addWidget(self.port_input)
        client_layout.addLayout(port_network_layout)

        # Run Client
        self.client_mode = False
        crunner_layout = QHBoxLayout()
        crunner_button = QPushButton("Start Client (waits 3 seconds, focus the target app)")
        crunner_button.clicked.connect(self.run_client)
        crunner_layout.addWidget(crunner_button)
        client_layout.addLayout(crunner_layout)

        # Close Daemon
        self.exit_daemon = False
        close_daemon_button = QPushButton("Send Close Daemon Signal")
        close_daemon_button.clicked.connect(self.close_daemon)
        client_layout.addWidget(close_daemon_button)

        # Other Settings Tab
        connection_tab = QWidget()
        connection_layout = QVBoxLayout()
        connection_tab.setLayout(connection_layout)

        # Salt folder Checkbox
        remote_layout = QHBoxLayout()
        self.salt_folder_check = QCheckBox("Salt folder (Useful for remote PC / daemon)")
        self.salt_folder_check.setChecked(self.settings.value('salt_folder_check', False, type=bool))
        remote_layout.addWidget(self.salt_folder_check)
        connection_layout.addLayout(remote_layout)

        # Server URL
        server_url_layout = QHBoxLayout()
        server_url_label = QLabel("Bitwarden Server URL:")
        self.server_url_input = QLineEdit()
        server_url_layout.addWidget(server_url_label)
        server_url_layout.addWidget(self.server_url_input)
        connection_layout.addLayout(server_url_layout)

        # Certificate File
        cert_file_layout = QHBoxLayout()
        cert_file_label = QLabel("Certificate File:")
        self.cert_file_input = QLineEdit()
        self.cert_file_input.setText(self.settings.value('cert_file_input', ''))
        cert_file_browse = QPushButton("Browse")
        cert_file_browse.clicked.connect(self.browse_cert_file)
        cert_file_layout.addWidget(cert_file_label)
        cert_file_layout.addWidget(self.cert_file_input)
        cert_file_layout.addWidget(cert_file_browse)
        connection_layout.addLayout(cert_file_layout)

        # Additional Encryption
        encryption_layout = QHBoxLayout()
        encryption_label = QLabel("Additional Encryption Password:")
        self.encryption_input = QLineEdit()
        self.encryption_input.setEchoMode(QLineEdit.Password)
        encryption_layout.addWidget(encryption_label)
        encryption_layout.addWidget(self.encryption_input)
        connection_layout.addLayout(encryption_layout)

        # Bitwarden CLI Path
        cli_path_layout = QHBoxLayout()
        cli_path_label = QLabel("Bitwarden CLI Path:")
        self.cli_path_input = QLineEdit()
        self.cli_path_input.setText(self.settings.value('cli_path_input', 'bw'))
        cli_path_browse = QPushButton("Browse")
        cli_path_browse.clicked.connect(self.browse_cli_path)
        cli_path_layout.addWidget(cli_path_label)
        cli_path_layout.addWidget(self.cli_path_input)
        cli_path_layout.addWidget(cli_path_browse)
        connection_layout.addLayout(cli_path_layout)

        # Copy command clipboard button
        cmd_clipboard_layout = QHBoxLayout()
        cmd_clipboard_button = QPushButton("Copy client command to clipboard for system shortcuts")
        cmd_clipboard_button.clicked.connect(self.copy_client_cmd)
        cmd_clipboard_layout.addWidget(cmd_clipboard_button)
        connection_layout.addLayout(cmd_clipboard_layout)

        # Add tabs
        tab_widget.addTab(daemon_tab, "Daemon")
        tab_widget.addTab(client_tab, "Client")
        tab_widget.addTab(connection_tab, "Other Settings")

        # Action Button
        # action_layout = QHBoxLayout()
        # exit_button = QPushButton("Exit App")
        # exit_button.clicked.connect(self.close_app)
        # action_layout.addWidget(exit_button)
        # main_layout.addLayout(action_layout)

    def pass_args(self, args):
        if '-cli' in args:
            args.remove('-cli')
            print("The argument '-cli' was passed redirecting to cli and closing after")
            print()
            bitwardenautofiller.main(args)
            sys.exit()

        print("The gui can be skipped and the command be bypassed to the Autofiller")
        print("To do that add the argument '-cli' to the gui app start command")
        print("any other arguments will then be passed to the autofiller and the gui will not run")
        print()

    def restore_window_geometry(self):
        """Restore the window's position and size from saved settings"""
        # Restore window size
        # size = self.settings.value('window_size', QSize(400, 240), type=QSize)
        # self.resize(size)

        # Restore window position
        pos = self.settings.value('window_position', QPoint(), type=QPoint)

        # If there is a previous position is saved, move to it
        if not pos.isNull():
            self.move(pos)

    def closeEvent(self, event):
        """Save settings when the application is closed"""
        if not self.keep_daemon_check.isChecked():
            self.close_daemon(True)

        # Save window geometry
        # self.settings.setValue('window_size', self.size())
        self.settings.setValue('window_position', self.pos())

        # Text inputs
        self.settings.setValue('cert_file_input', self.cert_file_input.text())
        self.settings.setValue('ip_input', self.ip_input.text())
        self.settings.setValue('port_input', self.port_input.text())
        self.settings.setValue('cli_path_input', self.cli_path_input.text())
        self.settings.setValue('fill_actions', self.fill_actions_input.text())

        # Checkboxes
        self.settings.setValue('salt_folder_check', self.salt_folder_check.isChecked())
        self.settings.setValue('keep_daemon_check', self.keep_daemon_check.isChecked())

        # Spinbox
        self.settings.setValue('daemon_timeout', self.timeout_spinbox.value())

        # Ensure settings are saved
        self.settings.sync()
        event.accept()

    def sizeHint(self):
        # Suggest a reasonable default size, but allow OS/window manager to adjust
        return QSize(400, 240)

    def browse_cert_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select Certificate File", filter="Pem Certificate (*.pem)")
        if filename:
            self.cert_file_input.setText(filename)

    def browse_cli_path(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select Bitwarden CLI")
        if filename:
            self.cli_path_input.setText(filename)

    def prepare_arguments(self):
        args = []

        # Enable non-blocking mode as the console is not used for the gui app
        args.append('-n')

        # Enable raise of errors
        args.append('-r')

        # Server URL
        if self.server_url_input.text():
            args.extend(['-s', self.server_url_input.text()])

        # Certificate File
        if self.cert_file_input.text():
            args.extend(['-cf', self.cert_file_input.text()])

        # Logout
        if self.logout_check.isChecked():
            args.append('-l')

        # Credentials
        if self.email_input.text():
            args.extend(['-m', self.email_input.text()])
        if self.password_input.text():
            args.extend(['-p', self.password_input.text()])

        # Additional Encryption
        if self.encryption_input.text():
            args.extend(['-e', self.encryption_input.text()])

        # Mode Selection
        if self.daemon_mode:
            self.daemon_mode = False
            args.append('-d')
        if self.client_mode:
            self.client_mode = False
            args.append('-c')

        # Bitwarden CLI Path
        if self.cli_path_input.text() != 'bw':
            args.extend(['-bw', self.cli_path_input.text()])

        # Daemon Timeout
        if self.timeout_spinbox.value() != 3600:
            args.extend(['-t', str(self.timeout_spinbox.value())])

        # Salt Folder
        if self.salt_folder_check.isChecked():
            args.append('-sf')

        # Local IP and Port
        if self.ip_input.text() != '127.0.0.1':
            args.extend(['-ip', self.ip_input.text()])
        if self.port_input.text() != '64756':
            args.extend(['-lp', self.port_input.text()])

        # Fill Actions
        if self.fill_actions_input.text() != 'C14724635':
            args.extend(['-f', self.fill_actions_input.text()])

        if self.exit_daemon:
            self.exit_daemon = False
            if not self.client_mode:
                args.append('-c')
            args.append('-x')

        return args

    def resource_path(self, relative_path):
        """Get absolute path to resource, works for dev and PyInstaller"""
        if hasattr(sys, '_MEIPASS'):  # Running as a PyInstaller bundle
            return os.path.join(sys._MEIPASS, relative_path)
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

    def run_bitwarden_autofiller(self,ierr=False):
        daemon_mode = self.daemon_mode
        try:
            args = self.prepare_arguments()
            ret = bitwardenautofiller.main(args)
            if daemon_mode and not ierr:
                QMessageBox.information(self, "Success", "The BitwardenAutofiller daemon was successfully started in the backround!")
                self.tab_widget.setCurrentIndex(1)
            elif not ierr:
                if not ret:
                    QMessageBox.information(self, "Success", "The BitwardenAutofiller client successfully retived and filled the vault data!")
                else:
                    QMessageBox.information(self, "Success", f"The BitwardenAutofiller client successfully ran but returned:\n{ret}")
        except Exception as e:
            if not ierr:
                QMessageBox.critical(self, "Error", f"An error occurred:\n{str(e)}")
            if not daemon_mode:
                if self.tab_widget.currentIndex() == 1:
                    self.tab_widget.setCurrentIndex(0)

    def run_daemon(self):
        self.daemon_mode = True
        self.run_bitwarden_autofiller()

    def close_daemon(self,ierr=False):
        self.client_mode = True
        self.exit_daemon = True
        self.run_bitwarden_autofiller(ierr)

    def run_client(self):
        time.sleep(3)
        self.client_mode = True
        self.run_bitwarden_autofiller()

    def copy_client_cmd(self):
        self.client_mode = True
        if getattr(sys, 'frozen', False):  # Check if running as a compiled executable
            script_path = os.path.abspath(sys.executable)
        else:  # Running as a regular Python script
            script_path = os.path.abspath(__file__)
        args = [script_path + '-cli'] + self.prepare_arguments()
        copyargs = "'" + "' '".join(args) + "'"
        clipboard.copy(copyargs)
        QMessageBox.information(self, "Success", f"The BitwardenAutofiller client command was successfully copied into the clipboard\nYou can now add this command to a hotkey progam")

def main():
    app = QApplication(sys.argv)
    gui = BitwardenAutofillerGUI()
    gui.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()

