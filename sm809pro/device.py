"""
sm809pro.device -- the SM809Pro device class (session + commands).

Consolidates the validated controller: persistent HID session (the fix for the
"works once then wedges" bug), thread-safe sends, and every confirmed command
(keys with the verified physical mapping, DPI, colors, polling, LOD, lighting,
power, sensor flags, macros, reset).

Design notes:
  * One persistent handle for the whole session, like GamingMS.exe. Callers
    open() once and keep the object alive (GUI/daemon model).
  * A persistent, monotonic sequence counter (never reset), matching the binary.
  * All sends go through a re-entrant lock so a background keep-alive/status
    thread can share the handle safely.
  * The "ACK" byte (report-6 byte[1]) is a constant on this device and is NOT a
    reliable success signal; we send, settle, and return True on a clean write.
    Real success is observed via effects / the status push, not this byte.
"""

import re
import time
import threading

try:
    import hid
except Exception:  # pragma: no cover
    hid = None

from . import protocol as P
from . import actions as A
from . import macros as M
from . import defaults as D


def pick_control_interface(devs):
    """The command interface = highest-Col usage_page 0x0A collection (Col05)."""
    cands = [d for d in devs if d.get("usage_page") == 0x000A]
    if cands:
        def coln(d):
            s = d.get("path", b"")
            s = s.decode(errors="replace") if isinstance(s, bytes) else str(s)
            m = re.search(r"Col(\d+)", s, re.I)
            return int(m.group(1)) if m else 0
        return max(cands, key=coln)
    return next((d for d in devs if d.get("usage") != 0x0002), devs[0])


def _has_command_interface(devs) -> bool:
    """True if this interface set exposes a usage_page 0x0A vendor collection
    (the report-6 command channel). Over Bluetooth this is often absent."""
    return any(d.get("usage_page") == 0x000A for d in devs)


def detect_modes(vid=P.VID):
    """
    Enumerate every connection mode currently present for the device.

    Returns a list of dicts, one per detected mode:
        {pid, connection, configurable, devs}
    where `connection` is "2.4GHz"/"wired"/"bluetooth"/"unknown" and
    `configurable` is True if the report-6 command interface is present.

    2.4GHz (0x026F) and wired (0x026E) are known PIDs. Anything else on the
    Elan VID (or devices matching SM809/Solakaka) is reported as bluetooth.
    """
    if hid is None:
        return []
    out = []
    seen = set()

    def classify(v, p):
        if v == vid:
            if p == P.PID_WIRELESS:
                return "2.4GHz"
            if p == P.PID_WIRED:
                return "wired"
        return "bluetooth"

    # Known PIDs first, then any other PID under the target VID (catches standard BT)
    all_devs = hid.enumerate(vid, 0)
    pids = [P.PID_WIRELESS, P.PID_WIRED] + sorted(
        {d.get("product_id") for d in all_devs} - {P.PID_WIRELESS, P.PID_WIRED}
    )
    for pid in pids:
        if (vid, pid) in seen or pid is None:
            continue
        seen.add((vid, pid))
        devs = hid.enumerate(vid, pid)
        if not devs:
            continue
        out.append({
            "vid": vid,
            "pid": pid,
            "connection": classify(vid, pid),
            "configurable": _has_command_interface(devs),
            "devs": devs,
        })

    # Also inspect global HID devices in case Bluetooth reports another VID with SM809/Solakaka
    try:
        global_devs = hid.enumerate(0, 0)
    except Exception:
        global_devs = []
    for d in global_devs:
        v = d.get("vendor_id")
        p = d.get("product_id")
        if (v, p) in seen or p is None or v is None:
            continue
        prod = (d.get("product_string") or "").lower()
        mfg = (d.get("manufacturer_string") or "").lower()
        if "sm809" in prod or "solakaka" in prod or "sm809" in mfg or "solakaka" in mfg:
            seen.add((v, p))
            devs = hid.enumerate(v, p)
            if devs:
                out.append({
                    "vid": v,
                    "pid": p,
                    "connection": classify(v, p),
                    "configurable": _has_command_interface(devs),
                    "devs": devs,
                })
    return out


