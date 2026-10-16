"""
tests/test_gui_headless.py -- offscreen GUI smoke test (no HID, no real config).

Builds the full MainWindow (DeviceController neutralized) to catch import/wiring/
QSS errors, then exercises the named-library macro model + the macro-binding
slot resolution. Uses a temp MacroStore so it never touches the real
%APPDATA%/SM809Pro/macros.json. Run:  python tests/test_gui_headless.py
"""
import os
import sys
import io
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

# Neutralize hardware access BEFORE building the window.
from app import controller as _C
_C.DeviceController.start = lambda self: None

# Isolate the profile store to a temp file so building MainWindow never writes
# the real config/profiles.json (load() seeds + saves a Default on first run).
from app import profile_store as _PS
_ps_fd, _ps_path = tempfile.mkstemp(suffix=".json")
os.close(_ps_fd)
os.unlink(_ps_path)
_PS.default_path = lambda: _ps_path

app = QApplication.instance() or QApplication([])

fails = 0


def check(name, cond):
    global fails
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        fails += 1


def tmp_store():
    from app.macro_store import MacroStore
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)            # start empty
    return MacroStore(path)


# 1) full window builds and the macro panel is wired into the stack
from app.main_window import MainWindow
from app.widgets.action_picker import describe_action
from sm809pro import actions as A

w = MainWindow()
check("MainWindow builds", w is not None)
check("nav has 7 items", w.nav.count() == 7)
check("macro panel at stack index 1", w.stack.widget(1) is w.macro_panel)
check("apply/resolve handlers exist",
      hasattr(w, "_apply_buttons") and hasattr(w, "_resolve_bindings"))

# 2) named-library macro model (isolated temp store)
from app.panels.macro_panel import MacroPanel

store = tmp_store()
mp = MacroPanel(store)
check("editor disabled with no macro", mp.editor.isEnabled() is False)

mp.new_macro()
check("new_macro -> 1 in store", len(store.all()) == 1)
check("editor enabled after new", mp.editor.isEnabled() is True)
check("new macro has no slot field", not hasattr(mp, "slot_combo"))

mp.add_text_events("hi", 20)                 # nothing selected -> appended
check("typed 'hi' -> 4 key events", len(mp._cur()["events"]) == 4)

# select event row 0, then Insert a Ctrl tap -> must land AFTER row 0 (at idx 1,2)
mp.events_table.selectRow(0)
mp.insert_event("key", 0x04, mode="tap", delay=50)
evs = mp._cur()["events"]
check("insert-after-selected -> 6 events", len(evs) == 6)
check("inserted tap is at index 1/2 (down,up)",
      evs[1]["type"] == "key" and evs[1]["down"] is True and evs[2]["down"] is False)

# events persist to the store and round-trip through the wire encoder
from sm809pro import macros as M
blob = M.encode_events(store.get(mp._cur_id)["events"])
check("events encode 3 bytes each", len(blob) == 3 * len(evs))

# table-row inline editing handlers (web-driver-style)
evd = mp._cur()["events"][1]            # the inserted tap's Down event
mp._on_row_type(evd, "Up")
check("row flip down->up (in place)", evd["down"] is False and evd["type"] == "key")
mp._on_row_type(evd, "Delay")
check("row type ->Delay converts", mp._cur()["events"][1]["type"] == "delay")
mp._on_row_type(mp._cur()["events"][1], "Down")
check("row Delay->Down -> key event", mp._cur()["events"][1]["type"] == "key")

# rename writes through to the store
mp.name_edit.setText("Combo")
check("rename persists to store", store.get(mp._cur_id)["name"] == "Combo")

# 3) macro-binding slot resolution on the MainWindow (swap in a temp store)
w.store = store                              # resolver reads self.store dynamically
mid = mp._cur_id
binding = {"macro": mid, "playmode": 1, "repeat": 0}
codes, macros = w._resolve_bindings([binding] + [A.BTN["unset"]] * 15)
check("bound macro -> slot 1 upload", set(macros.keys()) == {1})
check("macro button code is 0x90/slot1/hold", tuple(codes[0]) == tuple(A.macro_action(1, 1, 0)))
check("uploaded events match the macro", macros[1] == store.get(mid)["events"])
check("describe renders 'Macro: Combo (hold)'",
      describe_action(binding) == "Macro: Combo (hold)")

# unknown macro id resolves to unset (no crash, no slot)
codes2, macros2 = w._resolve_bindings([{"macro": "deadbeef"}] + [A.BTN["unset"]] * 15)
check("dangling macro -> unset", tuple(codes2[0]) == tuple(A.BTN["unset"]) and macros2 == {})

# two distinct bound macros -> slots 0 and 1
m2 = store.add("Second")
store.set_events(m2["id"], [{"type": "key", "keycode": 0x05, "down": True, "next_delay": 0}])
b3 = [binding, {"macro": m2["id"], "playmode": 2, "repeat": 3}] + [A.BTN["unset"]] * 14
codes3, macros3 = w._resolve_bindings(b3)
check("two macros -> slots {1,2}", set(macros3.keys()) == {1, 2})
check("second is play-N (repeat 3)", tuple(codes3[1]) == tuple(A.macro_action(2, 2, 3)))

