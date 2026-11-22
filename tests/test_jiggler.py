"""
tests/test_jiggler.py -- offline/headless test suite for Mouse Jiggler.

Covers patterns & net-zero invariants, validation/clamping, Win32 INPUT struct
ABI layout, spy-backend jiggling, user-activity pause, SetThreadExecutionState
lifecycle, randomized intervals, workstation lock/unlock pause, power resume,
preview pulse, tray tooltips, and JigglerSettingsDialog UI/dark rendering.

Run:  py -3.14 tests/test_jiggler.py
"""

import ctypes
import io
import os
import random
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from app import theme
from app.jiggler import (
    DEFAULT_DISTANCE,
    DEFAULT_MODE,
    DEFAULT_PERIOD,
    INPUT,
    JIGGLE_MODES,
    MAX_DISTANCE,
    MAX_PERIOD,
    MIN_DISTANCE,
    MIN_PERIOD,
    MOUSEINPUT,
    MouseJiggler,
    NullJigglerBackend,
    clamp_distance,
    clamp_period,
    coerce_mode,
    compute_pattern,
)
from app.widgets.jiggler_dialog import JigglerSettingsDialog

app = QApplication.instance() or QApplication([])
pal = theme.dark_palette()
if pal is not None:
    app.setPalette(pal)
app.setStyleSheet(theme.stylesheet())

fails = 0


def check(name, cond):
    global fails
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        fails += 1


class SpyBackend:
    """Deterministic spy backend simulating Windows cursor + execution state."""

    def __init__(self, start_pos=(100, 200), move_cursor_on_jiggle=True):
        self.pos = start_pos
        self.move_cursor_on_jiggle = move_cursor_on_jiggle
        self.jiggles = []
        self.awake_calls = 0
        self.sleep_calls = 0
        self.awake = False

    def supported(self):
        return True

    def jiggle(self, dx, dy):
        self.jiggles.append((dx, dy))
        if self.move_cursor_on_jiggle and self.pos is not None:
            self.pos = (self.pos[0] + dx, self.pos[1] + dy)
        return True

    def stay_awake(self):
        self.awake_calls += 1
        self.awake = True
        return True

    def allow_sleep(self):
        self.sleep_calls += 1
        self.awake = False
        return True

    def get_cursor_pos(self):
        return self.pos


# 1) Patterns & net-zero displacement invariants
for mode in JIGGLE_MODES:
    for dist in (1, 5):
        pat = compute_pattern(mode, dist)
        check(f"pattern {mode} d={dist} non-empty", len(pat) > 0)
        check(
            f"pattern {mode} d={dist} net-zero displacement",
            sum(dx for dx, _ in pat) == 0 and sum(dy for _, dy in pat) == 0,
        )

check("Normal d=1 exact", compute_pattern("Normal", 1) == [(4, 4), (-4, -4)])
check("Zen d=5 exact", compute_pattern("Zen", 5) == [(0, 0)])
check("Linear d=3 exact", compute_pattern("Linear", 3) == [(12, 0), (-12, 0)])
check("Circle has 8 steps", len(compute_pattern("Circle", 1)) == 8)

# 2) Coercion & clamping
check("coerce_mode case-insensitive", coerce_mode("  cIrClE ") == "Circle")
check("coerce_mode invalid falls back", coerce_mode("zigzag") == DEFAULT_MODE)
check("coerce_mode None falls back", coerce_mode(None) == DEFAULT_MODE)

check("clamp_period low", clamp_period(0) == MIN_PERIOD)
check("clamp_period high", clamp_period(99999) == MAX_PERIOD)
check("clamp_period valid string", clamp_period("45") == 45)
check("clamp_period rejects bool", clamp_period(True) == DEFAULT_PERIOD)
check("clamp_period invalid", clamp_period("abc") == DEFAULT_PERIOD)

check("clamp_distance low", clamp_distance(-3) == MIN_DISTANCE)
check("clamp_distance high", clamp_distance(500) == MAX_DISTANCE)
check("clamp_distance valid", clamp_distance(12) == 12)
check("clamp_distance rejects bool", clamp_distance(False) == DEFAULT_DISTANCE)
check("clamp_distance invalid", clamp_distance(None) == DEFAULT_DISTANCE)

