"""
Offline test of the consolidated sm809pro package -- NO hardware needed.

Patches SM809Pro._send_packet to capture the bytes that WOULD go on the wire,
then checks them against the values verified during reverse-engineering.

Run:  python -m tests.test_offline   (from the project root)
   or: python tests/test_offline.py
"""
import os
import sys

# allow running directly (python tests/test_offline.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sm809pro import SM809Pro, protocol as P, actions as A, macros as M

captured = []


def patch(dev):
    def cap(packet):
        captured.append(bytes(packet))
        return True
    dev._send_packet = cap


def fresh():
    captured.clear()
    d = SM809Pro.__new__(SM809Pro)
    d.sensor = P.DEFAULT_SENSOR
    d._seq = 1
    import threading
    d._lock = threading.RLock()
    d._dev = object()
    patch(d)
    return d


def hx(b):
    return " ".join(f"{x:02X}" for x in b)


passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


print("== checksum / packet builder ==")
pkt = P.build_packet(P.CMD_LIGHTING, 1, 0x01, bytes([0xFF, 8, 0x43, 0, 255, 0, 0]))
check("packet length 31", len(pkt) == 31)
# checksum at index 3 = (6 + sum(30-byte buf)) & 0xFF
buf = bytearray([P.CMD_LIGHTING, 1, 0x01, 0xFF, 8, 0x43, 0, 255, 0, 0])
while len(buf) < 30:
    buf.append(0xFF)
expect_chk = (P.CHECKSUM_SEED + sum(buf)) & 0xFF
check("checksum spliced at index 3", pkt[3] == expect_chk)

print("== DPI encoding ==")
check("dpi_to_raw(1200)=11 (PAW3311 /100)", P.dpi_to_raw(1200) == 11)
check("dpi_to_raw(16000)=159", P.dpi_to_raw(16000) == 159)
check("raw_to_dpi inverse", P.raw_to_dpi(P.dpi_to_raw(2400)) == 2400)

print("== polling enum ==")
check("500Hz -> 2", P.POLLING_ENUM[500] == 2)
check("1000Hz -> 1", P.POLLING_ENUM[1000] == 1)

print("== keys: factory defaults land on correct physical buttons ==")
d = fresh()
d.set_keys_default()
check("two key packets sent", len(captured) == 2)
p1, p2 = captured[0], captured[1]
check("packet1 subcmd 0x02", p1[2] == 0x02)
check("packet2 subcmd 18", p2[2] == 18)
# reconstruct slots, then verify a few physical buttons via PERMUTE
slots = []
for i in range(9):
    slots.append(tuple(p1[4 + i * 3:7 + i * 3]))
for i in range(7):
    slots.append(tuple(p2[4 + i * 3:7 + i * 3]))
def action_on_physical(phys1):
    slot = A.PERMUTE.index(phys1 - 1)
    return slots[slot]
check("button 12 = Left (10 01 00)", action_on_physical(12) == (0x10, 0x01, 0x00))
check("button 13 = Right (10 02 00)", action_on_physical(13) == (0x10, 0x02, 0x00))
check("button 1 = WIN+D (70 08 07)", action_on_physical(1) == (0x70, 0x08, 0x07))
check("button 10 = Fire (30 32 00)", action_on_physical(10) == (0x30, 0x32, 0x00))
check("button 15 = DPI+ (40 02 00)", action_on_physical(15) == (0x40, 0x02, 0x00))
check("button 16 = DPI- (40 03 00)", action_on_physical(16) == (0x40, 0x03, 0x00))

print("== keys: partial remap preserves left-click ==")
d = fresh()
codes = A.default_button_codes()
codes[0] = A.kb(A.HID["g"])   # button 1 -> 'g'
d.set_keys(codes)
slots = []
for i in range(9):
    slots.append(tuple(captured[0][4 + i * 3:7 + i * 3]))
for i in range(7):
    slots.append(tuple(captured[1][4 + i * 3:7 + i * 3]))
check("button 12 still Left", slots[A.PERMUTE.index(11)] == (0x10, 0x01, 0x00))
check("button 1 now 'g'", slots[A.PERMUTE.index(0)] == (0x70, 0x00, 0x0A))

print("== macros: encoding + chunk framing ==")
d = fresh()
evs = M.text_to_events("hi")
d.upload_macro(1, evs)
# captured[0] = CLEAR, captured[1] = first DATA chunk
clr = captured[0]
data = captured[1]
check("CLEAR class 0x11 sub 0x01 first-data 0xFF", clr[0] == 0x11 and clr[2] == 0x01 and clr[4] == 0xFF)
check("DATA class 0x10", data[0] == 0x10)
check("DATA subcmd = chunkIdx<<4|count (0x01)", data[2] == 0x01)
check("DATA length byte = 1+12 = 13", data[4] == 13)
check("DATA macro slot = 1", data[5] == 1)
# events: 'h' down(30 0A 0B) up(B0 0A 0B), 'i' down(30 0A 0C) up(B0 0A 0C)
ev = tuple(data[6:18])
check("event bytes h/i press+release w/ 0x80 up-flag",
      ev == (0x30, 0x0A, 0x0B, 0xB0, 0x0A, 0x0B, 0x30, 0x0A, 0x0C, 0xB0, 0x0A, 0x0C))

