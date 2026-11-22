"""
app.jiggler -- Mouse Jiggler engine modeled on arkane-systems/mousejiggler.

Generates periodic synthetic mouse movement via Win32 SendInput (with a
non-moving "Zen" mode), pauses automatically while the user moves the cursor,
prevents display/system sleep via SetThreadExecutionState, optionally pauses
when Windows is locked (WM_WTSSESSION_CHANGE), recovers on Modern Standby wake
(WM_POWERBROADCAST), and exposes a toggleable global hotkey (Ctrl+Shift+J).

Non-Windows platforms and headless/offscreen Qt runs automatically receive a
no-op backend so tests never inject real OS input or alter power state.
"""

from __future__ import annotations

import ctypes
import os
import random
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

if os.name == "nt":
    from ctypes import wintypes


# --- Constants ---------------------------------------------------------------

JIGGLE_MODES = ("Normal", "Zen", "Circle", "Linear")

MODE_DESCRIPTIONS = {
    "Normal": "Diagonal back-and-forth movement.",
    "Zen": "Virtual movement (0 px) \u2014 prevents idle without moving the cursor.",
    "Circle": "Circular 8-step cursor movement.",
    "Linear": "Horizontal left-and-right movement.",
}

MIN_PERIOD = 1
MAX_PERIOD = 10800
DEFAULT_PERIOD = 60

MIN_DISTANCE = 1
MAX_DISTANCE = 120
DEFAULT_DISTANCE = 1

DEFAULT_MODE = "Normal"
DEFAULT_RANDOM = False
DEFAULT_RESPECT_LOCK = False
DEFAULT_HOTKEY = True
DEFAULT_AUTOSTART = False

HOTKEY_TEXT = "Ctrl+Shift+J"

# Win32 constants
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

WM_HOTKEY = 0x0312
WM_POWERBROADCAST = 0x0218
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0

MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_J = 0x4A
TOGGLE_HOTKEY_ID = 1


# --- Validation & patterns ---------------------------------------------------

def coerce_mode(mode) -> str:
    """Return a canonical mode name from JIGGLE_MODES, defaulting to Normal."""
    if isinstance(mode, str):
        low = mode.strip().lower()
        for valid in JIGGLE_MODES:
            if valid.lower() == low:
                return valid
    return DEFAULT_MODE


def clamp_period(value) -> int:
    """Coerce and clamp the jiggle interval (seconds) to [1, 10800]."""
    if isinstance(value, bool):
        return DEFAULT_PERIOD
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PERIOD
    return max(MIN_PERIOD, min(MAX_PERIOD, iv))


def clamp_distance(value) -> int:
    """Coerce and clamp the jiggle distance multiplier to [1, 120]."""
    if isinstance(value, bool):
        return DEFAULT_DISTANCE
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DISTANCE
    return max(MIN_DISTANCE, min(MAX_DISTANCE, iv))


def compute_pattern(mode: str, distance: int = DEFAULT_DISTANCE) -> list[tuple[int, int]]:
    """Return the sequence of relative (dx, dy) deltas for `mode` and `distance`."""
    m = coerce_mode(mode)
    d = clamp_distance(distance)
    if m == "Normal":
        return [(4 * d, 4 * d), (-4 * d, -4 * d)]
    if m == "Zen":
        return [(0, 0)]
    if m == "Circle":
        return [
            (3 * d, 2 * d),
            (2 * d, 3 * d),
            (-2 * d, 3 * d),
            (-3 * d, 2 * d),
            (-3 * d, -2 * d),
            (-2 * d, -3 * d),
            (2 * d, -3 * d),
            (3 * d, -2 * d),
        ]
    if m == "Linear":
        return [(4 * d, 0), (-4 * d, 0)]
    return [(4 * d, 4 * d), (-4 * d, -4 * d)]


# --- Win32 ABI structures ----------------------------------------------------

if os.name == "nt":
    _ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", wintypes.DWORD),
            ("union", _INPUT_UNION),
        ]
else:  # pragma: no cover - non-Windows import safety
    MOUSEINPUT = None
    KEYBDINPUT = None
    HARDWAREINPUT = None
    _INPUT_UNION = None
    INPUT = None


# --- OS backends -------------------------------------------------------------

class NullJigglerBackend:
    """Safe no-op backend used on non-Windows platforms and offscreen tests."""

    def supported(self) -> bool:
        return False

    def jiggle(self, dx: int, dy: int) -> bool:
        return True

    def stay_awake(self) -> bool:
        return True

    def allow_sleep(self) -> bool:
        return True

    def get_cursor_pos(self) -> Optional[tuple[int, int]]:
        return None