# 3) Win32 struct ABI layout on Windows
if os.name == "nt":
    expected_input_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    check("Win32 INPUT struct ABI size", ctypes.sizeof(INPUT) == expected_input_size)
    check("Win32 MOUSEINPUT defined", ctypes.sizeof(MOUSEINPUT) >= 24)

# 4) Default backend under offscreen is NullJigglerBackend
default_j = MouseJiggler()
check("offscreen default uses NullJigglerBackend", isinstance(default_j._backend, NullJigglerBackend))
default_j.shutdown()

# 5) MouseJiggler movement detection, pattern cycling, and stay-awake lifecycle
spy = SpyBackend(start_pos=(100, 200))
j = MouseJiggler(backend=spy, rng=random.Random(42), enable_win_events=False)
j.configure(mode="Normal", period=10, distance=2)

enabled_events = []
tick_events = []
j.enabled_changed.connect(enabled_events.append)
j.tick_completed.connect(tick_events.append)

j.set_enabled(True)
check("enable sets active & stay_awake", j.enabled and j.is_active and spy.awake and spy.awake_calls == 1)
check("enabled_changed emitted True", enabled_events == [True])

# Tick 1 (stationary) -> step 0: (8, 8)
j._on_tick()
check("tick 1 jiggles (8, 8)", spy.jiggles == [(8, 8)])
check("tick 1 cursor moved to (108, 208)", spy.pos == (108, 208))
check("tick 1 re-asserted stay_awake", spy.awake_calls == 2)
check("tick 1 emitted interval 10", tick_events == [10])

# Tick 2 (still stationary relative to post-jiggle pos!) -> step 1: (-8, -8)
j._on_tick()
check("tick 2 completes cycle (-8, -8)", spy.jiggles == [(8, 8), (-8, -8)])
check("tick 2 cursor returned to (100, 200)", spy.pos == (100, 200))

# User moves cursor -> next tick skips jiggle, next stationary tick resumes
spy.pos = (500, 300)
j._on_tick()
check("user movement pauses tick (no new jiggle)", len(spy.jiggles) == 2)
j._on_tick()
check("stationary after user move resumes jiggling", spy.jiggles[-1] == (8, 8))

# Disable -> allow_sleep called, timer stopped
j.set_enabled(False)
check("disable stops active & calls allow_sleep", (not j.is_active) and (not spy.awake) and spy.sleep_calls >= 1)
check("enabled_changed emitted False", enabled_events == [True, False])

# 6) Circle 8-step full cycle net-zero
spy_c = SpyBackend(start_pos=(400, 400))
jc = MouseJiggler(backend=spy_c, enable_win_events=False)
jc.configure(mode="Circle", period=5, distance=3)
jc.set_enabled(True)
for _ in range(8):
    jc._on_tick()
check("Circle 8 ticks returns cursor to exact origin", spy_c.pos == (400, 400))
jc.shutdown()
check("shutdown releases sleep lock", not spy_c.awake)
jc.shutdown()  # idempotent second call
check("double shutdown safe", not jc.enabled)

# 7) Random timer bounds
spy_r = SpyBackend()
jr = MouseJiggler(backend=spy_r, rng=random.Random(1234), enable_win_events=False)
jr.configure(mode="Zen", period=25, random_timer=True)
jr.set_enabled(True)
rolled = []
for _ in range(25):
    jr._on_tick()
    rolled.append(jr.current_interval_s)
check("random intervals within [1, 25]", all(1 <= s <= 25 for s in rolled) and len(set(rolled)) > 1)
check("random timer updated QTimer interval", jr._timer.interval() == rolled[-1] * 1000)
jr.configure(random_timer=False)
check("disabling random restores fixed interval", jr.current_interval_s == 25 and jr._timer.interval() == 25000)
jr.shutdown()

# 8) Workstation lock/unlock policy
spy_l = SpyBackend()
jl = MouseJiggler(backend=spy_l, enable_win_events=False)
jl.configure(respect_locked_state=False)
jl.set_enabled(True)
jl.set_workstation_locked(True)
check("locked with respect=False stays active", jl.is_active and not jl.is_paused_locked and spy_l.awake)

