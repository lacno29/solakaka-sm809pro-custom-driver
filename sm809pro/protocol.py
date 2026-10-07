"""
sm809pro.protocol -- low-level wire protocol constants and helpers.

Everything here is CONFIRMED against the web driver, the official GamingMS.exe
(IDA), and live hardware. No device I/O lives in this module; it is pure data +
the packet builder, so it is trivially testable and portable.
"""

# --- Identity ---------------------------------------------------------------
VID = 0x04F3                 # Elan
PID_WIRELESS = 0x026F        # 2.4GHz dongle
PID_WIRED = 0x026E           # USB wired
# (anything else on this VID = Bluetooth)

# --- Report IDs / framing ---------------------------------------------------
REPORT_ID_CMD = 0x06          # SetFeature (write) + GetFeature (ACK/idle poll)
REPORT_ID_STATUS_FEAT = 0x05  # pulled status / version string
REPORT_ID_STATUS_PUSH = 0x04  # device-pushed input report (DPI/heartbeat)
PACKET_LEN = 31               # on-wire payload length AFTER checksum insert
CHECKSUM_SEED = 6             # checksum running seed

# Timing (matches the official software's Sleep() values)
CMD_DELAY = 0.060             # 60ms settle after a SetFeature
RETRY_DELAY = 0.060
MAX_RETRIES = 3
MACRO_CHUNK_DELAY = 0.120     # 120ms between macro data chunks

# --- Command classes (first payload byte) -----------------------------------
CMD_KEYS         = 0x01
CMD_DPI_VALUES   = 0x02
CMD_DPI_COLORS   = 0x03
CMD_POLLING      = 0x04
CMD_LOD          = 0x05
CMD_LIGHTING     = 0x06
CMD_POWER        = 0x07
CMD_SENSOR_FLAGS = 0x08
CMD_RESET        = 0x0F
CMD_MACRO_DATA   = 0x10
CMD_MACRO_CLEAR  = 0x11

# DPI config is sent as a PAIR of class-0x02 packets, differing only in the
# subcommand byte (CONFIRMED by USB capture of the official app cycling DPI
# stages, session 9j). BOTH must be sent or the device does not commit the
# active-stage (`selected`) change -- this is why a single sub=0x02 write
# reflected in config but never switched the physical DPI. Same two-packet
# pattern as the keys (sub 0x02 + 0x12).
DPI_SUBCMD_1 = 0x02
DPI_SUBCMD_2 = 0x12

CMD_NAMES = {
    CMD_KEYS: "KEYS", CMD_DPI_VALUES: "DPI_VALUES", CMD_DPI_COLORS: "DPI_COLORS",
    CMD_POLLING: "POLLING", CMD_LOD: "LOD", CMD_LIGHTING: "LIGHTING",
    CMD_POWER: "POWER", CMD_SENSOR_FLAGS: "SENSOR_FLAGS",
    CMD_RESET: "RESET", CMD_MACRO_DATA: "MACRO_DATA", CMD_MACRO_CLEAR: "MACRO_CLEAR",
}

# --- Enums ------------------------------------------------------------------
# Polling rate (Hz) -> wire byte. 2000/4000/8000 only if maxReportRate allows.
POLLING_ENUM = {125: 8, 250: 4, 500: 2, 1000: 1, 2000: 17, 4000: 18, 8000: 20}
POLLING_REVERSE = {v: k for k, v in POLLING_ENUM.items()}

# Lighting modes (index -> human label). Single-color modes: 8/9/10.
LIGHTING_MODES = {
    0: "Off", 1: "Stars Twinkle", 2: "Colorful Streaming", 3: "Seven-color Stretch",
    4: "Seven-color Flash", 5: "Colorful Breath", 6: "Seven-color Explosion",
    7: "Colorful Coverage", 8: "Red", 9: "Green", 10: "Blue",
}
# Modes that honor the RGB color argument (the rest cycle/ignore it).
LIGHTING_SINGLE_COLOR_MODES = {8, 9, 10}

# Sensor DPI divisor: most sensors use floor(dpi/100)-1; a couple use /50.
DPI_DIV50_SENSORS = {149, 80}
DEFAULT_SENSOR = 0x11  # PAW3311 on this unit