# config path is the portable local ./config/ dir, not %APPDATA%
from app.macro_store import default_path
check("config path is local ./config/",
      default_path().replace(chr(92), "/").endswith("/config/macros.json"))

# deleting a macro that's bound to a button resets that button to its default
mq = store.add("ToDelete")
w.buttons_panel.set_binding(1, {"macro": mq["id"], "playmode": 1, "repeat": 0})
check("button1 is a macro binding", isinstance(w.buttons_panel.bindings()[0], dict))
store.delete(mq["id"])
w._on_library_changed()
check("deleted-macro button reset to default",
      tuple(w.buttons_panel.bindings()[0]) == tuple(A.default_button_codes()[0]))

# 4) profile store: CRUD + persistence (isolated temp path)
from app.profile_store import ProfileStore, default_config

ps = ProfileStore(_ps_path + ".store")
check("store seeds a Default", [p["name"] for p in ps.all()] == ["Default"])
check("default config has all sections",
      sorted(default_config().keys()) ==
      ["buttons", "dpi", "lighting", "lod_mm", "polling_hz", "power", "sensor"])
pa = ps.add("FPS")
pb = ps.duplicate(pa["id"], "FPS copy")
ps.set_active(pb["id"])
ps.rename(pa["id"], "Gaming")
check("add/dup/rename", [p["name"] for p in ps.all()] == ["Default", "Gaming", "FPS copy"])
ps2 = ProfileStore(_ps_path + ".store")     # reload from disk
check("profiles persist across reload", len(ps2.all()) == 3 and ps2.active()["name"] == "FPS copy")
check("duplicate name gets a suffix", ps.add("Gaming")["name"] == "Gaming (1)")
check("second duplicate increments", ps.add("Gaming")["name"] == "Gaming (2)")
ps2.delete(ps2.active_id)
check("delete falls back to a valid active", ps2.active() is not None)
# delete fallback when there's no MRU: previous neighbor in the list
ps3 = ProfileStore(_ps_path + ".del")
a = ps3.add("A"); b = ps3.add("B"); c = ps3.add("C")
idx = ps3.index_of(b["id"]); ps3.delete(b["id"])
rem = ps3.all()
prev = rem[max(0, min(idx - 1, len(rem) - 1))]
check("delete fallback = previous neighbor", prev["name"] == "A")
# predefined sorts + drag reorder (store level)
ps4 = ProfileStore(_ps_path + ".sort")
ps4.add("Zebra"); ps4.add("Apple"); ps4.add("Mango")   # + seeded "Default"
ps4.sort_by("az")
check("sort A-Z", [p["name"] for p in ps4.all()] == ["Apple", "Default", "Mango", "Zebra"])
ps4.sort_by("za")
check("sort Z-A", [p["name"] for p in ps4.all()][0] == "Zebra")
ps4.sort_by("oldest")
check("sort oldest = creation order",
      [p["name"] for p in ps4.all()] == ["Default", "Zebra", "Apple", "Mango"])
ps4.sort_by("latest")
check("sort latest = newest first", [p["name"] for p in ps4.all()][0] == "Mango")
_ids = [p["id"] for p in ps4.all()]
ps4.reorder(list(reversed(_ids)))
check("drag reorder applies", [p["id"] for p in ps4.all()] == list(reversed(_ids)))

# 5) MainWindow profile wiring: live edits fold into the active profile + persist
import app.profile_store as _PS2
_PS2.default_path = lambda: _ps_path + ".mw"
w2 = MainWindow()
check("current config seeded from active profile", w2._current_config is not None)
w2._apply_polling(1000)                      # simulate a Performance-panel edit
check("edit recorded into current config", w2._current_config["polling_hz"] == 1000)
check("edit persisted to active profile",
      w2.profiles.active()["config"]["polling_hz"] == 1000)
# apply_profile seeds panels without re-triggering an auto-apply
before = list(w2.buttons_panel.bindings())
cfg = default_config()
w2.apply_profile(cfg)
check("apply_profile loads buttons silently",
      len(w2.buttons_panel.bindings()) == 16)
w2.ctrl.shutdown()

