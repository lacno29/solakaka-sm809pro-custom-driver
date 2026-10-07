"""
app.psf_import -- read-only importer for the official software's .psf profiles
(Milestone 3 step 2).

The stock app stores each profile as a UTF-16LE INI-style file in
`SM809pro Mouse\\config\\` (default0..4.psf) or wherever the user exports one.
This module parses one into our profile schema (see app.profile_store) so users
can migrate their existing setup. It is READ-ONLY: it never writes a .psf.

EVERYTHING here was verified byte-for-byte against two purpose-built captures
(custom1_red.psf / custom2_colorful.psf -- every physical button set to a unique
key, lighting set to two known modes):

- BUTTONS: the .psf stores `Key{0..15}Value` = 3-byte action codes in PROTOCOL
  SLOT order (identical 3-byte format to our bindings, e.g. `700010` = kb('m')).
  `actions.PERMUTE[n]` maps slot n -> the 0-based PHYSICAL button, so
  bindings[PERMUTE[n]] = code(Key{n}). Confirmed via the Key{n}Name labels
  (Key0=Left, Key7=A -> physical 1, Key13=I -> physical 9, ...).
- DPI: `XYSetting{1..8}ValueX` (newer) or `XYSetting{n}Value` (older) hold the
  16-bit raw DPI; `protocol.raw_to_dpi` decodes it ((raw+1)*100). `DPIOffOnFlagValue`
  is the enabled-stage bitmask (3F = 6 stages). `CurrentDPILevelValue` is the
  0-based active stage. `DPILevelIndication{0..7}Valuer` are RRGGBB stage colors.
- POLLING: `PollingRateValue` first byte = polling enum (protocol.POLLING_REVERSE).
- LOD: `LiftDetectionValue` = lift height in mm (1 or 2).
- LIGHTING: `Lighting1ModeValue` first byte == our protocol mode index directly
  (verified: 08=Red Full, 02=Colorful Streaming, 01=Stars Twinkle).
- POWER: `PowerDownTime` (min), `MotionWakeup`, `MoveLightingOnOffMode`.
- SENSOR: `AngleSnap`/`AngleSnapValue`, `MotionSync`, `RippleControl`.
- AUTO-SWITCH: `GameFile0/1/2` = per-app bindings -> our match_rules (the stock
  app exposes no UI for these, so they are usually blank; our app fills them).

NOT imported: per-button MACROS (the 8-byte on-disk AllAction records) -- none of
the validated samples used them and the host macro library is separate; macro
buttons would need the library entry too. Documented as a known gap.

The Windows pointer/accel fields (DoubleClickSpeed, PointerSpeed, ...) are OS
settings, not device state -- ignored.
"""

import os
import re

from sm809pro import actions as A
from sm809pro.protocol import raw_to_dpi, POLLING_REVERSE
from sm809pro import defaults as D


# Windows Virtual-Key -> USB HID usage. The .psf stores macro keystrokes as VK
# codes (decoded from macro.psf: a0 48 45 4c 4c 4f = Shift H E L L O = "Hello").
def _build_vk_to_hid():
    m = {}
    for i in range(26):                 # A-Z
        m[0x41 + i] = 0x04 + i
    for i in range(1, 10):              # 1-9
        m[0x30 + i] = 0x1E + (i - 1)
    m[0x30] = 0x27                      # 0
    m.update({
        0x0D: 0x28, 0x1B: 0x29, 0x08: 0x2A, 0x09: 0x2B, 0x20: 0x2C,  # enter esc bksp tab space
        0xBD: 0x2D, 0xBB: 0x2E, 0xDB: 0x2F, 0xDD: 0x30, 0xDC: 0x31,  # - = [ ] backslash
        0xBA: 0x33, 0xDE: 0x34, 0xC0: 0x35, 0xBC: 0x36, 0xBE: 0x37, 0xBF: 0x38,  # ; ' ` , . /
        0x14: 0x39,                                                  # caps lock
        0x2C: 0x46, 0x91: 0x47, 0x13: 0x48, 0x2D: 0x49, 0x24: 0x4A,  # prtsc scroll pause ins home
        0x21: 0x4B, 0x2E: 0x4C, 0x23: 0x4D, 0x22: 0x4E,              # pgup del end pgdn
        0x27: 0x4F, 0x25: 0x50, 0x28: 0x51, 0x26: 0x52,              # right left down up
        # modifiers (left/right + the generic VK_SHIFT/CONTROL/MENU)
        0xA0: 0xE1, 0xA1: 0xE5, 0xA2: 0xE0, 0xA3: 0xE4, 0xA4: 0xE2, 0xA5: 0xE6,
        0x5B: 0xE3, 0x5C: 0xE7, 0x10: 0xE1, 0x11: 0xE0, 0x12: 0xE2,
    })
    for i in range(12):                 # F1-F12
        m[0x70 + i] = 0x3A + i
    for i in range(10):                 # numpad 0-9 (NP1..NP9 = 0x59.., NP0 = 0x62)
        m[0x61 + i] = 0x59 + i
    m[0x60] = 0x62
    m.update({0x6F: 0x54, 0x6A: 0x55, 0x6D: 0x56, 0x6B: 0x57, 0x6E: 0x63, 0x90: 0x53})
    return m


