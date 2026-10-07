"""
sm809pro.macros -- macro event encoding + chunked upload.

Verified against GamingMS.exe sub_436A50 and the real on-disk macro blob in
default0.psf. A macro is a list of events; each encodes to a 3-byte WIRE event:

    b0 = (delay_hi & 0x0F) | type_nibble | (0x80 if key-UP else 0x00)
    b1 = delay_lo            (low 8 bits of the inter-event gap, ms 0..4095)
    b2 = code                (HID usage / mouse-bit / consumer code)

type_nibble: 0x30 keyboard, 0x20 consumer, 0x10 mouse. The delay is the gap
BEFORE the NEXT event (delay-folded-into-next), which is how the device reads it.

Upload protocol:
  1. CLEAR: class 0x11, subcmd 1, data byte 0xFF.
  2. DATA:  class 0x10, in <=25-byte chunks. Per chunk:
       payload = [0x10][seq][subcmd][checksum][lengthByte][macroSlot][<=25 data]
       subcmd     = (chunkIndex << 4) | chunkCount
       lengthByte = 1 + len(chunk)
     Chunks are spaced MACRO_CHUNK_DELAY (120 ms) apart.
"""

from . import protocol as P

# Max events per macro. The official software's on-disk macro buffer is 1000
# bytes = 125 eight-byte records (confirmed from macro_limit.psf:
# MacroActionNum=249 = 125 key events + 124 inter-event delays). Our atomic
# events map ~1:1 to those records, so we cap at 125 to stay within the device's
# per-slot limit.
MAX_MACRO_EVENTS = 125

MOUSE_BITS = {1: 0x01, 2: 0x02, 3: 0x04, 4: 0x08, 5: 0x10}

# HID keyboard usages for the (left) modifier keys, used as STANDALONE key
# events inside a macro (a macro replays raw key down/up, so a modifier is just
# another key event -- unlike the 0x70 button combo which uses a mod mask).
KEY_LCTRL = 0xE0
KEY_LSHIFT = 0xE1
KEY_LALT = 0xE2
KEY_LGUI = 0xE3   # Windows / Meta


def _build_char_map():
    """char -> (HID usage, needs_shift) for printable ASCII (US layout)."""
    m = {}
    for i in range(26):                       # a-z / A-Z
        m[chr(ord("a") + i)] = (0x04 + i, False)
        m[chr(ord("A") + i)] = (0x04 + i, True)
    for i, ch in enumerate("1234567890"):     # digits (0 is 0x27)
        m[ch] = (0x1E + i if ch != "0" else 0x27, False)
    for i, ch in enumerate("!@#$%^&*()"):     # shifted digits
        m[ch] = (0x1E + i if i < 9 else 0x27, True)
    m.update({
        "-": (0x2D, False), "_": (0x2D, True),
        "=": (0x2E, False), "+": (0x2E, True),
        "[": (0x2F, False), "{": (0x2F, True),
        "]": (0x30, False), "}": (0x30, True),
        "\\": (0x31, False), "|": (0x31, True),
        ";": (0x33, False), ":": (0x33, True),
        "'": (0x34, False), '"': (0x34, True),
        "`": (0x35, False), "~": (0x35, True),
        ",": (0x36, False), "<": (0x36, True),
        ".": (0x37, False), ">": (0x37, True),
        "/": (0x38, False), "?": (0x38, True),
        " ": (0x2C, False), "\t": (0x2B, False), "\n": (0x28, False),
    })
    return m


# Printable-ASCII -> (usage, shift) lookup, for text_to_events.
CHAR_MAP = _build_char_map()


def encode_events(events) -> bytes:
    """
    events: list of dicts, each one of:
      {"type":"key",      "keycode":N, "down":bool, "next_delay":ms}
      {"type":"mouse",    "button":1..5, "down":bool, "next_delay":ms}
      {"type":"consumer", "code":N,    "down":bool, "next_delay":ms}
      {"type":"delay",    "ms":N}   (pure pause)
    Returns the flat 3-bytes-per-event wire blob.
    """
    out = bytearray()
    for ev in events:
        t = ev["type"]
        if t == "delay":
            ms = min(4095, ev.get("ms", 0))
            out += bytes([((ms >> 8) & 0x0F) | 0x30, ms & 0xFF, 0])
            continue
        nd = min(4095, ev.get("next_delay", 0))
        up = 0x80 if not ev.get("down", True) else 0x00
        if t == "mouse":
            tc, code = 0x10, MOUSE_BITS.get(ev["button"], 0x01)
        elif t == "consumer":
            tc, code = 0x20, ev.get("code", 0)
        else:  # key
            tc, code = 0x30, ev["keycode"]
        out += bytes([((nd >> 8) & 0x0F) | tc | up, nd & 0xFF, code & 0xFF])
    return bytes(out)


def text_to_events(text: str, key_delay: int = 10) -> list:
    """
    Turn a literal string into press/release key events (US layout).

    Handles the full printable-ASCII set: lowercase a-z/0-9 produce a plain
    down/up pair; uppercase and shifted symbols are wrapped in Left-Shift
    down/up (Shift v, key v, key ^, Shift ^). Unknown chars are skipped.
    (Real recorded macros carry their own per-event timing; this is the quick
    type-a-string helper -- every event gets the same flat `key_delay`.)
    """
    evs = []
    for ch in text:
        entry = CHAR_MAP.get(ch) or CHAR_MAP.get(ch.lower())
        if entry is None:
            continue
        usage, shift = entry
        if shift:
            evs.append({"type": "key", "keycode": KEY_LSHIFT, "down": True, "next_delay": key_delay})
            evs.append({"type": "key", "keycode": usage, "down": True, "next_delay": key_delay})
            evs.append({"type": "key", "keycode": usage, "down": False, "next_delay": key_delay})
            evs.append({"type": "key", "keycode": KEY_LSHIFT, "down": False, "next_delay": key_delay})
        else:
            evs.append({"type": "key", "keycode": usage, "down": True, "next_delay": key_delay})
            evs.append({"type": "key", "keycode": usage, "down": False, "next_delay": key_delay})
    return evs


def build_chunks(macro_slot: int, events) -> list:
    """
    Return a list of (subcmd, data_bytes) tuples for the DATA phase, where
    data_bytes = [lengthByte, macroSlot, <=25 event bytes]. The caller sends
    each as class 0x10 with the given subcmd, MACRO_CHUNK_DELAY apart.
    """
    blob = encode_events(events)
    if not blob:
        return []
    chunk_count = max(1, (len(blob) + 24) // 25)
    chunks = []
    for idx in range(chunk_count):
        piece = blob[idx * 25:(idx + 1) * 25]
        subcmd = ((idx << 4) & 0xF0) | (chunk_count & 0x0F)
        data = bytearray()
        data.append((1 + len(piece)) & 0xFF)   # length byte
        data.append(macro_slot & 0xFF)         # macro slot
        data += piece
        chunks.append((subcmd, bytes(data)))
    return chunks