jl.configure(respect_locked_state=True)
check("enabling respect while locked pauses immediately", (not jl.is_active) and jl.is_paused_locked and (not spy_l.awake))
check("lock pause preserves user enabled flag", jl.enabled is True)

jl.set_workstation_locked(False)
check("unlock resumes jiggling & stay_awake", jl.is_active and not jl.is_paused_locked and spy_l.awake)

jl.set_workstation_locked(True)
check("re-lock pauses again", not jl.is_active and jl.is_paused_locked and not spy_l.awake)
jl.shutdown()

# 9) Power resume recovery
spy_p = SpyBackend()
jp = MouseJiggler(backend=spy_p, enable_win_events=False)
jp.set_enabled(True)
before_awake = spy_p.awake_calls
jp.on_power_resume()
check("on_power_resume re-asserts stay_awake & keeps timer running", spy_p.awake_calls == before_awake + 1 and jp._timer.isActive())
jp.set_enabled(False)
before_awake_off = spy_p.awake_calls
jp.on_power_resume()
check("on_power_resume while disabled stays stopped", spy_p.awake_calls == before_awake_off and not jp._timer.isActive())
jp.shutdown()

# 10) Preview pulse (non-Zen round trip + Zen no-return + rapid double-pulse)
spy_pv = SpyBackend(start_pos=(300, 300))
jpv = MouseJiggler(backend=spy_pv, enable_win_events=False)
jpv.pulse_preview(mode="Linear", distance=3)
check("preview immediate step (12, 0)", spy_pv.jiggles == [(12, 0)] and spy_pv.pos == (312, 300))
jpv._finish_preview()
check("preview finish returns (-12, 0)", spy_pv.jiggles == [(12, 0), (-12, 0)] and spy_pv.pos == (300, 300))

jpv.pulse_preview(mode="Normal", distance=2)
jpv.pulse_preview(mode="Linear", distance=1)
jpv._finish_preview()
check("rapid double preview preserves net-zero cursor pos", spy_pv.pos == (300, 300))

count_before_zen = len(spy_pv.jiggles)
jpv.pulse_preview(mode="Zen", distance=10)
check("Zen preview sends single (0, 0) with no timer", spy_pv.jiggles[count_before_zen:] == [(0, 0)] and not jpv._preview_timer.isActive())
jpv.shutdown()

# 11) Status summary & tray tooltip formatting
check("inactive summary", j.status_summary() == "Inactive")
check("inactive tooltip preserves base", j.tray_tooltip("SM809 Pro") == "SM809 Pro")
j.configure(mode="Circle", period=45, distance=3, random_timer=True, respect_locked_state=True)
j.set_enabled(True)
check(
    "active random summary includes range, next interval & mode",
    "Active" in j.status_summary()
    and "1\u201345 s" in j.status_summary()
    and f"(next {j.current_interval_s} s)" in j.status_summary()
    and "Circle" in j.status_summary(),
)
j.configure(mode="Zen", period=20, random_timer=True)
j._on_tick()
check(
    "active random Zen summary includes next interval",
    "1\u201320 s" in j.status_summary()
    and f"(next {j.current_interval_s} s)" in j.status_summary()
    and "Zen" in j.status_summary(),
)
tip = j.tray_tooltip()
check("active tooltip bounded <= 120 chars", "Mouse Jiggler:" in tip and len(tip) <= 120)
j.set_workstation_locked(True)
check("locked summary says Paused", "Paused" in j.status_summary())
j.shutdown()

j_no_hk = MouseJiggler(backend=SpyBackend(), enable_win_events=False, hotkey_enabled=False)
check("hotkey_enabled constructor kwarg honored", j_no_hk.hotkey_enabled is False)
j_no_hk.shutdown()

# 12) JigglerSettingsDialog headless UI & dark rendering checks
spy_d = SpyBackend(start_pos=(250, 250))
jd = MouseJiggler(backend=spy_d, enable_win_events=False)
jd.configure(mode="Normal", period=30, distance=5, random_timer=True, respect_locked_state=True, hotkey_enabled=True)
dlg = JigglerSettingsDialog(jd, autostart=True)

