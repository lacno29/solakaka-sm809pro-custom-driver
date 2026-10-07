#!/usr/bin/env python3
"""
run_app.py -- launch the SM809 Pro desktop app.

    python run_app.py

Single-instance: the app lives in the tray, so launching it again does NOT start
a second copy -- it signals the running instance to show its window and exits.
"""
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from app import theme
from app.main_window import MainWindow, app_icon

_INSTANCE_KEY = "SM809Pro_single_instance"


def _hand_off_if_running() -> bool:
    """If another instance is already running, tell it to show and return True."""
    sock = QLocalSocket()
    sock.connectToServer(_INSTANCE_KEY)
    if sock.waitForConnected(250):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(250)
        sock.disconnectFromServer()
        return True
    return False


def _listen_for_relaunch(win) -> QLocalServer:
    """Become the primary instance: listen so a future launch can raise our
    window instead of starting a new copy."""
    QLocalServer.removeServer(_INSTANCE_KEY)   # clear any stale socket
    server = QLocalServer()
    server.listen(_INSTANCE_KEY)

    def _on_new_connection():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readAll()
            conn.disconnectFromServer()
        # restore from tray + bring to the foreground
        if hasattr(win, "_show_from_tray"):
            win._show_from_tray()
        else:
            win.showNormal()
            win.raise_()
            win.activateWindow()

    server.newConnection.connect(_on_new_connection)
    return server


def main():
    # crisp rendering on high-dpi displays
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("SM809 Pro")
    app.setWindowIcon(app_icon())

    # if we're a second launch, surface the running instance and quit
    if _hand_off_if_running():
        return

    pal = theme.dark_palette()
    if pal is not None:
        app.setPalette(pal)
    app.setStyleSheet(theme.stylesheet())
    win = MainWindow()
    win._single_instance_server = _listen_for_relaunch(win)   # keep a reference
    # --minimized / --tray (used by "Start with Windows"): stay in the tray on
    # launch. Only honoured when a tray exists, else show so it's not unreachable.
    minimized = ("--minimized" in sys.argv or "--tray" in sys.argv)
    if minimized and getattr(win, "tray", None) is not None:
        win.tray.showMessage("SM809 Pro", "Running in the tray.",
                             win.tray.MessageIcon.Information, 2000)
    else:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