VK_TO_HID = _build_vk_to_hid()


class PsfError(Exception):
    pass


def parse_psf_text(text):
    """Flatten a .psf into {key: value}. Keys are unique enough across the file
    (Key0Value, XYSetting1ValueX, ...) that a flat dict is sufficient; section
    headers and indentation (tabs) are ignored."""
    d = {}
    for line in text.lstrip("﻿").splitlines():
        line = line.strip()
        if not line or line.startswith("[") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        d[k.strip()] = v.strip()
    return d


def read_psf_text(path):
    try:
        with open(path, "r", encoding="utf-16-le") as f:
            text = f.read()
    except Exception as e:
        raise PsfError(f"Could not read .psf (expected UTF-16LE): {e}")
    if "Key0Value" not in text and "DPIOffOnFlagValue" not in text:
        raise PsfError("This does not look like an SM809 .psf profile.")
    return text


def read_psf(path):
    return parse_psf_text(read_psf_text(path))


def decode_macro_events(blob):
    """Decode a .psf AllAction blob (8-byte records) to our macro event list.

    Record = [VK, up?(0x80 in byte1), 0, 0, type(0x03=keyboard), 0, delay_hi,
    delay_lo]. Verified vs macro.psf ("Hello" via VK codes a0/48/45/4c/4f).
    Only keyboard events are decoded (the only type seen); others are skipped.
    """
    b = bytes.fromhex(blob)
    events = []
    for i in range(0, len(b) - 7, 8):
        rec = b[i:i + 8]
        if not any(rec):
            break
        vk, flag, etype = rec[0], rec[1], rec[4]
        delay = (rec[6] << 8) | rec[7]
        if etype in (0x00, 0x03):           # keyboard
            hid = VK_TO_HID.get(vk)
            if hid is None:
                continue
            events.append({"type": "key", "keycode": hid,
                           "down": not (flag & 0x80), "next_delay": delay})
    return events


_MACRO_BLOCK = re.compile(
    r"MacroKey(\d+)Name=([^\r\n]*)[\s\S]*?MacroActionNum=(\d+)"
    r"[\s\S]*?AllAction=([0-9A-Fa-f]+)")


def to_macros(text, d):
    """Extract per-key macros bound on a 0x90 (play-macro) button. Returns a list
    of {tempid, name, events, phys, playmode, repeat}; phys is the 1-based
    physical button (via PERMUTE). Macros with no decodable events are skipped."""
    out = []
    for m in _MACRO_BLOCK.finditer(text):
        n, name, num, blob = int(m.group(1)), m.group(2).strip(), int(m.group(3)), m.group(4)
        val = d.get(f"Key{n}Value", "")
        if num == 0 or not val.startswith("90") or len(val) < 6:
            continue
        code = bytes.fromhex(val[:6])
        events = decode_macro_events(blob)
        if not events:
            continue
        out.append({"tempid": f"psf{n}", "name": name or f"Imported {n}",
                    "events": events, "phys": A.PERMUTE[n] + 1,
                    "playmode": ((code[1] >> 4) & 0x0F) or 1, "repeat": code[2]})
    return out


# -- field decoders ----------------------------------------------------------
def _hexbyte(s, default=0):
    """First byte of a hex field. .psf packs multi-byte values big-endian, e.g.
    Lighting1ModeValue=080000 -> 0x08, PollingRateValue=020000 -> 0x02; the
    single-byte fields (DPIOffOnFlagValue=3F, CurrentDPILevelValue=03) also take
    the first two chars correctly."""
    try:
        return int(str(s).strip()[:2], 16) & 0xFF
    except (TypeError, ValueError):
        return default


def _bool01(s, default=False):
    if s is None:
        return default
    return s.strip() not in ("0", "00", "", "false", "False")