# 6) .psf import -- verified against the two purpose-built capture files
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_psf1 = os.path.join(_root, "custom1_red.psf")
if os.path.exists(_psf1):
    from app.psf_import import import_psf
    from sm809pro import actions as _A
    imp = import_psf(_psf1)
    cfg = imp["config"]
    # every physical button got its known action: phys 1..11 = A..K, 12/13 =
    # Left/Right, 14/15/16 = M/N/O (HID usages a=0x04..)
    rev = {v: k for k, v in _A.HID.items()}
    btn_letters = []
    for b in cfg["buttons"]:
        if tuple(b) == _A.BTN["left"]:
            btn_letters.append("Left")
        elif tuple(b) == _A.BTN["right"]:
            btn_letters.append("Right")
        elif b[0] == 0x70 and b[1] == 0:
            btn_letters.append(rev.get(b[2], "?").upper())
        else:
            btn_letters.append("?")
    check("psf buttons map to physical layout",
          btn_letters == ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K",
                          "Left", "Right", "M", "N", "O"])
    check("psf DPI values decode", cfg["dpi"]["values"] == [1200, 1600, 2400, 3200, 6400, 16000])
    check("psf DPI selected (0-based) = 3", cfg["dpi"]["selected"] == 3)
    check("psf enabled count = 6", cfg["dpi"]["enabled_count"] == 6)
    check("psf lighting = Red Full (mode 8)", cfg["lighting"]["mode"] == 8)
    check("psf polling = 500", cfg["polling_hz"] == 500)
    check("psf power imported", cfg["power"]["sleep_min"] == 20 and cfg["power"]["move_wakeup"])
    check("psf sensor imported", cfg["sensor"]["motion_sync"] and not cfg["sensor"]["ripple"])
    _psf2 = os.path.join(_root, "custom2_colorful.psf")
    if os.path.exists(_psf2):
        check("psf2 lighting = Colorful Streaming (mode 2)",
              import_psf(_psf2)["config"]["lighting"]["mode"] == 2)

# 7) auto-switch wiring (Razer-style base profile) through MainWindow
from app.autoswitch import rule_matches, match_profile

# pure-logic checks
check("rule exe match", rule_matches({"exe": "game.exe"}, "game.exe", "X"))
check("rule exe miss", not rule_matches({"exe": "game.exe"}, "other.exe", "X"))
check("rule title substring", rule_matches({"exe": "g.exe", "title": "Lobby"}, "g.exe", "Main Lobby"))
check("empty rule never matches", not rule_matches({}, "g.exe", "X"))

import app.profile_store as _PS3
_PS3.default_path = lambda: _ps_path + ".as"
w3 = MainWindow()
base_id = w3.profiles.active_id
game = w3.profiles.add("Game", match_rules=[{"exe": "game.exe", "title": None}])
note = w3.profiles.add("Notes", match_rules=[{"exe": "notepad.exe", "title": None}])
w3._refresh_profile_combo()
w3._select_profile(base_id)                 # manual base = Default


class _FakeWatcher:
    def __init__(self): self.fg = (None, None, None)
    def current(self): return self.fg


fw = _FakeWatcher()
w3._auto._watcher = fw
w3._auto._debounce_ms = 0          # immediate switching for the logic checks below
w3._auto.set_enabled(True)
check("auto base is the manual profile", w3._auto.base_id == base_id)

fw.fg = ("game.exe", "Game", "C:/games/game.exe"); w3._auto.poll()
check("matches -> switch to Game", w3._applied_id == game["id"])
fw.fg = ("chrome.exe", "Web", "C:/x/chrome.exe"); w3._auto.poll()
check("no match -> revert to base", w3._applied_id == base_id)
fw.fg = ("notepad.exe", "Untitled", "C:/w/notepad.exe"); w3._auto.poll()
check("matches -> switch to Notes", w3._applied_id == note["id"])

# manual selection changes the base; unruled app then stays on it
w3._select_profile(game["id"])
check("manual select updates base", w3._auto.base_id == game["id"] and w3._applied_id == game["id"])
fw.fg = ("explorer.exe", "Files", "C:/explorer.exe"); w3._auto.poll()
check("no match -> revert to new base (Game)", w3._applied_id == game["id"])

# disabling auto reverts to the manual base
w3._select_profile(base_id)
fw.fg = ("notepad.exe", "x", "C:/w/notepad.exe"); w3._auto.poll()
check("override active before disable", w3._applied_id == note["id"])
w3._auto.set_enabled(False)
check("disable reverts to base", w3._applied_id == base_id)

# debounce: a transient app does NOT switch until it's been stable long enough
w3._select_profile(base_id)
w3._auto._debounce_ms = 400
w3._auto.set_enabled(True)
fw.fg = ("game.exe", "G", "C:/g/game.exe")
w3._auto.poll()                                   # first sighting -> pending only
check("debounce: no switch on first sight", w3._applied_id == base_id)
w3._auto.poll()                                   # still within the window
check("debounce: still no switch", w3._applied_id == base_id)
w3._auto._pending_since -= 1.0                    # simulate the dwell elapsing
w3._auto.poll()
check("debounce: switches once stable", w3._applied_id == game["id"])
# a transient app (gone before the window) never switches
fw.fg = ("note.exe", "N", "C:/n/notepad.exe"); w3._auto.poll()   # pending note
fw.fg = ("game.exe", "G", "C:/g/game.exe"); w3._auto.poll()      # back to game (applied)
check("debounce: transient app skipped", w3._applied_id == game["id"])
w3._auto.set_enabled(False)

