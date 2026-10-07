"""
app.autostart -- "Start with Windows" (launch at login).

Uses the per-user registry Run key
(HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run) so no admin rights are
needed. The registered command launches with `--minimized` so the app goes
straight to the tray on login. Windows-only; no-ops elsewhere.
"""

import os
import sys

from .paths import app_dir, is_frozen

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "SM809Pro"


def supported():
    return os.name == "nt"


def launch_command():
    """The command Windows runs at login (quoted; starts minimized to tray)."""
    if is_frozen():
        return f'"{os.path.abspath(sys.executable)}" --minimized'
    # from source: prefer pythonw.exe (no console window) running run_app.py
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    if os.path.exists(pyw):
        py = pyw
    script = os.path.join(app_dir(), "run_app.py")
    return f'"{py}" "{script}" --minimized'


def is_enabled():
    if not supported():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, APP_NAME)
            return bool(value)
    except OSError:
        return False


def set_enabled(on):
    """Register/unregister the login entry. Returns True on success."""
    if not supported():
        return False
    try:
        import winreg
        if on:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
