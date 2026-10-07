"""
app.autoswitch -- per-app profile auto-switching (Milestone 3 step 3, the
headline feature; the official software has NO auto-switch).

Watches the foreground window and switches the active mouse profile by rule,
modelled on Razer Synapse's "base profile" behaviour:

- The user's MANUAL selection is the BASE profile (sticky, persisted).
- When the foreground app matches a profile's rule, switch to that profile
  (a temporary override).
- When focus moves to an app that matches NO rule, REVERT to the base profile.
- If the base profile itself matches the app, nothing visibly changes.

Rules live on each profile as `match_rules = [{"exe": "game.exe", "title": None},
...]`. First match in PROFILE LIST ORDER wins (reorder profiles to set priority).
A switch only fires when the target differs from what is currently applied, so a
steady foreground never re-pushes config to the device.

Foreground detection is behind an injectable `watcher` so the core logic is
testable headless and the OS-specific part can be swapped per platform (Windows
implemented; macOS/Linux land in the M3 step 6 port).
"""

import os
import time

from PySide6.QtCore import QObject, QTimer, Signal


# --- foreground-window detection --------------------------------------------
class ForegroundWatcher:
    """Returns (exe_basename_lower, window_title, full_path) for the focused
    window, or (None, None, None) if it can't be determined. Windows impl; other
    platforms return Nones until the port lands. The full path lets rules tell
    apart same-named exes (e.g. many UE/Unity games ship Client-Win64-Shipping.exe)."""

    def __init__(self):
        self._impl = _win_foreground if os.name == "nt" else _null_foreground

    def current(self):
        try:
            return self._impl()
        except Exception:
            return (None, None, None)


def _null_foreground():
    return (None, None, None)


def _win_foreground():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return (None, None, None)

    # window title
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value or ""

    # owning process id -> exe name
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    full_path = None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if handle:
        try:
            kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD,
                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            size = wintypes.DWORD(32768)
            nbuf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, nbuf, ctypes.byref(size)):
                full_path = nbuf.value
        finally:
            kernel32.CloseHandle(handle)
    exe = os.path.basename(full_path).lower() if full_path else None
    return (exe, title, full_path)


# --- rule matching (pure) ----------------------------------------------------
def rule_matches(rule, exe, title, path=None):
    """A rule matches when ALL of its specified (non-empty) conditions hold:
      - exe:   basename equals the foreground exe (case-insensitive)
      - path:  substring of the foreground full path (case-insensitive) -- this
               distinguishes same-named exes (e.g. UE/Unity Client-Win64-Shipping.exe)
      - title: substring of the foreground window title (case-insensitive)
    A rule with no conditions set never matches."""
    want_exe = (rule.get("exe") or "").strip().lower()
    want_path = (rule.get("path") or "").strip().lower()
    want_title = (rule.get("title") or "").strip().lower()
    if not (want_exe or want_path or want_title):
        return False
    if want_exe and (not exe or exe.lower() != want_exe):
        return False
    if want_path and (not path or want_path not in path.lower()):
        return False
    if want_title and (not title or want_title not in title.lower()):
        return False
    return True


def match_profile(profiles, exe, title, path=None):
    """First profile (in list order) with a rule matching the foreground, or None."""
    for p in profiles:
        for r in p.get("match_rules", []):
            if rule_matches(r, exe, title, path):
                return p["id"]
    return None


# --- the switcher ------------------------------------------------------------
class AutoSwitcher(QObject):
    """Polls the foreground window and requests profile switches.

    Wiring: `apply` is called with a profile id when a switch should happen;
    `get_applied` returns the id of the profile currently on the device (so we
    skip redundant re-applies). The base profile is set via set_base() whenever
    the user manually picks a profile.
    """

    switched = Signal(str)        # emitted with the profile id we switched TO

    def __init__(self, store, apply, get_applied, watcher=None,
                 interval_ms=200, debounce_ms=200, parent=None):
        super().__init__(parent)
        self._store = store
        self._apply = apply
        self._get_applied = get_applied
        self._watcher = watcher or ForegroundWatcher()
        self._base_id = None
        self._enabled = False
        # debounce: apply only after the target stays put for this long, so fast
        # alt-tabbing through apps doesn't flood the (stateful) device with a full
        # profile-apply per transient window. 0 = switch immediately.
        self._debounce_ms = debounce_ms
        self._pending = None          # candidate target awaiting the debounce
        self._pending_since = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll)

    def set_base(self, pid):
        """The manually-selected, sticky profile to revert to on no-match."""
        self._base_id = pid

    @property
    def base_id(self):
        return self._base_id

    def set_enabled(self, on):
        self._enabled = bool(on)
        self._pending = None
        if self._enabled:
            self._timer.start()
            self.poll()                     # start watching (debounce still applies)
        else:
            self._timer.stop()
            # leaving auto-switch reverts to the manual base profile
            if self._base_id and self._get_applied() != self._base_id:
                self._switch(self._base_id)

    def is_enabled(self):
        return self._enabled

    def poll(self):
        if not self._enabled:
            return
        exe, title, path = self._watcher.current()
        target = match_profile(self._store.all(), exe, title, path) or self._base_id
        # already on the right profile -> nothing pending
        if not target or target == self._get_applied():
            self._pending = None
            return
        if self._debounce_ms <= 0:
            self._pending = None
            self._switch(target)
            return
        # debounce: only switch once the target has been stable long enough, so
        # rapid app-switching collapses to a single apply on the app you land on
        now = time.monotonic()
        if target != self._pending:
            self._pending = target
            self._pending_since = now
            return
        if (now - self._pending_since) * 1000.0 >= self._debounce_ms:
            self._pending = None
            self._switch(target)

    def _switch(self, pid):
        self._apply(pid)
        self.switched.emit(pid)