# MRU: deleting the current profile should fall back to the LAST one set
w3._select_profile(game["id"])
w3._select_profile(note["id"])     # leaving game -> game is most-recent in MRU
check("MRU tracks last profile set", w3._profile_mru[0] == game["id"])

# Profiles tab: listed, sortable, reorder drives auto-switch priority
check("profiles panel at stack index 6", w3.stack.widget(6) is w3.profiles_panel)
w3.profiles_panel.set_profiles(w3.profiles.all(), w3.profiles.active_id, "custom")
check("profiles panel lists all", w3.profiles_panel.list.count() == len(w3.profiles.all()))
w3._on_profile_sort("az")
_pn = [p["name"] for p in w3.profiles.all()]
check("panel sort A-Z applied to store", _pn == sorted(_pn, key=str.lower))
_pids = [p["id"] for p in w3.profiles.all()]
w3._on_profile_reorder(list(reversed(_pids)))
check("panel reorder applied to store",
      [p["id"] for p in w3.profiles.all()] == list(reversed(_pids)))
# management (New/Duplicate/Rename/Delete/Import) moved to the Profiles tab,
# targeting the SELECTED row (rail keeps only the quick-switch combo)
check("rail combo has no menu button", not hasattr(w3, "profile_menu"))
w3.profiles_panel.set_profiles(w3.profiles.all(), w3.profiles.active_id, "custom")
w3.profiles_panel.list.setCurrentRow(1)
_sel = w3.profiles_panel.selected_id()
check("panel selected_id works", _sel == w3.profiles.all()[1]["id"])
check("management targets the selected row", w3._target_profile_id() == _sel)
# "Detect app" confirmation flashes the (configured) overlay, even if disabled
w3._overlay_enabled = False
w3.overlay.hide()
w3._on_app_detected("game.exe", "Wuthering Waves")
check("detect flashes overlay regardless of enable", w3.overlay.isVisible())
check("detect overlay shows app + window (4 widgets)", w3.overlay._lay.count() == 4)

# auto-start ("Start with Windows") -- read-only checks (don't touch the registry)
from app import autostart as _AS
check("autostart is_enabled returns bool", isinstance(_AS.is_enabled(), bool))
check("autostart command starts minimized", "--minimized" in _AS.launch_command())

# PATH matching: two same-named exes in different folders -> different profiles
from app.autoswitch import rule_matches as _rm
check("path distinguishes same exe (match)",
      _rm({"exe": "client-win64-shipping.exe", "path": "GameA"},
          "client-win64-shipping.exe", "", "D:/Steam/GameA/client-win64-shipping.exe"))
check("path distinguishes same exe (miss)",
      not _rm({"exe": "client-win64-shipping.exe", "path": "GameA"},
              "client-win64-shipping.exe", "", "D:/Steam/GameB/client-win64-shipping.exe"))

# Auto-Switch panel is wired into the nav + stack
check("nav has 7 items (Auto-Switch + Profiles)", w3.nav.count() == 7)
check("auto-switch panel at stack index 5", w3.stack.widget(5) is w3.autoswitch_panel)
w3.autoswitch_panel.set_profiles(w3.profiles.all(), game["id"])
check("panel lists all profiles", w3.autoswitch_panel.profile_combo.count() == len(w3.profiles.all()))

# overlay HUD: exists, toggles, and flashes without error
check("overlay created", w3.overlay is not None)
w3._toggle_overlay(True)
check("overlay enabled persists", w3.profiles.get_setting("overlay") is True)
w3.overlay.flash(1600, "DPI")
check("overlay shows on flash", w3.overlay.isVisible())
w3._toggle_overlay(False)
check("overlay disabled persists", w3.profiles.get_setting("overlay") is False)
# overlay appearance config (position / opacity / scale)
from app.widgets.overlay import POSITIONS
w3.overlay.set_appearance("top-right", 60, 150)
check("overlay appearance applied",
      w3.overlay._pos == "top-right" and abs(w3.overlay._opacity_shown - 0.6) < 0.01
      and abs(w3.overlay._scale - 1.5) < 0.01)
check("9 overlay positions", len(POSITIONS) == 9)
# monitor selection: follow-cursor vs a fixed monitor index
from PySide6.QtGui import QGuiApplication as _QGA
from app.widgets.overlay import _target_screen as _ovl_screen
check("follow-cursor picks a screen", _ovl_screen(w3.overlay, True, 0) is not None)
check("fixed monitor 0 = first screen",
      _ovl_screen(w3.overlay, False, 0) is _QGA.screens()[0])
# show-gating settings persist + default
w3._overlay_show = {"profile": True, "dpi": False, "rate": True}
w3.profiles.set_setting("overlay_show", w3._overlay_show)
check("overlay show settings persist",
      w3.profiles.get_setting("overlay_show")["rate"] is True)