def _buttons(d):
    """16-entry physical-button bindings (3-byte lists), factory-default for any
    Key slot the .psf omits. A Run-APP key (value 600500) carries its exe path in
    a Key{N}URL field -> imported as a {"runapp": path} binding (not a bare code),
    so it launches in our app too."""
    run_app = tuple(A.BTN["run_app"])
    bindings = [list(c) for c in A.default_button_codes()]
    for n in range(A.NUM_BUTTONS):
        v = d.get(f"Key{n}Value")
        if not v or len(v) < 6:
            continue
        try:
            b = bytes.fromhex(v[:6])
        except ValueError:
            continue
        if (b[0], b[1], b[2]) == run_app:
            url = (d.get(f"Key{n}URL") or "").strip()
            bindings[A.PERMUTE[n]] = {"runapp": url}
        else:
            bindings[A.PERMUTE[n]] = [b[0], b[1], b[2]]
    return bindings


def _dpi(d):
    flag = _hexbyte(d.get("DPIOffOnFlagValue", "3F"), 0x3F)
    enabled = bin(flag).count("1") or D.DPI_ENABLED_COUNT
    enabled = max(1, min(8, enabled))
    values = []
    for i in range(1, enabled + 1):
        raw = d.get(f"XYSetting{i}ValueX") or d.get(f"XYSetting{i}Value")
        if raw is None:
            values.append(D.DPI_VALUES[i - 1] if i - 1 < len(D.DPI_VALUES) else 800)
        else:
            try:
                values.append(raw_to_dpi(int(raw, 16)))
            except ValueError:
                values.append(800)
    colors = []
    for i in range(enabled):
        c = d.get(f"DPILevelIndication{i}Valuer", "FFFFFF")
        try:
            colors.append([int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)])
        except ValueError:
            colors.append([255, 255, 255])
    selected = _hexbyte(d.get("CurrentDPILevelValue", "0"), 0)
    selected = max(0, min(enabled - 1, selected))
    return {"values": values, "colors": colors,
            "enabled_count": enabled, "selected": selected}


def to_config(d):
    """Map a parsed .psf dict to our profile `config` schema."""
    polling = POLLING_REVERSE.get(_hexbyte(d.get("PollingRateValue", "020000")), D.POLLING_HZ)
    lod = _hexbyte(d.get("LiftDetectionValue", "02"), D.LOD_MM)
    lod = lod if lod in (1, 2) else D.LOD_MM
    mode = _hexbyte(d.get("Lighting1ModeValue", "020000"), D.LIGHTING_MODE)
    return {
        "buttons": _buttons(d),
        "dpi": _dpi(d),
        "polling_hz": polling,
        "lod_mm": lod,
        # color is predefined by the device for single-color modes; keep our
        # default (the .psf FixedColor table is per-mode and unused by 8/9/10).
        "lighting": {"mode": mode, "color": list(D.LIGHTING_COLOR)},
        "power": {
            "sleep_min": _int(d.get("PowerDownTime"), D.POWER_SLEEP_MIN),
            "move_wakeup": _bool01(d.get("MotionWakeup"), D.POWER_MOVE_WAKEUP),
            "move_lighting": _bool01(d.get("MoveLightingOnOffMode"), D.POWER_MOVE_LIGHTING),
        },
        "sensor": {
            "angle_snap": _bool01(d.get("AngleSnapValue", d.get("AngleSnap")), D.SENSOR_ANGLE_SNAP),
            "motion_sync": _bool01(d.get("MotionSync"), D.SENSOR_MOTION_SYNC),
            "ripple": _bool01(d.get("RippleControl"), D.SENSOR_RIPPLE),
        },
    }


def to_match_rules(d):
    """GameFile0/1/2 -> match rules (exe basename). Usually blank: the stock app
    has no auto-switch UI, so these are filled in OUR app."""
    rules = []
    for i in range(3):
        g = (d.get(f"GameFile{i}") or "").strip()
        if g:
            rules.append({"exe": os.path.basename(g).lower(), "title": None})
    return rules


def _int(s, default):
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return default


def import_psf(path):
    """Parse a .psf file into a profile-ready dict:
        {"name": str, "match_rules": [...], "config": {...}, "macros": [...]}
    `macros` are decoded library macros (each with a tempid the caller remaps to a
    real MacroStore id); the corresponding buttons reference that tempid via a
    {"macro": tempid, ...} binding. Raises PsfError on unreadable / non-.psf input.
    """
    text = read_psf_text(path)
    d = parse_psf_text(text)
    name = (d.get("ProfileName") or os.path.splitext(os.path.basename(path))[0]).strip()
    config = to_config(d)
    macros = to_macros(text, d)
    # point each macro button at its temp id instead of the raw 0x90 code
    for mac in macros:
        i = mac["phys"] - 1
        if 0 <= i < len(config["buttons"]):
            config["buttons"][i] = {"macro": mac["tempid"],
                                    "playmode": mac["playmode"], "repeat": mac["repeat"]}
    return {"name": name or "Imported", "match_rules": to_match_rules(d),
            "config": config, "macros": macros}
