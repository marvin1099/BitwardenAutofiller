import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLineEdit

from bitwarden_autofiller.desktop.gui import BitwardenAutofillerWindow


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
    with pytest.raises(ValueError, match="app ID"):
        window._current_app_id()
    window.app_id_edit.setText("pcprocess://steam/")
    assert window._current_app_id() == "steam"

    window.email_edit.setText("alice@example.test")
    window.password_edit.setText("do-not-persist-this-password")
    window.close()
    app.processEvents()
    settings.sync()

    assert not settings.contains("password")
    assert "do-not-persist-this-password" not in settings_path.read_text(
        encoding="utf-8"
    )