# overlay shows ALL enabled fields together (the bug: only DPI showed)
w3._overlay_enabled = True
w3._overlay_show = {"profile": True, "dpi": True, "rate": True}
w3._cur_profile, w3._cur_dpi, w3._cur_rate = "FPS", 1600, 1000
w3._overlay_flash()
check("overlay multi-field flash visible", w3.overlay.isVisible())
check("overlay rendered 3 fields (6 widgets)", w3.overlay._lay.count() == 6)
w3.overlay.flash_lines([("DPI", 800)])
check("overlay single field (2 widgets)", w3.overlay._lay.count() == 2)
# overlay flashes when an apply FINISHES (busy->False), not when it's queued
w3._overlay_enabled = True
w3._cur_profile = "FPS"
w3._overlay_pending = True
w3.overlay.hide()
w3._on_busy_overlay(True)
check("overlay waits while applying", not w3.overlay.isVisible())
w3._on_busy_overlay(False)
check("overlay flashes when apply done", w3.overlay.isVisible())
check("overlay-pending cleared", w3._overlay_pending is False)
# two-phase: "Switching to X" immediately, then the detailed card on completion
w3._overlay_enabled = True
w3._overlay_show = {"profile": True, "dpi": False, "rate": False}
w3._applied_id = base_id
w3._prev_overlay_pid = base_id
w3.overlay.hide()
w3._apply_by_id(game["id"])
check("switching overlay shown immediately", w3.overlay.isVisible())
check("overlay caption is SWITCHING TO",
      w3.overlay._lay.itemAt(0).widget().text() == "SWITCHING TO")
check("apply pending set", w3._overlay_pending is True)
w3._on_busy_overlay(False)                       # apply finished
check("detailed overlay replaces it on done",
      w3.overlay._lay.itemAt(0).widget().text() == "PROFILE")

# battery alerts: persistent (manually-dismissed) at 20% / 10% / fully-charged
w3.alert_overlay.hide()
w3._charging = False
w3._batt_alerted = set(); w3._full_alerted = False
w3._check_battery_alerts(50)
check("no alert above thresholds", not w3.alert_overlay.isVisible())
w3._check_battery_alerts(20)
check("alert at 20%", w3.alert_overlay.isVisible()
      and w3.alert_overlay.caption.text() == "BATTERY LOW")
w3.alert_overlay.hide()
w3._check_battery_alerts(18)
check("no re-alert while still <=20", not w3.alert_overlay.isVisible())
w3._check_battery_alerts(10)
check("critical alert at 10%",
      w3.alert_overlay.caption.text() == "BATTERY CRITICALLY LOW")
w3.alert_overlay.hide()
w3._check_battery_alerts(80)                      # recharged -> re-arm
w3._check_battery_alerts(20)
check("re-alerts after recharge", w3.alert_overlay.isVisible())
# fully charged (only while charging)
w3.alert_overlay.hide(); w3._full_alerted = False
w3._charging = True
w3._check_battery_alerts(100)
check("fully-charged alert",
      w3.alert_overlay.isVisible() and w3.alert_overlay.caption.text() == "FULLY CHARGED")
w3.alert_overlay.hide()
w3._check_battery_alerts(100)
check("no repeat fully-charged", not w3.alert_overlay.isVisible())
# dismiss button hides it
w3.alert_overlay.alert("Test", "x")
w3.alert_overlay.dismiss.click()
check("dismiss hides the alert", not w3.alert_overlay.isVisible())

# diff-apply: only push the sections that changed (force pushes all)
_calls = []
w3.ctrl.call = lambda method, *a, **k: _calls.append(method)
cfg_a = default_config()
cfg_b = default_config(); cfg_b["polling_hz"] = 1000     # differs only in polling
w3._current_config = dict(cfg_a)
_calls.clear()
w3.apply_profile(cfg_b)
check("diff-apply pushes only changed section", _calls == ["set_polling_rate"])
_calls.clear()
w3.apply_profile(cfg_b, force=True)
check("force pushes all 7 sections", len(_calls) == 7)
_calls.clear()
w3.apply_profile(cfg_b)                                  # identical to current -> nothing
check("no-op apply pushes nothing", _calls == [])
w3.ctrl.shutdown()

# macro per-slot limit (125) enforced in the editor
from sm809pro.macros import MAX_MACRO_EVENTS
check("macro limit is 125", MAX_MACRO_EVENTS == 125)
mp.new_macro()
mp.add_text_events("a" * 200, 5)           # 400 events -> capped
check("macro capped at limit",
      len(mp._cur()["events"]) == MAX_MACRO_EVENTS)
n_before = len(mp._cur()["events"])
mp.insert_event("key", 0x04, mode="tap")   # refused (no room)
check("insert refused at limit", len(mp._cur()["events"]) == n_before)

