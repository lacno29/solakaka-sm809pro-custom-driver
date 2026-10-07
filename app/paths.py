"""
app.paths -- frozen-aware filesystem paths.

Works both when run from source and when bundled by PyInstaller:

- `app_dir()` is where PORTABLE user data (config/) lives. When frozen it's the
  folder containing the .exe, so config travels with the app and survives across
  runs (NOT the ephemeral PyInstaller extraction dir). From source it's the
  project root.
- `resource_path(*parts)` resolves a bundled READ-ONLY resource (e.g. images/),
  using PyInstaller's `sys._MEIPASS` extraction dir when frozen, else the project
  root.
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def app_dir():
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return _PROJECT_ROOT


def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", None) or _PROJECT_ROOT
    return os.path.join(base, *parts)
