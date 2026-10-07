"""
app.controller -- DeviceController: owns the SM809Pro session off the UI thread.

The GUI must never block on HID I/O (a SetFeature + 60ms settle would freeze the
UI). So all device calls run on a dedicated worker thread via a queue, and
results/events come back as Qt signals. The persistent session + keep-alive
(the wedge fix) live here too, plus the StatusListener for live DPI reflection.

Usage from the UI:
    ctrl = DeviceController()
    ctrl.connected.connect(on_connected)
    ctrl.dpi_level_changed.connect(on_dpi_push)   # live status push
    ctrl.command_done.connect(on_done)
    ctrl.start()                 # opens device + threads
    ctrl.call("set_dpi", [800, 1600, 3200])   # queue a device call by method name
"""

import queue
import threading

from PySide6.QtCore import QObject, Signal

from sm809pro import SM809Pro
from sm809pro.status import StatusListener


class DeviceController(QObject):
    # lifecycle
    connected = Signal(dict)        # {connection, product} on success
    disconnected = Signal()
    error = Signal(str)
    # live device push (from status interface)
    dpi_level_changed = Signal(int)     # current DPI stage index changed
    rate_changed = Signal(int)          # current polling rate (Hz) from the push
    battery_changed = Signal(int)       # battery percent
    charging_changed = Signal(bool)     # charging state (if reported)
    alive_changed = Signal(bool)        # True=mouse awake, False=offline (dongle in, mouse off)
    runapp_pressed = Signal(int)        # a Run-APP button was pressed (report-04 byte[7] code)
    # a queued command finished: (method_name, ok)
    command_done = Signal(str, bool)
    busy_changed = Signal(bool)         # True while a queued command is running

    def __init__(self, keepalive_interval=8.0, parent=None):
        super().__init__(parent)
        self._dev = SM809Pro()
        self._status = None
        self._q = queue.Queue()
        self._worker = None
        self._keepalive = None
        self._stop = threading.Event()
        self._keepalive_interval = keepalive_interval

    # -- public API -----------------------------------------------------------
    def start(self):
        """Open the device and spin up worker + keep-alive + status threads."""
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def call(self, method: str, *args, **kwargs):
        """Queue a device method call by name; result via command_done signal."""
        self._q.put((method, args, kwargs))

    def shutdown(self):
        self._stop.set()
        self._q.put(None)  # unblock worker
        if self._status:
            self._status.stop()

    # -- worker thread --------------------------------------------------------
    def _run(self):
        try:
            ok = self._dev.open()
        except Exception as e:
            self.error.emit(f"open failed: {e}")
            return
        if not ok:
            msg = getattr(self._dev, "last_error", None) or \
                "Device not found. Plug it in and close the official software."
            self.error.emit(msg)
            return

        info = {"connection": self._dev.connection,
                "product": (self._dev.interface_info or {}).get("product_string", "SM809 Pro")}
        self.connected.emit(info)

        # keep-alive thread (mimics the official 10s timer; we use 8s)
        self._keepalive = threading.Thread(target=self._keepalive_loop, daemon=True)
        self._keepalive.start()

        # status listener -> live DPI / battery / liveness
        self._status = StatusListener(
            on_change=self._on_status_push,
            on_battery=lambda pct: self.battery_changed.emit(pct),
            on_alive=lambda alive: self.alive_changed.emit(alive),
            on_charging=lambda ch: self.charging_changed.emit(ch),
            on_runapp=lambda code: self.runapp_pressed.emit(code),
            pid=self._dev.pid,
        )
        self._status.start()

        # process queued commands
        while not self._stop.is_set():
            item = self._q.get()
            if item is None:
                break
            method, args, kwargs = item
            self.busy_changed.emit(True)
            ok = False
            try:
                fn = getattr(self._dev, method)
                ok = bool(fn(*args, **kwargs))
            except Exception as e:
                self.error.emit(f"{method} failed: {e}")
                ok = False
            self.command_done.emit(method, ok)
            if self._q.empty():
                self.busy_changed.emit(False)

        # clean shutdown
        if self._status:
            self._status.stop()
        self._dev.close()
        self.disconnected.emit()

    def _keepalive_loop(self):
        while not self._stop.wait(self._keepalive_interval):
            self._dev.keepalive_poll()

    def _on_status_push(self, level, rate, raw):
        # called from the StatusListener thread; Qt signals are thread-safe to emit
        self.dpi_level_changed.emit(level)
        if rate is not None:
            self.rate_changed.emit(rate)