class Win32JigglerBackend:
    """Windows API backend wrapping SendInput, GetCursorPos, and SetThreadExecutionState."""

    def __init__(self):
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        ]
        self._user32.SendInput.restype = wintypes.UINT

        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self._user32.GetCursorPos.restype = wintypes.BOOL

        self._kernel32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
        self._kernel32.SetThreadExecutionState.restype = wintypes.DWORD

    def supported(self) -> bool:
        return True

    def jiggle(self, dx: int, dy: int) -> bool:
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi = MOUSEINPUT(
            dx=int(dx),
            dy=int(dy),
            mouseData=0,
            dwFlags=MOUSEEVENTF_MOVE,
            time=0,
            dwExtraInfo=0,
        )
        sent = self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        return sent == 1

    def stay_awake(self) -> bool:
        flags = ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED
        return self._kernel32.SetThreadExecutionState(flags) != 0

    def allow_sleep(self) -> bool:
        return self._kernel32.SetThreadExecutionState(ES_CONTINUOUS) != 0

    def get_cursor_pos(self) -> Optional[tuple[int, int]]:
        pt = wintypes.POINT()
        if self._user32.GetCursorPos(ctypes.byref(pt)):
            return (int(pt.x), int(pt.y))
        return None


def _is_windows_gui() -> bool:
    """True only when running on Windows with the native Windows Qt platform plugin."""
    if os.name != "nt":
        return False
    app = QGuiApplication.instance()
    return app is not None and QGuiApplication.platformName() == "windows"


def _default_backend():
    if _is_windows_gui():
        return Win32JigglerBackend()
    return NullJigglerBackend()


# --- Dedicated hidden Win32 message receiver ---------------------------------

class _WinJigglerEvents(QWidget):
    """Hidden top-level HWND receiving WM_HOTKEY, WM_WTSSESSION_CHANGE, and WM_POWERBROADCAST."""

    hotkey_pressed = Signal()
    session_lock_changed = Signal(bool)
    power_resumed = Signal()

    def __init__(self):
        super().__init__(None, Qt.Tool)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

        self._user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.RegisterHotKey.restype = wintypes.BOOL

        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL

        self._wtsapi32.WTSRegisterSessionNotification.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
        ]
        self._wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL

        self._wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
        self._wtsapi32.WTSUnRegisterSessionNotification.restype = wintypes.BOOL

        self._hwnd = int(self.winId())
        self.hotkey_registered = False
        self.session_registered = False
        self._closed = False

    def register_hotkey(self) -> bool:
        if self._closed:
            return False
        if self.hotkey_registered:
            return True
        ok = bool(
            self._user32.RegisterHotKey(
                wintypes.HWND(self._hwnd),
                TOGGLE_HOTKEY_ID,
                MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT,
                VK_J,
            )
        )
        self.hotkey_registered = ok
        return ok

    def unregister_hotkey(self) -> None:
        if self.hotkey_registered and not self._closed:
            self._user32.UnregisterHotKey(wintypes.HWND(self._hwnd), TOGGLE_HOTKEY_ID)
        self.hotkey_registered = False

    def register_session_notifications(self) -> bool:
        if self._closed:
            return False
        if self.session_registered:
            return True
        ok = bool(
            self._wtsapi32.WTSRegisterSessionNotification(
                wintypes.HWND(self._hwnd),
                NOTIFY_FOR_THIS_SESSION,
            )
        )
        self.session_registered = ok
        return ok

    def unregister_session_notifications(self) -> None:
        if self.session_registered and not self._closed:
            self._wtsapi32.WTSUnRegisterSessionNotification(wintypes.HWND(self._hwnd))
        self.session_registered = False

    def nativeEvent(self, eventType, message):  # noqa: N802 (Qt naming)
        try:
            ev_type = bytes(eventType)
        except Exception:
            ev_type = b""
        if ev_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and int(msg.wParam) == TOGGLE_HOTKEY_ID:
                    self.hotkey_pressed.emit()
                    return True, 0
                if msg.message == WM_WTSSESSION_CHANGE:
                    wp = int(msg.wParam)
                    if wp == WTS_SESSION_LOCK:
                        self.session_lock_changed.emit(True)
                    elif wp == WTS_SESSION_UNLOCK:
                        self.session_lock_changed.emit(False)
                elif msg.message == WM_POWERBROADCAST:
                    wp = int(msg.wParam)
                    if wp in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
                        self.power_resumed.emit()
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    def shutdown(self) -> None:
        if self._closed:
            return
        self.unregister_hotkey()
        self.unregister_session_notifications()
        self._closed = True
        self.close()
        self.deleteLater()


# --- MouseJiggler controller -------------------------------------------------