check("dialog initializes enable_cb False", dlg.enable_cb.isChecked() is False)
check("dialog initializes mode Normal", dlg.mode_combo.currentData() == "Normal")
check("dialog initializes period 30", dlg.period_spin.value() == 30)
check("dialog initializes distance 5", dlg.distance_spin.value() == 5)
check("dialog initializes random True", dlg.random_cb.isChecked() is True)
check("dialog initializes respect_lock True", dlg.respect_lock_cb.isChecked() is True)
check("dialog initializes hotkey True", dlg.hotkey_cb.isChecked() is True)
check("dialog initializes autostart True", dlg.autostart_cb.isChecked() is True)
check("dialog distance warning hidden at d=5", dlg.distance_hint.isHidden())

# Switch to Zen -> distance_spin disabled, mode_hint updates
zen_idx = dlg.mode_combo.findData("Zen")
dlg.mode_combo.setCurrentIndex(zen_idx)
check("Zen disables distance_spin", not dlg.distance_spin.isEnabled())
check("Zen updates mode_hint", "Virtual movement" in dlg.mode_hint.text())

# Switch to Circle and set distance=25 -> re-enabled and warning visible
cir_idx = dlg.mode_combo.findData("Circle")
dlg.mode_combo.setCurrentIndex(cir_idx)
dlg.distance_spin.setValue(25)
check("Circle re-enables distance_spin", dlg.distance_spin.isEnabled())
check("distance > 20 shows warning", not dlg.distance_hint.isHidden())

# Test jiggle button triggers preview pulse
dlg.test_btn.click()
check("Test jiggle button sends preview step", len(spy_d.jiggles) == 1)
jd._finish_preview()

# Round-trip values()
dlg.enable_cb.setChecked(True)
dlg.period_spin.setValue(90)
dlg.random_cb.setChecked(False)
dlg.autostart_cb.setChecked(False)
vals = dlg.values()
check(
    "dialog values() reflects edits",
    vals == {
        "enabled": True,
        "mode": "Circle",
        "period": 90,
        "distance": 25,
        "random_timer": False,
        "respect_locked_state": True,
        "hotkey_enabled": True,
        "autostart": False,
    },
)

# Dark theme visual check offscreen
dlg.show()
app.processEvents()
img = dlg.grab().toImage()
check("dialog background is dark (not white)", QColor(img.pixel(8, 8)).name().lower() != "#ffffff")
dlg.close()
jd.shutdown()

# 13) Single-instance IPC (--stop-jiggling vs show) round-trip
import run_app as _RA

_orig_key = _RA._INSTANCE_KEY
_test_key = f"SM809Pro_jiggler_test_{os.getpid()}"
_RA._INSTANCE_KEY = _test_key
ipc_calls = []
_loop = QEventLoop()


class _DummyWin:
    def _toggle_jiggler(self, on):
        ipc_calls.append(("stop", on))
        _loop.quit()

    def _show_from_tray(self):
        ipc_calls.append(("show",))
        _loop.quit()


_srv = _RA._listen_for_relaunch(_DummyWin())
try:
    def _send_ipc(payload: bytes):
        code = (
            "import os, sys; "
            "os.environ['QT_QPA_PLATFORM'] = 'offscreen'; "
            "from PySide6.QtWidgets import QApplication; "
            "import run_app; "
            f"run_app._INSTANCE_KEY = {_test_key!r}; "
            "app = QApplication([]); "
            f"ok = run_app._hand_off_if_running({payload!r}); "
            "sys.exit(0 if ok else 1)"
        )
        p = subprocess.Popen([sys.executable, "-c", code])
        QTimer.singleShot(2500, _loop.quit)
        _loop.exec()
        p.wait(timeout=3)
        return p.returncode

    rc_stop = _send_ipc(b"stop-jiggling")
    check("IPC stop-jiggling delivered cleanly", rc_stop == 0 and ipc_calls == [("stop", False)])
    rc_show = _send_ipc(b"show")
    check("IPC show delivered cleanly", rc_show == 0 and ipc_calls == [("stop", False), ("show",)])
finally:
    _srv.close()
    _RA._INSTANCE_KEY = _orig_key

print(f"\n{('ALL GOOD' if fails == 0 else str(fails) + ' FAILED')}")
sys.exit(0 if fails == 0 else 1)