print("== macro_action binding code ==")
ma = A.macro_action(1, playmode=1)
check("macro_action(1) = (0x90,0x11,0x00)", ma == (0x90, 0x11, 0x00))
ma2 = A.macro_action(6, playmode=2, repeat=5)
check("macro_action(6,2,5) = (0x90,0x26,0x05)", ma2 == (0x90, 0x26, 0x05))

print("== macros: batch upload (one CLEAR, then per-slot DATA) ==")
d = fresh()
d.upload_macros({1: M.text_to_events("h"), 3: M.text_to_events("i")})
check("batch CLEAR sent first (0x11, data 0xFF)",
      captured[0][0] == 0x11 and captured[0][2] == 0x01 and captured[0][4] == 0xFF)
_data_pkts = [p for p in captured[1:] if p[0] == 0x10]
check("batch has 2 DATA chunks (one per non-empty slot)", len(_data_pkts) == 2)
check("first DATA targets slot 1", _data_pkts[0][5] == 1)
check("second DATA targets slot 3", _data_pkts[1][5] == 3)
check("empty macros set => CLEAR only",
      (lambda dd: (dd.upload_macros({2: []}), len([p for p in captured if p[0] == 0x10]) == 0)[1])(fresh()))

print("== macros: text_to_events shift handling ==")
_a = M.text_to_events("A")
_codes = [(e["type"], e["keycode"], e["down"]) for e in _a]
check("uppercase 'A' expands to a 4-event shift tap", len(_a) == 4)
check("A: Left-Shift down first (0xE1)", _codes[0] == ("key", 0xE1, True))
check("A: 'a' usage 0x04 down", _codes[1] == ("key", 0x04, True))
check("A: 'a' up then Shift up", _codes[2] == ("key", 0x04, False) and _codes[3] == ("key", 0xE1, False))
check("symbol '!' = shift+1 (usage 0x1E)",
      [(e["keycode"], e["down"]) for e in M.text_to_events("!")]
      == [(0xE1, True), (0x1E, True), (0x1E, False), (0xE1, False)])
check("lowercase 'hi' unchanged (no shift events)",
      len(M.text_to_events("hi")) == 4
      and all(e["keycode"] != 0xE1 for e in M.text_to_events("hi")))

print("== mode selection & Bluetooth priority ==")
from sm809pro.device import choose_mode

check("empty modes returns None", choose_mode([]) is None)

m_wl = {"connection": "2.4GHz", "pid": 0x026F, "configurable": True, "devs": []}
m_wired = {"connection": "wired", "pid": 0x026E, "configurable": True, "devs": []}
m_bt_cfg = {"connection": "bluetooth", "pid": 0x0270, "configurable": True, "devs": []}
m_bt_ro = {"connection": "bluetooth", "pid": 0x0270, "configurable": False, "devs": []}

check("only 2.4GHz -> picks 2.4GHz", choose_mode([m_wl]) == m_wl)
check("only wired -> picks wired", choose_mode([m_wired]) == m_wired)
check("only bluetooth (cfg) -> picks bluetooth", choose_mode([m_bt_cfg]) == m_bt_cfg)
check("only bluetooth (read-only) -> picks bluetooth fallback", choose_mode([m_bt_ro]) == m_bt_ro)

# When 2.4GHz dongle is plugged in, but mouse is active on Bluetooth:
check("2.4GHz + Bluetooth -> prefers active Bluetooth",
      choose_mode([m_wl, m_bt_cfg])["connection"] == "bluetooth")
check("2.4GHz + Bluetooth (read-only) -> prefers active Bluetooth over idle dongle",
      choose_mode([m_wl, m_bt_ro])["connection"] == "bluetooth")

# When wired USB is plugged in, wired always takes top priority:
check("wired + Bluetooth + 2.4GHz -> prefers wired",
      choose_mode([m_wl, m_bt_cfg, m_wired])["connection"] == "wired")

print("== keepalive_poll health detection ==")
d = fresh()
class DummyDev:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
    def get_feature_report(self, r_id, length):
        if self.should_fail:
            raise OSError("device disconnected")
        return bytes([r_id] + [0] * (length - 1))

d._dev = DummyDev(should_fail=False)
check("keepalive_poll returns True on healthy handle", d.keepalive_poll() is True)

d._dev = DummyDev(should_fail=True)
check("keepalive_poll returns False on dead/disconnected handle", d.keepalive_poll() is False)

d._dev = None
check("keepalive_poll returns False when device is closed", d.keepalive_poll() is False)

d = fresh()
d.configurable = False
check("_send_packet returns False safely when not configurable", SM809Pro._send_packet(d, b"test") is False)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