class MouseJiggler(QObject):
    """Coordinates mouse jiggle patterns, timer ticks, idle pause, sleep lock, and Win32 events."""

    enabled_changed = Signal(bool)
    status_changed = Signal()
    tick_completed = Signal(int)

    def __init__(
        self,
        backend=None,
        rng=None,
        enable_win_events: bool = True,
        hotkey_enabled: bool = DEFAULT_HOTKEY,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._backend = backend if backend is not None else _default_backend()
        self._rng = rng if rng is not None else random.Random()

        self._enabled = False
        self._mode = DEFAULT_MODE
        self._period = DEFAULT_PERIOD
        self._distance = DEFAULT_DISTANCE
        self._random_timer = DEFAULT_RANDOM
        self._respect_locked_state = DEFAULT_RESPECT_LOCK
        self._hotkey_enabled = bool(hotkey_enabled)
        self._workstation_locked = False
        self._awake_asserted = False

        self._pattern = compute_pattern(self._mode, self._distance)
        self._step = 0
        self._last_pos: Optional[tuple[int, int]] = None
        self._current_interval_s = self._period

        self._timer = QTimer(self)
        self._timer.setInterval(self._period * 1000)
        self._timer.timeout.connect(self._on_tick)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._finish_preview)
        self._pending_preview_return: Optional[tuple[int, int]] = None

        self._win_events: Optional[_WinJigglerEvents] = None
        if enable_win_events and _is_windows_gui():
            ev = _WinJigglerEvents()
            ev.hotkey_pressed.connect(self.toggle)
            ev.session_lock_changed.connect(self.set_workstation_locked)
            ev.power_resumed.connect(self.on_power_resume)
            ev.register_session_notifications()
            if self._hotkey_enabled:
                ev.register_hotkey()
            self._win_events = ev

    # -- properties -----------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def period(self) -> int:
        return self._period

    @property
    def distance(self) -> int:
        return self._distance

    @property
    def random_timer(self) -> bool:
        return self._random_timer

    @property
    def respect_locked_state(self) -> bool:
        return self._respect_locked_state

    @property
    def hotkey_enabled(self) -> bool:
        return self._hotkey_enabled

    @property
    def workstation_locked(self) -> bool:
        return self._workstation_locked

    @property
    def is_paused_locked(self) -> bool:
        return bool(self._enabled and self._respect_locked_state and self._workstation_locked)

    @property
    def is_active(self) -> bool:
        return bool(self._enabled and not (self._respect_locked_state and self._workstation_locked))

    @property
    def current_interval_s(self) -> int:
        return self._current_interval_s

    @property
    def hotkey_registered(self) -> bool:
        return bool(self._win_events is not None and self._win_events.hotkey_registered)

    @property
    def hotkey_registration_failed(self) -> bool:
        return bool(
            self._hotkey_enabled
            and self._win_events is not None
            and not self._win_events.hotkey_registered
        )

    # -- public controls ------------------------------------------------------
    def set_enabled(self, on: bool) -> None:
        on = bool(on)
        if on == self._enabled:
            return
        self._enabled = on
        self._apply_active_state()
        self.enabled_changed.emit(self._enabled)

    def toggle(self) -> None:
        self.set_enabled(not self._enabled)

    def configure(
        self,
        *,
        mode: Optional[str] = None,
        period: Optional[int] = None,
        distance: Optional[int] = None,
        random_timer: Optional[bool] = None,
        respect_locked_state: Optional[bool] = None,
        hotkey_enabled: Optional[bool] = None,
    ) -> None:
        mode_changed = False
        recompute = False
        lock_policy_changed = False

        if mode is not None:
            new_mode = coerce_mode(mode)
            if new_mode != self._mode:
                self._mode = new_mode
                mode_changed = True
                recompute = True

        if distance is not None:
            new_dist = clamp_distance(distance)
            if new_dist != self._distance:
                self._distance = new_dist
                recompute = True

        if recompute:
            self._pattern = compute_pattern(self._mode, self._distance)
            if mode_changed or self._step >= len(self._pattern):
                self._step = 0

        if period is not None:
            new_period = clamp_period(period)
            if new_period != self._period:
                self._period = new_period
                self._current_interval_s = new_period
                self._timer.setInterval(new_period * 1000)

        if random_timer is not None:
            new_rand = bool(random_timer)
            if new_rand != self._random_timer:
                self._random_timer = new_rand
                if not new_rand:
                    self._current_interval_s = self._period
                    self._timer.setInterval(self._period * 1000)

        if respect_locked_state is not None:
            new_respect = bool(respect_locked_state)
            if new_respect != self._respect_locked_state:
                self._respect_locked_state = new_respect
                lock_policy_changed = True

        if hotkey_enabled is not None:
            new_hk = bool(hotkey_enabled)
            if new_hk != self._hotkey_enabled:
                self._hotkey_enabled = new_hk
                if self._win_events is not None:
                    if new_hk:
                        self._win_events.register_hotkey()
                    else:
                        self._win_events.unregister_hotkey()

        if lock_policy_changed and self._enabled and self._workstation_locked:
            self._apply_active_state()
        else:
            self.status_changed.emit()

    def set_workstation_locked(self, locked: bool) -> None:
        locked = bool(locked)
        if locked == self._workstation_locked:
            return
        self._workstation_locked = locked
        if self._respect_locked_state and self._enabled:
            self._apply_active_state()
        else:
            self.status_changed.emit()

    def on_power_resume(self) -> None:
        """Restart timer and re-assert execution state after Modern Standby / sleep resume."""
        self._timer.stop()
        if self._enabled:
            self._apply_active_state()

    def pulse_preview(self, mode: Optional[str] = None, distance: Optional[int] = None) -> None:
        """Execute a short safe preview jiggle (and return pointer after 120 ms)."""
        self._finish_preview()
        m = coerce_mode(mode) if mode is not None else self._mode
        d = clamp_distance(distance) if distance is not None else self._distance
        pat = compute_pattern(m, d)
        dx, dy = pat[0]
        self._backend.jiggle(dx, dy)
        pos_after = self._backend.get_cursor_pos()
        if pos_after is not None:
            self._last_pos = pos_after
        if dx != 0 or dy != 0:
            self._pending_preview_return = (-dx, -dy)
            self._preview_timer.start()

    def status_summary(self) -> str:
        """Human-readable one-line status for UI and tray tooltip."""
        if not self._enabled:
            return "Inactive"
        if self.is_paused_locked:
            return "Paused \u2014 workstation locked"
        if self._random_timer:
            timing = f"1\u2013{self._period} s (next {self._current_interval_s} s)"
        else:
            timing = f"every {self._period} s"
        if self._mode == "Zen":
            return f"Active \u2014 {timing}, Zen"
        return f"Active \u2014 {timing}, {self._mode} (\u0394 {self._distance})"

    def tray_tooltip(self, base: str = "SM809 Pro \u2014 Custom Driver") -> str:
        """Tray tooltip text, safely bounded to avoid Win32 truncation."""
        if not self._enabled:
            return base
        text = f"{base}\nMouse Jiggler: {self.status_summary()}"
        if len(text) > 120:
            return text[:117] + "..."
        return text

    def shutdown(self) -> None:
        """Stop timers, clear sleep prevention, and tear down Win32 hooks."""
        self._timer.stop()
        self._finish_preview()
        if self._enabled or self._awake_asserted:
            self._backend.allow_sleep()
        self._enabled = False
        self._awake_asserted = False
        self._step = 0
        if self._win_events is not None:
            self._win_events.shutdown()
            self._win_events = None

    # -- internal helpers -----------------------------------------------------
    def _apply_active_state(self) -> None:
        if self.is_active:
            self._backend.stay_awake()
            self._awake_asserted = True
            self._step = 0
            self._last_pos = self._backend.get_cursor_pos()
            self._current_interval_s = self._period
            self._timer.setInterval(self._period * 1000)
            self._timer.start()
        else:
            self._timer.stop()
            self._step = 0
            self._backend.allow_sleep()
            self._awake_asserted = False
        self.status_changed.emit()

    def _finish_preview(self) -> None:
        self._preview_timer.stop()
        if self._pending_preview_return is not None:
            rx, ry = self._pending_preview_return
            self._pending_preview_return = None
            self._backend.jiggle(rx, ry)
            pos_after = self._backend.get_cursor_pos()
            if pos_after is not None:
                self._last_pos = pos_after

    def _on_tick(self) -> None:
        if not self.is_active:
            self._timer.stop()
            return

        # Re-assert every tick so Modern Standby / display-off never drops it silently.
        self._backend.stay_awake()

        # Skip if user moved the cursor since the last tick, then re-arm on next idle tick.
        pos = self._backend.get_cursor_pos()
        if pos is not None:
            moved = self._last_pos is not None and pos != self._last_pos
            self._last_pos = pos
            if moved:
                self._schedule_next_interval()
                return

        if self._step >= len(self._pattern):
            self._step = 0
        dx, dy = self._pattern[self._step]
        self._step = (self._step + 1) % len(self._pattern)

        self._backend.jiggle(dx, dy)
        pos_after = self._backend.get_cursor_pos()
        if pos_after is not None:
            self._last_pos = pos_after

        secs = self._schedule_next_interval()
        self.tick_completed.emit(secs)
        self.status_changed.emit()

    def _schedule_next_interval(self) -> int:
        if self._random_timer:
            secs = self._rng.randint(1, self._period)
        else:
            secs = self._period
        self._current_interval_s = secs
        self._timer.setInterval(secs * 1000)
        return secs
