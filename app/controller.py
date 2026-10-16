"""
app.controller -- DeviceController: owns the SM809Pro session off the UI thread.

The GUI must never block on HID I/O (a SetFeature + 60ms settle would freeze the
UI). So all device calls run on a dedicated worker thread via a queue, and
results/events come back as Qt signals. The persistent session + keep-alive
(the wedge fix) live here too, plus the StatusListener for live DPI reflection,
and automatic background reconnection & mode switching (2.4GHz / Bluetooth / wired).

Usage from the UI:
    ctrl = DeviceController()
    ctrl.connected.connect(on_connected)
    ctrl.dpi_level_changed.connect(on_dpi_push)   # live status push
    ctrl.command_done.connect(on_done)
    ctrl.start()                 # starts background auto-detection loop
    ctrl.call("set_dpi", [800, 1600, 3200])   # queue a device call by method name
"""

import queue
import threading
import time

from PySide6.QtCore import QObject, Signal

from sm809pro import SM809Pro
from sm809pro.device import detect_modes
from sm809pro.status import StatusListener


class DeviceController(QObject):
    # lifecycle
    connected = Signal(dict)        # {connection, product, configurable} on success
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
        self._stop = threading.Event()
        self._keepalive_interval = keepalive_interval
        self._last_keepalive = 0.0
        self._last_mode_check = 0.0
        self._is_connected = False
        self._dev_lock = threading.RLock()

    # -- public API -----------------------------------------------------------
    def start(self):
        """Start the background worker thread for auto-detection and command processing."""
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def call(self, method: str, *args, **kwargs):
        """Queue a device method call by name; result via command_done signal."""
        self._q.put((method, args, kwargs))

    def shutdown(self):
        """Cleanly stop worker thread, status listener, and close device."""
        self._stop.set()
        self._q.put(None)  # unblock worker queue
        if self._status:
            try:
                self._status.stop()
            except Exception:
                pass
            self._status = None
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2.0)
        with self._dev_lock:
            self._dev.close()

    # -- worker thread --------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            # 1. If not connected, attempt auto-detection / connect
            if not self._is_connected or not self._dev.is_open:
                self._attempt_connect()
                if not self._is_connected:
                    # Still disconnected: drain any queued calls so callers don't hang
                    self._drain_queue()
                    # Wait 1.5s before next polling attempt
                    self._stop.wait(1.5)
                    continue

            # 2. Wait for next queued command or timeout (1.0s) for health monitoring
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                item = None

            if self._stop.is_set():
                break

            # 3. Process command if present
            if item is not None:
                method, args, kwargs = item
                self.busy_changed.emit(True)
                ok = False
                try:
                    with self._dev_lock:
                        fn = getattr(self._dev, method)
                        ok = bool(fn(*args, **kwargs))
                except Exception as e:
                    self.error.emit(f"{method} failed: {e}")
                    ok = False
                self.command_done.emit(method, ok)
                if self._q.empty():
                    self.busy_changed.emit(False)

            # 4. Connection maintenance & mode checking
            if self._is_connected and not self._stop.is_set():
                self._maintain_connection()

        # Clean shutdown
        self._teardown_device()

    def _attempt_connect(self):
        with self._dev_lock:
            ok = False
            try:
                ok = self._dev.open()
            except Exception as e:
                ok = False

            if ok:
                self._is_connected = True
                info = {
                    "connection": self._dev.connection,
                    "product": (self._dev.interface_info or {}).get("product_string", "SM809 Pro"),
                    "configurable": getattr(self._dev, "configurable", True),
                }
                self.connected.emit(info)

                # Spin up StatusListener
                if self._status:
                    try:
                        self._status.stop()
                    except Exception:
                        pass
                    self._status = None

                self._status = StatusListener(
                    on_change=self._on_status_push,
                    on_battery=lambda pct: self.battery_changed.emit(pct),
                    on_alive=self._on_alive_event,
                    on_charging=lambda ch: self.charging_changed.emit(ch),
                    on_runapp=lambda code: self.runapp_pressed.emit(code),
                    pid=self._dev.pid,
                    vid=self._dev.vid,
                )
                self._status.start()
                self._last_keepalive = time.time()
                self._last_mode_check = time.time()

    def _maintain_connection(self):
        now = time.time()

        # Periodic keep-alive poll (every _keepalive_interval, default 8s)
        if now - self._last_keepalive >= self._keepalive_interval:
            self._last_keepalive = now
            with self._dev_lock:
                if self._dev.is_open:
                    if not self._dev.keepalive_poll():
                        # Device is no longer responding
                        self._teardown_device()
                        return

        # Periodic mode & liveness check (every 1.5s)
        if now - self._last_mode_check >= 1.5:
            self._last_mode_check = now
            conn = self._dev.connection

            # If connected via 2.4GHz dongle, but mouse is reported offline (link==0):
            # check if mouse has connected via Bluetooth!
            if conn == "2.4GHz" and self._status and self._status._alive is False:
                modes = detect_modes(self._dev.vid)
                if any(m["connection"] == "bluetooth" for m in modes):
                    # Mouse switched to Bluetooth! Tear down 2.4GHz so next cycle connects BT
                    self._teardown_device()
                    return

            # If connected via Bluetooth:
            # 1. Check if wired USB cable was plugged in (wired takes priority)
            # 2. Check if device is still present in detect_modes()
            if conn == "bluetooth":
                modes = detect_modes(self._dev.vid)
                if any(m["connection"] == "wired" for m in modes):
                    # Wired cable attached! Switch to wired
                    self._teardown_device()
                    return
                if not any(m["connection"] == "bluetooth" for m in modes):
                    # Bluetooth disconnected / went to sleep
                    self._teardown_device()
                    return

    def _teardown_device(self):
        was_connected = self._is_connected
        self._is_connected = False
        if self._status:
            try:
                self._status.stop()
            except Exception:
                pass
            self._status = None
        with self._dev_lock:
            try:
                self._dev.close()
            except Exception:
                pass
            # Reset pid to None so next open() runs auto-detect
            self._dev.pid = None
        if was_connected:
            self.disconnected.emit()

    def _drain_queue(self):
        while not self._q.empty():
            try:
                item = self._q.get_nowait()
                if item is None:
                    break
                method, args, kwargs = item
                self.command_done.emit(method, False)
            except queue.Empty:
                break
        self.busy_changed.emit(False)

    def _on_alive_event(self, alive: bool):
        self.alive_changed.emit(alive)
        if not alive and getattr(self._dev, "connection", None) == "2.4GHz":
            # If mouse went offline on 2.4GHz, fast-track mode check on next cycle
            self._last_mode_check = 0.0

    def _on_status_push(self, level, rate, raw):
        # called from the StatusListener thread; Qt signals are thread-safe to emit
        self.dpi_level_changed.emit(level)
        if rate is not None:
            self.rate_changed.emit(rate)