# 8) Run APP (host-side launcher) -- byte[7] mapping confirmed via pcap
check("runapp code 0x08 -> button 1", A.runapp_code_to_physical(0x08) == 1)
check("runapp code 0x0C -> button 5", A.runapp_code_to_physical(0x0C) == 5)
check("runapp code 0x0E -> button 9", A.runapp_code_to_physical(0x0E) == 9)
check("runapp code 0x06 -> button 10", A.runapp_code_to_physical(0x06) == 10)
check("runapp code 0 -> None", A.runapp_code_to_physical(0) is None)
check("describe runapp binding",
      describe_action({"runapp": "C:/x/calc.exe"}) == "Run App: calc.exe")
# a runapp binding resolves to the device placeholder, no macro upload
rcodes, rmacros = w._resolve_bindings([{"runapp": "calc.exe"}] + [A.BTN["unset"]] * 15)
check("runapp resolves to placeholder", tuple(rcodes[0]) == tuple(A.BTN["run_app"]))
check("runapp uploads no macro", rmacros == {})

# .psf import of a Run-APP profile -> {"runapp": path} bindings with the exe URL
_psf_run = os.path.join(_root, "run_app.psf")
if os.path.exists(_psf_run):
    from app.psf_import import import_psf as _imp
    rb = _imp(_psf_run)["config"]["buttons"]
    runapps = {i + 1: b["runapp"] for i, b in enumerate(rb)
               if isinstance(b, dict) and "runapp" in b}
    check("psf run-app buttons captured (1,5,9,10)",
          set(runapps.keys()) == {1, 5, 9, 10})
    check("psf run-app exe path imported",
          all(p.lower().endswith("calc.exe") for p in runapps.values()))

# .psf macro import -> decoded library macros (verified vs macro.psf = "Hello")
_psf_mac = os.path.join(_root, "macro.psf")
if os.path.exists(_psf_mac):
    from app.psf_import import import_psf as _impm
    mi = _impm(_psf_mac)
    check("psf macro decoded", len(mi["macros"]) == 1)
    mac0 = mi["macros"][0]
    check("psf macro has 12 events (Hello)", len(mac0["events"]) == 12)
    check("psf macro first event = LShift down",
          mac0["events"][0]["keycode"] == 0xE1 and mac0["events"][0]["down"])
    check("psf macro 2nd event = 'h' down (HID 0x0B)",
          mac0["events"][1]["keycode"] == 0x0B)
    # the macro button now references the macro by temp id (remapped on import)
    binding = mi["config"]["buttons"][mac0["phys"] - 1]
    check("psf macro button references macro",
          isinstance(binding, dict) and binding.get("macro") == mac0["tempid"])

# theme dark palette & scroll area viewport consistency
from app import theme
dpal = theme.dark_palette()
check("theme dark_palette defined", dpal is not None)
if dpal is not None:
    from PySide6.QtGui import QPalette, QColor
    check("dark_palette window color is BG", dpal.color(QPalette.Window).name().lower() == theme.BG.lower())

# verify scroll area content does not paint white even if light palette was set
app.setStyleSheet(theme.stylesheet())
w.resize(1000, 680)
w.show()
app.processEvents()
img = w.grab().toImage()
check("buttons panel scroll background is not white", QColor(img.pixel(400, 200)).name().lower() != "#ffffff")
w.nav.setCurrentRow(1)
app.processEvents()
img = w.grab().toImage()
check("macro panel editor scroll background is not white", QColor(img.pixel(500, 480)).name().lower() != "#ffffff")
check("macro list keeps its border", any(img.pixelColor(x, 250).name() == theme.BORDER.lower() for x in range(200, 225)))
check("macro events table keeps its border", any(img.pixelColor(x, 450).name() == theme.BORDER.lower() for x in range(460, 485)))

# ActionPicker Key Combination: "None" option, modifier-only, and comprehensive keys
from app.widgets.action_picker import describe_action, ActionPicker, _ComboEditor
check("describe_action Alt only", describe_action(A.kb(0, A.MOD_ALT)) == "Alt")
check("describe_action Ctrl only", describe_action(A.kb(0, A.MOD_CTRL)) == "Ctrl")
check("describe_action Shift only", describe_action(A.kb(0, A.MOD_SHIFT)) == "Shift")
check("describe_action Win only", describe_action(A.kb(0, A.MOD_WIN)) == "Win")
check("describe_action Ctrl+Shift only", describe_action(A.kb(0, A.MOD_CTRL | A.MOD_SHIFT)) == "Ctrl+Shift")
check("describe_action 0x70 empty", describe_action((0x70, 0, 0)) == "(none)")

# Expanded keyboard keys in describe_action
check("describe_action DEL", describe_action(A.kb(A.HID["del"])) == "Key: DEL")
check("describe_action Ctrl+DEL", describe_action(A.kb(A.HID["del"], A.MOD_CTRL)) == "Ctrl+DEL")
check("describe_action HOME", describe_action(A.kb(A.HID["home"])) == "Key: HOME")
check("describe_action END", describe_action(A.kb(A.HID["end"])) == "Key: END")
check("describe_action PAGE UP", describe_action(A.kb(A.HID["page up"])) == "Key: PAGE UP")
check("describe_action PAGE DOWN", describe_action(A.kb(A.HID["page down"])) == "Key: PAGE DOWN")
check("describe_action BACKSPACE", describe_action(A.kb(A.HID["backspace"])) == "Key: BACKSPACE")
check("describe_action INSERT", describe_action(A.kb(A.HID["insert"])) == "Key: INSERT")

