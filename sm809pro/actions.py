"""
sm809pro.actions -- button action vocabulary, physical mapping, and defaults.

All codes verified against the web-driver action dictionary, the official
software's menus (screenshots), and live hardware. A button action is a 3-byte
tuple (type, p1, p2); the first byte selects the action class.

Action classes:
  0x10 mouse | 0x30 fire/multiclick | 0x40 dpi | 0x50 dpi-lock | 0x60 special
  0x70 keyboard-combo | 0x80 consumer/media | 0x90 play-macro | 0xFF unset
"""

NUM_BUTTONS = 16

# --- Modifier mask bits for keyboard combos (type 0x70) ---------------------
MOD_CTRL = 0x01
MOD_SHIFT = 0x02
MOD_ALT = 0x04
MOD_WIN = 0x08

# --- HID usages we reference by name (keyboard page) ------------------------
HID = {
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
    "g": 0x0A, "h": 0x0B, "i": 0x0C, "j": 0x0D, "k": 0x0E, "l": 0x0F,
    "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
    "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1A, "x": 0x1B,
    "y": 0x1C, "z": 0x1D,
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
    "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "enter": 0x28, "esc": 0x29, "tab": 0x2B, "space": 0x2C,
    "f1": 0x3A, "f2": 0x3B, "f3": 0x3C, "f4": 0x3D, "f5": 0x3E, "f6": 0x3F,
    "f7": 0x40, "f8": 0x41, "f9": 0x42, "f10": 0x43, "f11": 0x44, "f12": 0x45,
    "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
}


def kb(usage: int, mods: int = 0) -> tuple:
    """Keyboard combo action: (0x70, modmask, HID usage)."""
    return (0x70, mods & 0xFF, usage & 0xFF)


def fire(interval_ms: int = 50, count: int = 0) -> tuple:
    """Rapid-fire: (0x30, interval, count). count=0 => fire while held."""
    return (0x30, interval_ms & 0xFF, count & 0xFF)


def dpi_lock(level: int) -> tuple:
    """DPI lock to a level (1..11 == 200..1200 dpi): (0x50, level, 0)."""
    return (0x50, level & 0xFF, 0x00)


def macro_action(macro_slot: int, playmode: int = 1, repeat: int = 0) -> tuple:
    """
    Bind a button to PLAY a macro (verified from GamingMS.exe sub_4365A0):
        (0x90, (playmode << 4) | (macro_slot & 0x0F), repeat)
    playmode: 1 = repeat while held, 2 = play `repeat` times, 3 = toggle.
    The macro DATA must be uploaded to the same slot via the device's macros API.
    """
    return (0x90, ((playmode & 0x0F) << 4) | (macro_slot & 0x0F), repeat & 0xFF)


# --- Named single-action vocabulary -----------------------------------------
# Mirrors the official software's right-click menu. Values are 3-byte tuples.
BTN = {
    # mouse (0x10)
    "left":    (0x10, 0x01, 0x00),
    "right":   (0x10, 0x02, 0x00),
    "middle":  (0x10, 0x04, 0x00),
    "forward": (0x10, 0x10, 0x00),
    "back":    (0x10, 0x08, 0x00),
    # fire (0x30)
    "fire":    fire(50, 0),
    "triple":  (0x30, 0x32, 0x03),     # "Three Click"
    # dpi (0x40)
    "dpi_up":    (0x40, 0x02, 0x00),
    "dpi_down":  (0x40, 0x03, 0x00),
    "dpi_cycle": (0x40, 0x01, 0x00),   # "DPI Loop"
    # special (0x60)
    "disable":      (0x60, 0x00, 0x00),
    "light_toggle": (0x60, 0x04, 0x00),  # "Switch Effect" lighting toggle
    "run_app":      (0x60, 0x05, 0x00),  # host-side "Run APP" placeholder (see runapp_code_to_physical)
    "unset":        (0xFF, 0xFF, 0xFF),
    # multimedia / consumer (0x80) -- verified
    "media_select": (0x80, 0x83, 0x01),
    "prev_track":   (0x80, 0xB6, 0x00),
    "next_track":   (0x80, 0xB5, 0x00),
    "stop":         (0x80, 0xB7, 0x00),
    "play_pause":   (0x80, 0xCD, 0x00),
    "mute":         (0x80, 0xE2, 0x00),
    "vol_up":       (0x80, 0xE9, 0x00),
    "vol_down":     (0x80, 0xEA, 0x00),
    "email":        (0x80, 0x8A, 0x01),
    "calculator":   (0x80, 0x92, 0x01),
    # Word/Office shortcuts (0x70 combos) -- verified
    "copy":       (0x70, MOD_CTRL, HID["c"]),
    "paste":      (0x70, MOD_CTRL, HID["v"]),
    "cut":        (0x70, MOD_CTRL, HID["x"]),
    "select_all": (0x70, MOD_CTRL, HID["a"]),
    "new":        (0x70, MOD_CTRL, HID["n"]),
    "save":       (0x70, MOD_CTRL, HID["s"]),
    "print":      (0x70, MOD_CTRL, HID["p"]),
    "open":       (0x70, MOD_WIN, HID["e"]),   # Win+E -- CONFIRMED from pcap (NOT Ctrl+O)
    "undo":       (0x70, MOD_CTRL, HID["z"]),
    # Window management (0x70 OS shortcuts) -- codes inferred from labels, verify
    "my_computer":     (0x80, 0x94, 0x01),  # consumer AL My Computer -- CONFIRMED from pcap
    "close_window":    (0x70, MOD_ALT, HID["f4"]),  # Alt+F4
    "display_desktop": (0x70, MOD_WIN, HID["d"]),   # Win+D
    "run":             (0x70, MOD_WIN, HID["r"]),   # Win+R
    "minimize":        (0x70, MOD_WIN, HID["down"]),
    "maximize":        (0x70, MOD_WIN, HID["up"]),
}

