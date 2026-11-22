"""
sm809pro.status -- background listener for device-pushed status (input report 4).

The device pushes report ID 4 on the MI_01/Col04 collection (usage_page 0x0A,
the LOWER of the two 0x0A collections; Col05 is the command interface). It fires
on DPI-level change (physical DPI+/- buttons) and as a ~5s heartbeat.

This module opens that interface separately and runs a thread that invokes a
callback whenever the reported DPI level changes. Used by the GUI for live
reflection and (later) by the daemon for the overlay HUD.
"""

import re
import threading

try:
    import hid
except Exception:  # pragma: no cover - hid is required at runtime
    hid = None

from . import protocol as P


def get_bluetooth_battery(serial=None) -> int | None:
    """
    On Windows, query SetupAPI for the Bluetooth Low Energy device's battery percentage.
    Returns integer percent (0..100) if found, else None.
    """
    import sys
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import uuid
        from ctypes import wintypes, c_void_p

        setupapi = ctypes.windll.setupapi
        setupapi.SetupDiGetClassDevsW.restype = c_void_p
        setupapi.SetupDiGetClassDevsW.argtypes = [c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
        setupapi.SetupDiEnumDeviceInfo.argtypes = [c_void_p, wintypes.DWORD, c_void_p]
        setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [c_void_p, c_void_p, wintypes.LPWSTR, wintypes.DWORD, c_void_p]
        setupapi.SetupDiDestroyDeviceInfoList.argtypes = [c_void_p]
        setupapi.SetupDiGetDevicePropertyW.argtypes = [
            c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, wintypes.DWORD, c_void_p, wintypes.DWORD
        ]

        class SP_DEVINFO_DATA(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("ClassGuid", ctypes.c_ubyte * 16),
                ("DevInst", wintypes.DWORD),
                ("Reserved", ctypes.c_size_t),
            ]

        class DEVPROPKEY(ctypes.Structure):
            _fields_ = [("fmtid", ctypes.c_ubyte * 16), ("pid", wintypes.DWORD)]

        u = uuid.UUID("{104ea319-6ee2-4701-bd47-8ddbf425bbe5}")
        raw = (ctypes.c_ubyte * 16)(*u.bytes_le)
        battery_key = DEVPROPKEY(raw, 2)

        # DIGCF_PRESENT = 2, DIGCF_ALLCLASSES = 4
        h = setupapi.SetupDiGetClassDevsW(None, "BTHLE", None, 2 | 4)
        if not h or h == c_void_p(-1).value:
            return None

        devinfo = SP_DEVINFO_DATA()
        devinfo.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
        idx = 0
        battery = None
        target_serial = serial.upper().replace(":", "") if serial else None

        while setupapi.SetupDiEnumDeviceInfo(h, idx, ctypes.byref(devinfo)):
            idx += 1
            buf = (ctypes.c_wchar * 512)()
            if setupapi.SetupDiGetDeviceInstanceIdW(h, ctypes.byref(devinfo), buf, 512, None):
                inst = buf.value.upper()
                if target_serial:
                    if target_serial not in inst:
                        continue
                elif "SM809" not in inst and "026D" not in inst and "RIVIERAWAVES" not in inst:
                    continue

                prop_type = wintypes.DWORD()
                val_buf = (ctypes.c_byte * 256)()
                if setupapi.SetupDiGetDevicePropertyW(
                    h, ctypes.byref(devinfo), ctypes.byref(battery_key),
                    ctypes.byref(prop_type), val_buf, 256, None, 0
                ):
                    val = val_buf[0]
                    if 0 <= val <= 100:
                        battery = val
                        break

        setupapi.SetupDiDestroyDeviceInfoList(h)
        return battery
    except Exception:
        return None


def find_status_interface(vid=P.VID, pid=None):
    """
    Return the hid enumeration dict for the status-push interface (Col04/Col05), or
    None. Status interface = the LOWER of the two usage_page 0x0A collections.
    """
    if hid is None:
        return None
    pids = [pid] if pid else [P.PID_WIRELESS, P.PID_WIRED, getattr(P, "PID_BLUETOOTH", 0x026D)]
    for p in pids:
        devs = hid.enumerate(vid, p)
        zero_a = [d for d in devs if d.get("usage_page") == 0x000A]
        if len(zero_a) >= 2:
            def coln(d):
                s = d.get("path", b"")
                s = s.decode(errors="replace") if isinstance(s, bytes) else str(s)
                m = re.search(r"Col(\d+)", s)
                return int(m.group(1)) if m else 99
            zero_a.sort(key=coln)
            return zero_a[0]  # Col04/Col05 (lower 0x0A collection)
    return None


class StatusListener(threading.Thread):
    """
    Polls input report 4 and reports device telemetry.

    Offline detection: the 2.4GHz dongle keeps pushing report 4 (~every 3s)
    whether the mouse is awake or not; the LINK byte (offset 1) is the signal:
    1 = mouse online, 0 = mouse offline (powered off / out of range). Confirmed
    on hardware. We report liveness from this byte directly, which is as fast as
    the next push (~1-3s) -- matching the official software -- rather than
    waiting for a silence timeout. As a fallback, if NO push arrives at all for
    `stale_after` seconds (e.g. dongle yanked), we also report offline.

    Callbacks (all optional; emitted from this thread, safe for Qt signals):
      on_change(level, rate_hz, raw)  -> DPI level changed (rate_hz decoded to Hz)
      on_battery(percent)             -> battery % changed
      on_alive(is_alive)              -> online/offline changed
      on_charging(is_charging)        -> charging state changed (if detectable)
    """

    def __init__(self, on_change=None, on_battery=None, on_alive=None,
                 on_charging=None, on_runapp=None, vid=P.VID, pid=None,
                 connection=None, poll_ms=200, stale_after=8.0):
        super().__init__(daemon=True)
        self.on_change = on_change
        self.on_battery = on_battery
        self.on_alive = on_alive
        self.on_charging = on_charging
        self.on_runapp = on_runapp        # (code) when a Run-APP button is pressed
        self._last_runapp = 0
        self.vid = vid
        self.pid = pid
        self.connection = connection
        self.poll_ms = poll_ms
        self.stale_after = stale_after
        self._stop = threading.Event()
        self._dev = None
        self.last_level = None
        self.last_rate = None
        self.last_battery = None
        self._alive = None
        self._charging = None
        self._last_rx = 0.0

    @property
    def is_bluetooth(self) -> bool:
        return (
            self.connection == "bluetooth"
            or self.pid == getattr(P, "PID_BLUETOOTH", 0x026D)
            or (self.pid not in (P.PID_WIRELESS, P.PID_WIRED) and self.pid is not None)
        )

    def open(self) -> bool:
        tgt = find_status_interface(self.vid, self.pid)
        if not tgt or hid is None:
            return False
        self._dev = hid.device()
        self._dev.open_path(tgt["path"])
        self._dev.set_nonblocking(1)
        return True

    def _emit_alive(self, alive):
        if self._alive is not alive:
            self._alive = alive
            if not alive:
                # going offline clears the GUI readouts; forget the last values so
                # the next ONLINE push re-emits DPI/rate/battery (they're usually
                # unchanged across the gap, which would otherwise suppress the
                # re-emit and leave the readouts blank until something changes).
                self.last_level = None
                self.last_rate = None
                self.last_battery = None
            if self.on_alive:
                try:
                    self.on_alive(alive)
                except Exception:
                    pass

    def _emit_charging(self, charging):
        if self._charging is not charging:
            self._charging = charging
            if self.on_charging:
                try:
                    self.on_charging(charging)
                except Exception:
                    pass

    @staticmethod
    def _decode_charging(r):
        """Charging detection from a status frame.

        Hardware finding (status_probe): byte[5] is the charging flag
        (1 = charging, 0 = not). Battery (byte[4]) is a clean 0..100 percent and
        does NOT encode charging. Tentative from a small sample but it's the only
        byte that tracked the charger; icon-only, so safe.
        """
        if len(r) > P.PUSH_OFF_CHARGING:
            return r[P.PUSH_OFF_CHARGING] != 0
        return False

    @staticmethod
    def _battery_percent(r):
        """Battery percent (0..100). byte[4] is already a clean percent."""
        batt = r[P.PUSH_OFF_BATTERY] if len(r) > P.PUSH_OFF_BATTERY else 0
        return min(max(batt, 0), 100)

    def run(self):
        import time
        if self._dev is None and not self.open():
            return
        self._last_rx = time.time()
        if self.is_bluetooth:
            self._emit_alive(True)
        while not self._stop.is_set():
            try:
                r = self._dev.read(32, timeout_ms=self.poll_ms)
            except Exception:
                if self.is_bluetooth:
                    self._emit_alive(False)
                    break
                r = None
            now = time.time()
            if r and len(r) > P.PUSH_OFF_BATTERY and r[0] == P.REPORT_ID_STATUS_PUSH:
                self._last_rx = now
                # LINK byte is the online/offline signal (1=on, 0=off).
                link = r[P.PUSH_OFF_LINK]
                self._emit_alive(link != 0)
                # Only treat DPI/battery as valid while the mouse is online;
                # when offline the dongle echoes stale values.
                if link != 0:
                    level = r[P.PUSH_OFF_DPI_LEVEL]
                    rate_byte = r[P.PUSH_OFF_RATE] if len(r) > P.PUSH_OFF_RATE else None
                    # the push reports the polling enum byte; decode to Hz
                    rate_hz = P.POLLING_REVERSE.get(rate_byte) if rate_byte is not None else None
                    # Emit on the FIRST push too (so the GUI shows the active DPI
                    # + rate immediately at startup), and whenever level OR rate
                    # changes.
                    if (self.last_level is None or level != self.last_level
                            or rate_byte != self.last_rate):
                        self.last_level, self.last_rate = level, rate_byte
                        if self.on_change:
                            try:
                                self.on_change(level, rate_hz, bytes(r))
                            except Exception:
                                pass
                    # battery % (plain 0..100) + charging state (byte[5])
                    batt = self._battery_percent(r)
                    if batt != self.last_battery:
                        self.last_battery = batt
                        if self.on_battery:
                            try:
                                self.on_battery(batt)
                            except Exception:
                                pass
                    self._emit_charging(self._decode_charging(r))
                    # Run-APP button: byte[7] carries (slot+1) of the pressed
                    # host-side button, 0 when none. Fire once on a new nonzero
                    # code (edge), so holding the button launches the app once.
                    code = r[P.PUSH_OFF_RUNAPP] if len(r) > P.PUSH_OFF_RUNAPP else 0
                    if code != self._last_runapp:
                        self._last_runapp = code
                        if code != 0 and self.on_runapp:
                            try:
                                self.on_runapp(code)
                            except Exception:
                                pass
            else:
                # Silence timeout: only apply to 2.4GHz dongle.
                # Over Bluetooth, reports only arrive on button events, not periodic heartbeats.
                if not self.is_bluetooth:
                    if (now - self._last_rx) > self.stale_after:
                        self._emit_alive(False)
            self._stop.wait(0.01)

    def stop(self):
        self._stop.set()
        if self._dev:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None
