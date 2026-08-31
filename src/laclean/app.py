"""Application bootstrap."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PyQt5.QtCore import QCoreApplication, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

from laclean.ui.main_window import MainWindow
from laclean.ui.theme import DARK_STYLESHEET
from laclean.logging_config import configure_logging, install_exception_hook


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Create and configure the single Qt application instance."""

    configure_logging()
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication.instance()
    if app is None:
        app = QApplication(list(argv) if argv is not None else sys.argv)

    app.setApplicationName("Laclean Studio")
    app.setOrganizationName("Laclean")
    app.setApplicationVersion("0.1.0")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(DARK_STYLESHEET)
    return app


def main(argv: Sequence[str] | None = None) -> int:
    app = create_application(argv)
    window = MainWindow()
    install_exception_hook(lambda: window)
    window.show()
    return app.exec_()