# ActionPicker with modifier-only action
dlg = ActionPicker((0x70, A.MOD_ALT, 0))
check("ActionPicker opens on Key Combination for Alt", dlg.cats.currentItem().text() == "Key Combination")
check("ActionPicker Alt is checked", dlg.combo_editor.alt.isChecked())
check("ActionPicker Ctrl is unchecked", not dlg.combo_editor.ctrl.isChecked())
check("ActionPicker Key is None (data=0)", dlg.combo_editor.key.currentData() == 0)
check("ActionPicker code is (0x70, 4, 0)", dlg.combo_editor.code() == (0x70, 0x04, 0x00))
check("ActionPicker preview is 'Alt'", dlg.preview.text() == "Alt")
check("ActionPicker OK button enabled", dlg.ok_btn.isEnabled())

# Uncheck modifier with Key=None -> defaults to "Disable" (0x60, 0x00, 0x00)
dlg.combo_editor.alt.setChecked(False)
check("ActionPicker uncheck Alt -> code is Disable", dlg.combo_editor.code() == A.BTN["disable"])
check("ActionPicker uncheck Alt -> OK button enabled", dlg.ok_btn.isEnabled())
check("ActionPicker uncheck Alt -> preview is 'Disable'", dlg.preview.text() == "Disable")

# Check Ctrl -> valid Ctrl-only action
dlg.combo_editor.ctrl.setChecked(True)
check("ActionPicker check Ctrl -> code is (0x70, 1, 0)", dlg.combo_editor.code() == (0x70, 0x01, 0x00))
check("ActionPicker check Ctrl -> preview is 'Ctrl'", dlg.preview.text() == "Ctrl")
check("ActionPicker check Ctrl -> OK button enabled", dlg.ok_btn.isEnabled())

# Detect Key feature
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
dlg.combo_editor.detect_btn.click()
check("Detect Key button enters listening mode", dlg.combo_editor._listening)
check("Detect Key button text shows 'Press any key…'", dlg.combo_editor.detect_btn.text() == "Press any key…")

# Simulate pressing Delete
evt_del = QKeyEvent(QEvent.KeyPress, int(Qt.Key_Delete), Qt.NoModifier)
dlg.combo_editor._handle_key_press(evt_del)
check("Detect Delete -> stops listening", not dlg.combo_editor._listening)
check("Detect Delete -> button text restored", dlg.combo_editor.detect_btn.text() == "Detect Key")
check("Detect Delete -> Key dropdown selected DEL", dlg.combo_editor.key.currentData() == A.HID["del"])
check("Detect Delete -> code is (0x70, 0, 0x4C)", dlg.combo_editor.code() == (0x70, 0x00, 0x4C))
check("Detect Delete -> preview is 'Key: DEL'", dlg.preview.text() == "Key: DEL")

# Simulate pressing Ctrl+End
evt_combo = QKeyEvent(QEvent.KeyPress, int(Qt.Key_End), Qt.ControlModifier)
dlg.combo_editor._handle_key_press(evt_combo)
check("Detect Ctrl+End -> Ctrl is checked", dlg.combo_editor.ctrl.isChecked())
check("Detect Ctrl+End -> Key is END", dlg.combo_editor.key.currentData() == A.HID["end"])
check("Detect Ctrl+End -> preview is 'Ctrl+END'", dlg.preview.text() == "Ctrl+END")

# Simulate pressing Shift alone
evt_shift = QKeyEvent(QEvent.KeyPress, int(Qt.Key_Shift), Qt.NoModifier)
dlg.combo_editor._handle_key_press(evt_shift)
check("Detect Shift alone -> Shift checked", dlg.combo_editor.shift.isChecked())
check("Detect Shift alone -> Ctrl unchecked", not dlg.combo_editor.ctrl.isChecked())
check("Detect Shift alone -> Key is None", dlg.combo_editor.key.currentData() == 0)
check("Detect Shift alone -> preview is 'Shift'", dlg.preview.text() == "Shift")
# Macro Panel KEY_INSERT_CHOICES comprehensive keys
from app.panels.macro_panel import KEY_INSERT_CHOICES
macro_key_codes = {code for _, code in KEY_INSERT_CHOICES}
check("macro choices has Delete", 0x4C in macro_key_codes)
check("macro choices has Insert", 0x49 in macro_key_codes)
check("macro choices has Home", 0x4A in macro_key_codes)
check("macro choices has End", 0x4D in macro_key_codes)
check("macro choices has Page Up", 0x4B in macro_key_codes)
check("macro choices has Page Down", 0x4E in macro_key_codes)
check("macro choices has Print Screen", 0x46 in macro_key_codes)
check("macro choices has Pause", 0x48 in macro_key_codes)
check("macro choices has F13", 0x68 in macro_key_codes)
check("macro choices has F24", 0x73 in macro_key_codes)
check("macro choices has Num Enter", 0x58 in macro_key_codes)
check("macro choices has Menu", 0x65 in macro_key_codes)

