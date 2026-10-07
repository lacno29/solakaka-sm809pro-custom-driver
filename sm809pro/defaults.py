"""
sm809pro.defaults -- the factory-default device profile.

These are the values the official software's "Restore" writes to the SELECTED
profile (it does NOT clear uploaded macros). Confirmed from the official app +
web driver on this unit (see CLAUDE.md / journal.txt session 9c). Used by the
app's "Reset to Factory" (which re-pushes all of these but leaves macros) and to
seed the Lighting / Performance panels.

If your unit differs (DPI presets vary by batch/firmware), this is the one place
to change them.
"""

from . import actions as A

# --- DPI --------------------------------------------------------------------
# 6 stages enabled (device supports 8). Confirmed values + active stage.
DPI_VALUES = [1200, 1600, 2400, 3200, 6400, 16000]
DPI_ENABLED_COUNT = 6
DPI_SELECTED = 1                 # 0-based; stage 2 (1600) is active by default
DPI_MAX = 24000                  # hardware max (slider ceiling)

# Per-stage LED colors (RGB). Confirmed pure R/B/G/Y/C/M for stages 1-6.
DPI_COLORS = [
    (255, 0, 0),    # 1 red
    (0, 0, 255),    # 2 blue
    (0, 255, 0),    # 3 green
    (255, 255, 0),  # 4 yellow
    (0, 255, 255),  # 5 cyan
    (255, 0, 255),  # 6 magenta
    (255, 255, 255),  # 7 (unused by default) white
    (255, 255, 255),  # 8 (unused by default) white
]

# --- Polling / LOD ----------------------------------------------------------
POLLING_HZ = 500                 # web driver default (NOT 1000)
LOD_MM = 2                       # 2mm default

# --- Lighting ---------------------------------------------------------------
# Default mode = Colorful Streaming (mode 2), confirmed.
LIGHTING_MODE = 2
# IMPORTANT (hardware finding, session 9d): brightness/speed/direction are NOT
# exposed by the official app OR the web driver, AND on THIS unit's current
# firmware sweeping these packet bytes produced NO OBSERVABLE EFFECT (verified
# with lighting_lab.py: swept bri 1-4, spd 1-3, dir 0/1 -> no visible change).
# They may be reserved for a future firmware. We keep the packet fields (the
# byte layout is correct) but treat these as inert. Do NOT surface
# brightness/speed/direction in the Lighting UI unless a firmware update makes
# them work. Color likewise only matters for single-color modes 8-10.
LIGHTING_BRIGHTNESS = 4          # 1-4 (no observable effect on current firmware)
LIGHTING_SPEED = 3               # 1-3 (no observable effect on current firmware)
LIGHTING_DIRECTION = 0           # 0/1 (no observable effect on current firmware)
LIGHTING_COLOR = (0, 0, 255)     # only used for modes 8-10

# --- Power management --------------------------------------------------------
POWER_SLEEP_MIN = 20             # power-down time (minutes)
POWER_MOVE_WAKEUP = True         # "Keep motion wake up" = ON
POWER_MOVE_LIGHTING = True       # "lighting off while mouse move" = ON (checked)

# --- Sensor flags ------------------------------------------------------------
SENSOR_ANGLE_SNAP = False        # OFF
SENSOR_MOTION_SYNC = True        # ON
SENSOR_RIPPLE = False            # OFF


def button_codes():
    """The factory-default 16-button code list (0-based physical index)."""
    return A.default_button_codes()


def apply_all(dev, include_buttons=True, include_macros_clear=False):
    """
    Push every factory default to the device, matching the official Restore.

    Does NOT clear macros by default (the official Restore preserves them).
    Set include_macros_clear=True only if you explicitly want a full wipe.

    Returns True if every command reported a clean write.
    """
    ok = True
    # DPI values + colors + selected stage
    ok &= dev.set_dpi(DPI_VALUES[:DPI_ENABLED_COUNT],
                      selected=DPI_SELECTED,
                      colors=DPI_COLORS[:DPI_ENABLED_COUNT])
    # polling + LOD
    ok &= dev.set_polling_rate(POLLING_HZ)
    ok &= dev.set_lod(LOD_MM)
    # lighting
    ok &= dev.set_lighting(LIGHTING_MODE, brightness=LIGHTING_BRIGHTNESS,
                           speed=LIGHTING_SPEED, direction=LIGHTING_DIRECTION,
                           color=LIGHTING_COLOR)
    # power + sensor
    ok &= dev.set_power(sleep_time=POWER_SLEEP_MIN, move_wakeup=POWER_MOVE_WAKEUP,
                        move_lighting=POWER_MOVE_LIGHTING)
    ok &= dev.set_sensor_flags(angle_snap=SENSOR_ANGLE_SNAP,
                               motion_sync=SENSOR_MOTION_SYNC,
                               ripple=SENSOR_RIPPLE)
    # buttons last (so a failure here is easy to spot)
    if include_buttons:
        ok &= dev.set_keys_default()
    if include_macros_clear:
        ok &= dev.erase_macros()
    return ok
