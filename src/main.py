"""Entry point."""
from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from .core.paths import assets_dir
from .ui.main_window import MainWindow


def _load_theme() -> str:
    qss_path = assets_dir() / "theme.qss"
    if qss_path.exists():
        try:
            return qss_path.read_text(encoding="utf-8")
        except Exception:
            pass
    return ""


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("MiniRecorder")
    app.setQuitOnLastWindowClosed(False)  # keep tray alive

    icon_path = assets_dir() / "icons" / "app.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    qss = _load_theme()
    w = MainWindow(theme_qss=qss)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