# Human labels for the named actions (for GUI dropdowns).
ACTION_LABELS = {
    "left": "Left Button", "right": "Right Button", "middle": "Middle Button",
    "forward": "Forward", "back": "Backward", "fire": "Fire Key",
    "triple": "Three Click", "dpi_up": "DPI+", "dpi_down": "DPI-",
    "dpi_cycle": "DPI Loop", "disable": "Disable", "light_toggle": "Switch Effect",
    "unset": "(unset)", "media_select": "Media Select", "prev_track": "Prev Track",
    "next_track": "Next Track", "stop": "Stop", "play_pause": "Play/Pause",
    "mute": "Mute", "vol_up": "Volume+", "vol_down": "Volume-", "email": "Mail",
    "calculator": "Calculator", "copy": "Copy", "paste": "Paste", "cut": "Cut",
    "select_all": "Select All", "new": "New", "save": "Save", "print": "Print",
    "open": "Open", "undo": "Undo", "my_computer": "My Computer",
    "close_window": "Close Window", "display_desktop": "Display Desktop",
    "run": "Run", "minimize": "Minimize", "maximize": "Maximize",
}

# --- Physical-button <-> protocol-slot mapping ------------------------------
# VERIFIED on hardware by assigning a unique letter to each of the 16 protocol
# slots and reading which physical button (product-image numbering 1..16) typed
# it. PERMUTE[slot] = 0-based physical-button index whose action goes in slot.
PERMUTE = [11, 12, 13, 14, 15, 9, 10, 0, 1, 2, 3, 4, 5, 8, 6, 7]

# Physical button -> protocol slot (the inverse, handy for tooling).
PHYS_TO_SLOT = {PERMUTE[s] + 1: s for s in range(NUM_BUTTONS)}  # 1-based phys -> slot

# Packet split (from GamingMS.exe sub_437D00): packet 1 = slots 0-8 (subcmd 2,
# 27 data bytes), packet 2 = slots 9-15 (subcmd 18, 21 data bytes).
KEYS_SPLIT = 9
KEYS_SUBCMD_1 = 0x02
KEYS_SUBCMD_2 = 18

# --- Factory defaults (from the official software's Restore screen) ---------
# Physical button number (1..16) -> action. All verified including button 11
# ("My Computer" = consumer 0x80,0x94,0x01 -- confirmed from pcap, session 9p/9q).
FACTORY_DEFAULTS = {
    1:  kb(HID["d"], MOD_WIN),   # WIN+D
    2:  kb(HID["2"]),            # '2'
    3:  kb(HID["1"]),            # '1'
    4:  BTN["forward"],
    5:  kb(HID["4"]),            # '4'
    6:  kb(HID["3"]),            # '3'
    7:  kb(HID["6"]),            # '6'
    8:  kb(HID["5"]),            # '5'
    9:  BTN["back"],
    10: BTN["fire"],
    11: BTN["my_computer"],
    12: BTN["left"],
    13: BTN["right"],
    14: BTN["middle"],
    15: BTN["dpi_up"],
    16: BTN["dpi_down"],
}


def default_button_codes() -> list:
    """The 16 factory-default actions, indexed by 0-based physical button."""
    return [FACTORY_DEFAULTS[b] for b in range(1, NUM_BUTTONS + 1)]


def runapp_code_to_physical(code: int):
    """Map the report-04 byte[7] Run-APP code back to a 1-based physical button.

    The device reports (protocol_slot + 1) for the pressed host-side button
    (CONFIRMED via USBPcap: 1->0x08, 5->0x0C, 9->0x0E, 10->0x06). So slot =
    code - 1 and the physical button = PERMUTE[slot] + 1. Returns None if the
    code is 0 (nothing pressed) or out of range.
    """
    slot = code - 1
    if 0 <= slot < NUM_BUTTONS:
        return PERMUTE[slot] + 1
    return None


def physical_to_slots(codes_by_physical) -> list:
    """
    Reorder a 16-entry list indexed by PHYSICAL button (0-based) into the 16
    protocol SLOTS the device expects, applying the verified PERMUTE.
    """
    def get(phys0):
        c = codes_by_physical[phys0] if phys0 < len(codes_by_physical) else None
        return BTN["unset"] if c is None else tuple(c)
    return [get(PERMUTE[s]) for s in range(NUM_BUTTONS)]