def choose_mode(modes, prefer=("wired", "bluetooth", "2.4GHz")):
    """
    From detect_modes() output, pick the best mode.
    Priority order:
      1. wired: USB-C cable physically connected (charging + full config).
      2. bluetooth: mouse actively connected over Bluetooth (implies hardware switch is at BT).
      3. 2.4GHz: wireless USB dongle is plugged in.
    If configurable modes exist, prefer them. If only non-configurable modes exist
    (e.g. read-only Bluetooth), fallback to them so the device is recognized.
    """
    if not modes:
        return None
    # 1. If wired is connected, it always takes highest priority
    wired = [m for m in modes if m["connection"] == "wired"]
    if wired:
        return wired[0]
    # 2. If bluetooth is active, the physical mouse switch is in BT mode
    bt = [m for m in modes if m["connection"] == "bluetooth"]
    if bt:
        cfg_bt = [m for m in bt if m.get("configurable")]
        return cfg_bt[0] if cfg_bt else bt[0]
    # 3. If 2.4GHz dongle is present
    wl = [m for m in modes if m["connection"] == "2.4GHz"]
    if wl:
        return wl[0]
    # Fallback
    return modes[0]


class SM809Pro:
    """High-level controller for the SM809 Pro. Open once, keep alive."""

    def __init__(self, vid=P.VID, pid=None, sensor=P.DEFAULT_SENSOR):
        self.vid = vid
        self.pid = pid              # if None, auto-detect the best mode
        self.sensor = sensor
        self._dev = None
        self._seq = 1
        self._lock = threading.RLock()
        self.connection = None      # "2.4GHz" | "wired" | "bluetooth" | None
        self.configurable = True    # False if opened on an interface without command channel
        self.interface_info = None
        self.detected_modes = []    # list from detect_modes() at last open()
        self.last_error = None      # human-readable reason open() failed

    # -- lifecycle ------------------------------------------------------------
    def open(self) -> bool:
        """
        Detect the current connection mode and open the command interface.

        Supports tri-mode:
        - 2.4GHz and wired both expose the report-6 command interface and are supported.
        - Bluetooth is detected and supported. If Bluetooth exposes the command channel,
          it can be configured; if not, it opens in read-only mode so the GUI can
          recognize and monitor the mouse.
        """
        if hid is None:
            raise RuntimeError("hidapi not available")
        self.last_error = None

        # If the caller forced a specific PID, honor it directly.
        if self.pid is not None:
            devs = hid.enumerate(self.vid, self.pid)
            if not devs:
                self.last_error = f"PID {self.pid:#06x} not found."
                return False
            is_cfg = _has_command_interface(devs)
            self.configurable = is_cfg
            return self._open_devs(devs, self.pid, configurable=is_cfg)

        # Auto-detect across all modes.
        self.detected_modes = detect_modes(self.vid)
        if not self.detected_modes:
            self.last_error = ("Device not found. Turn on the mouse or plug in the "
                               "2.4GHz dongle / USB-C cable.")
            return False

        chosen = choose_mode(self.detected_modes)
        if chosen is None:
            conns = ", ".join(sorted({m["connection"] for m in self.detected_modes}))
            self.last_error = (
                f"Connected via {conns}, which doesn't expose the configuration "
                f"channel. Switch the mouse to 2.4GHz (dongle) or USB-C wired to "
                f"change settings."
            )
            return False

        self.vid = chosen.get("vid", self.vid)
        self.pid = chosen["pid"]
        self.configurable = chosen.get("configurable", True)
        return self._open_devs(chosen["devs"], chosen["pid"], chosen["connection"],
                               configurable=self.configurable)

    def _open_devs(self, devs, pid, connection=None, configurable=True) -> bool:
        self.connection = connection or (
            "2.4GHz" if pid == P.PID_WIRELESS
            else "wired" if pid == P.PID_WIRED else "bluetooth")
        self.configurable = configurable
        tgt = pick_control_interface(devs)
        self.interface_info = tgt
        self._dev = hid.device()
        try:
            self._dev.open_path(tgt["path"])
        except Exception as e:
            self._dev = None
            self.last_error = f"Could not open the command interface: {e}"
            return False
        self._dev.set_nonblocking(1)
        # Prime/wake (matches web driver): brief settle + a status read.
        time.sleep(0.05)
        try:
            self._dev.get_feature_report(P.REPORT_ID_STATUS_FEAT, 32)
        except Exception:
            pass
        time.sleep(0.03)
        return True

    def close(self):
        with self._lock:
            if self._dev:
                try:
                    self._dev.close()
                finally:
                    self._dev = None
            self.connection = None
            self.interface_info = None

    @property
    def is_open(self) -> bool:
        return self._dev is not None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()

    # -- low level ------------------------------------------------------------
    def _next_seq(self) -> int:
        s = self._seq
        self._seq = (self._seq + 1) % 256
        return s

    def _send_packet(self, packet: bytes) -> bool:
        """Prepend report id, write, settle. Returns True on a clean write."""
        if not self.configurable:
            return False
        send_buf = bytes([P.REPORT_ID_CMD]) + packet
        with self._lock:
            if self._dev is None:
                return False
            try:
                self._dev.send_feature_report(send_buf)
            except Exception:
                return False
            time.sleep(P.CMD_DELAY)
            # Drain the idle/echo buffer (keeps parity with the official flow);
            # the value is not a reliable ACK, so we don't gate on it.
            try:
                self._dev.get_feature_report(P.REPORT_ID_CMD, 32)
            except Exception:
                pass
        return True

    def send_command(self, cmd: int, sub: int, data: bytes = b"", pad: int = 0xFF) -> bool:
        seq = self._next_seq()
        return self._send_packet(P.build_packet(cmd, seq, sub, data, pad))

    def send_raw(self, payload31: bytes) -> bool:
        if len(payload31) != P.PACKET_LEN:
            raise ValueError(f"need {P.PACKET_LEN} bytes, got {len(payload31)}")
        return self._send_packet(bytes(payload31))

    def keepalive_poll(self) -> bool:
        """A harmless read used by a background keep-alive thread.
        Returns True if successful, False if the device handle is dead/unresponsive."""
        with self._lock:
            if not self._dev:
                return False
            try:
                self._dev.get_feature_report(P.REPORT_ID_CMD, 32)
                return True
            except Exception:
                return False

    # -- status ---------------------------------------------------------------
    def read_status(self):
        with self._lock:
            if self._dev is None:
                return None
            try:
                raw = self._dev.get_feature_report(P.REPORT_ID_STATUS_FEAT, 32)
            except Exception:
                return None
        if not raw:
            return None
        d = bytes(raw)
        return d[1:] if d and d[0] == P.REPORT_ID_STATUS_FEAT else d

    # -- DPI ------------------------------------------------------------------
    def _dpi_payload(self, dpi_levels, selected) -> bytes:
        """Build the 18-byte DPI data block: [selected, bitmask, 8x raw LE16].
        Unused stages (beyond the enabled count) are 0x0000, matching the
        official app's capture (NOT a repeat of the last value)."""
        n = len(dpi_levels)
        bitmask = (1 << n) - 1
        data = bytearray([selected & 0xFF, bitmask & 0xFF])
        for i in range(8):
            if i < n:
                raw = P.dpi_to_raw(dpi_levels[i], self.sensor)
            else:
                raw = 0x0000
            data += bytes([raw & 0xFF, (raw >> 8) & 0xFF])
        return bytes(data)

    def _send_dpi_pair(self, dpi_levels, selected) -> bool:
        """
        Send the DPI config as the PAIR of class-0x02 packets the official app
        sends (sub 0x02 then 0x12), both carrying the same payload incl.
        `selected`. BOTH are required for the device to commit the active stage
        (confirmed by USB capture). Pad is 0x00 to match the capture. Returns
        True if both wrote cleanly.
        """
        payload = self._dpi_payload(dpi_levels, selected)
        ok1 = self.send_command(P.CMD_DPI_VALUES, P.DPI_SUBCMD_1, payload, pad=0x00)
        ok2 = self.send_command(P.CMD_DPI_VALUES, P.DPI_SUBCMD_2, payload, pad=0x00)
        return ok1 and ok2

    def set_dpi(self, dpi_levels, selected=0, colors=None) -> bool:
        """
        Write the DPI stage configuration (values + active stage + optional
        colors). `selected` is the 0-based index (within the enabled list) of
        the stage to make active.

        Sends the class-0x02 config as a PAIR of packets (sub 0x02 + 0x12) --
        BOTH are needed or the device won't switch the live DPI (confirmed by
        USB capture, session 9j). This is also how the active stage is set, so
        set_active_dpi() is just this with the same values + a new `selected`.
        """
        n = len(dpi_levels)
        if not (1 <= n <= 8):
            raise ValueError("1-8 DPI levels")
        ok = self._send_dpi_pair(dpi_levels, selected)
        if colors:
            ok = self.set_dpi_colors(colors) and ok
        return ok

    def set_dpi_colors(self, colors) -> bool:
        data = bytearray()
        for i in range(8):
            r, g, b = colors[i] if i < len(colors) else (0xEA, 0x5E, 0x56)
            data += bytes([r & 0xFF, g & 0xFF, b & 0xFF])
        return self.send_command(P.CMD_DPI_COLORS, 0x01, bytes(data))

    def set_active_dpi(self, dpi_levels, selected) -> bool:
        """
        Switch the LIVE/active DPI stage on the device.

        CONFIRMED (USB capture, session 9j): the official app switches DPI by
        re-sending the class-0x02 DPI config as a PAIR of packets (sub 0x02 +
        0x12) with a new `selected` byte -- there is NO separate switch command
        (the earlier class-0x0A guess was wrong and corrupted state). Because
        the device wants the full config, this takes the current `dpi_levels`
        too; pass the same values currently configured.

        `selected` is the 0-based index within the enabled `dpi_levels` list.
        """
        n = len(dpi_levels)
        if not (1 <= n <= 8):
            raise ValueError("1-8 DPI levels")
        if not (0 <= selected < n):
            raise ValueError("selected out of range")
        return self._send_dpi_pair(dpi_levels, selected)

    # -- polling / LOD --------------------------------------------------------
    def set_polling_rate(self, hz: int) -> bool:
        if hz not in P.POLLING_ENUM:
            raise ValueError(f"hz must be one of {list(P.POLLING_ENUM)}")
        return self.send_command(P.CMD_POLLING, 0x01, bytes([P.POLLING_ENUM[hz]]), pad=0x00)

    def set_lod(self, mm: int) -> bool:
        if mm not in (1, 2):
            raise ValueError("lod must be 1 or 2")
        return self.send_command(P.CMD_LOD, 0x01, bytes([mm]))

    # -- lighting -------------------------------------------------------------
    def set_lighting(self, mode, brightness=4, speed=3, direction=0, color=(255, 0, 0)) -> bool:
        bri = max(1, min(4, brightness))
        spd = max(1, min(3, speed))
        r, g, b = color
        data = bytes([0xFF, mode & 0xFF, ((bri << 4) | spd) & 0xFF,
                      direction & 0xFF, r & 0xFF, g & 0xFF, b & 0xFF])
        return self.send_command(P.CMD_LIGHTING, 0x01, data)

    # -- power / sensor -------------------------------------------------------
    def set_power(self, sleep_time=20, move_wakeup=True, move_lighting=False) -> bool:
        data = bytes([sleep_time & 0xFF, 1 if move_wakeup else 0, 1 if move_lighting else 0])
        return self.send_command(P.CMD_POWER, 0x01, data)

    def set_sensor_flags(self, angle_snap=False, motion_sync=True, ripple=False) -> bool:
        data = bytes([1 if angle_snap else 0, 1 if motion_sync else 0, 1 if ripple else 0])
        return self.send_command(P.CMD_SENSOR_FLAGS, 0x01, data)

    # -- keys (verified physical mapping + 9/7 packet split) ------------------
    def set_keys(self, codes_by_physical) -> bool:
        """
        codes_by_physical: 16-entry list indexed by 0-based PHYSICAL button.
        Sends the full map as two packets exactly like GamingMS.exe sub_437D00.
        """
        slots = A.physical_to_slots(codes_by_physical)
        d1 = bytearray()
        for s in range(0, A.KEYS_SPLIT):
            d1 += bytes(slots[s])
        ok1 = self.send_command(P.CMD_KEYS, A.KEYS_SUBCMD_1, bytes(d1))
        d2 = bytearray()
        for s in range(A.KEYS_SPLIT, A.NUM_BUTTONS):
            d2 += bytes(slots[s])
        ok2 = self.send_command(P.CMD_KEYS, A.KEYS_SUBCMD_2, bytes(d2))
        return ok1 and ok2

    def set_keys_default(self) -> bool:
        """Restore the factory-default button layout."""
        return self.set_keys(A.default_button_codes())

    def apply_macro_buttons(self, codes, macros=None) -> bool:
        """Upload the referenced macros, then write the 16-button map (one op).

        `codes` is the final 16-entry list of 3-byte action tuples (any macro
        buttons already resolved to 0x90 codes with their assigned slot by the
        caller). `macros` maps those slots to event lists. Upload FIRST so the
        data is resident before the key map references it. This is the
        upload-on-assign path: macros reach the device only when a button binds
        them."""
        ok = self.set_keys(codes)           # KEYS FIRST (matches official app order from pcap)
        if macros:
            ok = self.upload_macros(macros) and ok
        return ok

    # -- macros ---------------------------------------------------------------
    def upload_macro(self, slot: int, events) -> bool:
        """CLEAR then chunked DATA upload (does NOT bind a button)."""
        self.send_command(P.CMD_MACRO_CLEAR, 0x01, bytes([0xFF]), pad=0x00)
        time.sleep(P.MACRO_CHUNK_DELAY)
        ok = True
        for subcmd, data in M.build_chunks(slot, events):
            if not self.send_command(P.CMD_MACRO_DATA, subcmd, data, pad=0x00):
                ok = False
            time.sleep(P.MACRO_CHUNK_DELAY)
        return ok

    def upload_macros(self, macros) -> bool:
        """
        Sync a FULL set of macros to the device in one batch.

        `macros` maps slot index (0..15) -> events list (the macros.py event
        dict format). The CLEAR command (class 0x11) takes no slot, so it wipes
        ALL macro memory; the only consistent way to keep several macros
        resident at once is therefore to CLEAR once and then upload every
        non-empty slot's DATA. So this is the correct full-sync primitive: a
        single CLEAR followed by DATA chunks per slot. Empty slots are skipped;
        an empty `macros` just clears the device.

        NOTE: single-macro upload is hardware-confirmed; multi-slot residency
        after ONE clear is the natural protocol reading but is PENDING a live
        confirm (does the device retain slots 1+3 after clear+seq DATA?).
        """
        self.send_command(P.CMD_MACRO_CLEAR, 0x01, bytes([0xFF]), pad=0x00)
        time.sleep(P.MACRO_CHUNK_DELAY)
        ok = True
        for slot, events in sorted(macros.items()):
            if not events:
                continue
            for subcmd, data in M.build_chunks(slot, events):
                if not self.send_command(P.CMD_MACRO_DATA, subcmd, data, pad=0x00):
                    ok = False
                time.sleep(P.MACRO_CHUNK_DELAY)
        return ok

    def erase_macros(self) -> bool:
        return self.send_command(P.CMD_MACRO_CLEAR, 0x01, bytes([0xFF]), pad=0x00)

    # -- reset ----------------------------------------------------------------
    def factory_reset(self) -> bool:
        """Send the firmware reset command (class 0x0F)."""
        return self.send_command(P.CMD_RESET, 0x01, bytes([0xFF]), pad=0x00)

    def factory_restore(self, include_buttons=True) -> bool:
        """
        Re-push every factory default (DPI/colors/polling/LOD/lighting/power/
        sensor + buttons), matching the official 'Restore'. Does NOT clear
        uploaded macros. See sm809pro.defaults for the values.
        """
        return D.apply_all(self, include_buttons=include_buttons,
                           include_macros_clear=False)