# TopBar connection UI tests for Bluetooth
w.topbar.set_connection({"connection": "bluetooth", "configurable": True})
check("TopBar Bluetooth (configurable) text", w.topbar.conn_pill.text() == "● Bluetooth")
check("TopBar Bluetooth (configurable) tooltip", "Connected via Bluetooth" in w.topbar.conn_pill.toolTip())

w.topbar.set_connection({"connection": "bluetooth", "configurable": False})
check("TopBar Bluetooth (read-only) text", w.topbar.conn_pill.text() == "● Bluetooth")
check("TopBar Bluetooth (read-only) tooltip mentions read-only", "read-only" in w.topbar.conn_pill.toolTip())

w.topbar.set_disconnected()
check("TopBar disconnected text", w.topbar.conn_pill.text() == "● not connected")
check("TopBar disconnected tooltip mentions searching", "Searching for connection" in w.topbar.conn_pill.toolTip())

w.topbar.set_offline()
check("TopBar 2.4G offline text", w.topbar.conn_pill.text() == "● mouse offline")
check("TopBar 2.4G offline tooltip mentions offline", "mouse is offline" in w.topbar.conn_pill.toolTip())

# DeviceController auto-detection & mode-switching tests
from app.controller import DeviceController
from app import controller as _app_ctrl

old_status_cls = _app_ctrl.StatusListener
class MockStatusListener:
    _alive = True
    def __init__(self, *args, **kwargs): pass
    def start(self): pass
    def stop(self): pass
_app_ctrl.StatusListener = MockStatusListener

ctrl = DeviceController()
connected_events = []
disconnected_events = []
ctrl.connected.connect(lambda info: connected_events.append(info))
ctrl.disconnected.connect(lambda: disconnected_events.append(True))

# 1. Test connect attempt when device is available
ctrl._dev._dev = object()
ctrl._dev.connection = "bluetooth"
ctrl._dev.configurable = True
ctrl._dev.open = lambda: True
ctrl._dev.pid = 0x0270
ctrl._dev.vid = 0x04F3

ctrl._attempt_connect()
check("DeviceController emits connected on attach", len(connected_events) == 1)
check("DeviceController connected info has bluetooth", connected_events[-1]["connection"] == "bluetooth")
check("DeviceController connected info is configurable", connected_events[-1]["configurable"] is True)
check("DeviceController is_connected is True", ctrl._is_connected is True)

# 2. Test keepalive failure triggers teardown and disconnected signal
ctrl._dev.keepalive_poll = lambda: False
ctrl._last_keepalive = 0.0  # force keepalive to run immediately
ctrl._maintain_connection()
check("DeviceController emits disconnected on keepalive failure", len(disconnected_events) == 1)
check("DeviceController is_connected is False after disconnect", ctrl._is_connected is False)

# 3. Test queue draining while disconnected
done_events = []
ctrl.command_done.connect(lambda m, ok: done_events.append((m, ok)))
ctrl.call("set_dpi", [800, 1600])
ctrl._drain_queue()
check("Drained queue emits command_done with False", done_events == [("set_dpi", False)])
check("Busy is False after draining", ctrl._q.empty())

# 4. Test mode-switching: 2.4GHz offline -> Bluetooth available triggers switch
ctrl._dev.open = lambda: True
ctrl._dev.connection = "2.4GHz"
ctrl._dev._dev = object()
ctrl._dev.configurable = True
ctrl._is_connected = True
mock_status = MockStatusListener()
mock_status._alive = False
ctrl._status = mock_status

# Mock detect_modes to return Bluetooth
from sm809pro import device as _dev_module
orig_detect = _dev_module.detect_modes
_dev_module.detect_modes = lambda vid=0x04F3: [{"connection": "bluetooth", "pid": 0x0270, "configurable": True, "devs": []}]
_app_ctrl.detect_modes = _dev_module.detect_modes

ctrl._last_mode_check = 0.0  # force mode check
ctrl._maintain_connection()
check("Mode switch tears down 2.4GHz when Bluetooth appears", ctrl._is_connected is False)

_dev_module.detect_modes = orig_detect
_app_ctrl.detect_modes = orig_detect
_app_ctrl.StatusListener = old_status_cls

ctrl.shutdown()
dlg.close()

w.ctrl.shutdown()
w.close()
print(f"\n{('ALL GOOD' if fails == 0 else str(fails) + ' FAILED')}")
sys.exit(0 if fails == 0 else 1)

