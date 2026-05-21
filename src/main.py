"""Entry point with single-instance enforcement.

Second launch is detected via a named local socket; the running instance is
told to bring itself to the front and the second launcher exits.
"""
from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtCore import QByteArray
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .core.paths import assets_dir
from .ui.main_window import MainWindow


SINGLETON_KEY = "QingLuRecorder_SingletonServer_v1"


def _signal_existing_instance() -> bool:
    """Try to find a running instance and tell it to show. Returns True if found."""
    sock = QLocalSocket()
    sock.connectToServer(SINGLETON_KEY)
    if sock.waitForConnected(300):
        sock.write(QByteArray(b"show"))
        sock.flush()
        sock.waitForBytesWritten(200)
        sock.disconnectFromServer()
        return True
    return False


def _load_theme() -> str:
    qss_path = assets_dir() / "theme.qss"
    if qss_path.exists():
        try:
            return qss_path.read_text(encoding="utf-8")
        except Exception:
            pass
    return ""


def main() -> int:
    # Fast-path: if another instance is already running, wake it and exit.
    # QApplication doesn't have to exist for QLocalSocket.connectToServer.
    app_for_probe = QApplication.instance() or QApplication(sys.argv)
    if _signal_existing_instance():
        return 0
    # Reuse the probe QApplication as our real one.
    app = app_for_probe
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app.setApplicationName("轻录")
    app.setQuitOnLastWindowClosed(False)  # keep tray alive

    icon_path = assets_dir() / "icons" / "app.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    qss = _load_theme()
    w = MainWindow(theme_qss=qss)
    w.show()

    # Listen for future "show" requests from other launches.
    # removeServer() clears any stale endpoint left by a crashed previous run.
    QLocalServer.removeServer(SINGLETON_KEY)
    server = QLocalServer()
    server.listen(SINGLETON_KEY)

    def _on_new_connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        sock.readyRead.connect(lambda: (sock.readAll(), w._show_from_tray()))
        # Best-effort: also handle data already buffered
        if sock.bytesAvailable() > 0:
            sock.readAll()
            w._show_from_tray()

    server.newConnection.connect(_on_new_connection)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