SENSOR_NAMES = {
    0x06: "S205", 0x09: "PAW3809", 0x11: "PAW3311", 0x12: "PAW3212",
    0x20: "PAW3220", 0x50: "PAW3950", 0x70: "OM70", 0x95: "PAW3395",
}

# Input report 4 (device->host push) field offsets, INCLUDING report-id byte 0.
# [0]=reportID(0x04) [1]=linkStatus [2]=currentDpiLevel [3]=reportRate
# [4]=battery% (0..100; confirmed 0x3C=60% matched the official UI) [9]=sensorType.
# Confirmed on hardware by stepping DPI levels and cross-checking the 60% reading.
#
# LINK STATUS (byte 1) is the ONLINE/OFFLINE signal: 1 = mouse online, 0 = mouse
# offline (powered off / out of range). The 2.4GHz dongle KEEPS pushing report 4
# (~every 3s) even when the mouse is off, with link=0 and stale dpi/battery
# echoed -- so detect offline from this byte, NOT from absence of pushes.
#
# NOTE: the PULLED feature report 5 is NOT telemetry -- it returns the ASCII
# firmware version string "1010" + flags. Battery/DPI live state come from THIS
# pushed report 4 on the Col04 interface.
PUSH_OFF_LINK = 1
PUSH_OFF_DPI_LEVEL = 2
PUSH_OFF_RATE = 3
PUSH_OFF_BATTERY = 4
# byte[5] = charging flag (1 = charging, 0 = not). Found via status_probe: it
# read 1 only while the charger was connected; battery (byte[4]) stays a clean
# 0..100 regardless. (Tentative from a small sample; icon-only, safe.)
PUSH_OFF_CHARGING = 5
# byte[7] = the pressed host-side "Run APP" button, encoded as (protocol_slot + 1);
# 0 = none pressed. CONFIRMED via two USBPcap captures (sm809pro_runapp*.pcapng):
# button 1->0x08, 5->0x0C, 9->0x0E, 10->0x06, all == PERMUTE-slot + 1. A Run-APP
# button carries the (0x60,0x05,0x00) placeholder on the device and does nothing
# itself; the host watches this byte and launches the stored exe. Normal keys go
# out as standard HID and never touch byte[7].
PUSH_OFF_RUNAPP = 7
PUSH_OFF_SENSOR = 9


# --- Packet builder ---------------------------------------------------------
def build_packet(cmd: int, seq: int, sub: int, data: bytes = b"", pad: int = 0xFF) -> bytes:
    """
    Build a 31-byte packet.

    1. Assemble a 30-byte pre-checksum buffer: [cmd, seq, sub, *data, pad...].
    2. checksum = (CHECKSUM_SEED + sum(buffer)) & 0xFF.
    3. INSERT the checksum at index 3 (splice) -> 31 bytes.

    On the wire the report ID (0x06) is prepended by the device layer, giving
    [06][cmd][seq][sub][checksum][data...].
    """
    buf = bytearray()
    buf.append(cmd & 0xFF)
    buf.append(seq & 0xFF)
    buf.append(sub & 0xFF)
    buf.extend(data)
    while len(buf) < 30:
        buf.append(pad & 0xFF)
    buf = buf[:30]
    chk = (CHECKSUM_SEED + sum(buf)) & 0xFF
    buf.insert(3, chk)            # -> 31 bytes
    return bytes(buf)


def dpi_to_raw(dpi: int, sensor_type: int = DEFAULT_SENSOR) -> int:
    """Encode a DPI value to its 16-bit raw wire value: floor(dpi/div) - 1."""
    div = 50 if sensor_type in DPI_DIV50_SENSORS else 100
    return ((dpi // div) - 1) & 0xFFFF


def raw_to_dpi(raw: int, sensor_type: int = DEFAULT_SENSOR) -> int:
    """Inverse of dpi_to_raw (for reading values back / .psf import)."""
    div = 50 if sensor_type in DPI_DIV50_SENSORS else 100
    return (raw + 1) * div


def hexstr(b) -> str:
    return " ".join(f"{x:02X}" for x in b)
