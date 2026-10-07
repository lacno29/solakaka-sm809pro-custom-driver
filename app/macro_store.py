"""
app.macro_store -- the host-side macro LIBRARY (named macros, no slots).

Mirrors how the official software works: macros live in a host-side library
(its MacroLibraryFile.mlf), and a device SLOT is assigned only when a macro is
bound to a button. So the library here is unlimited; slot assignment + upload
happen at bind time (see MainWindow._resolve_bindings / device.apply_macro_buttons).

Each macro: {"id": <8-hex>, "name": str, "events": [..]} in the sm809pro.macros
event format. Persisted to JSON so the library survives restarts (a focused
preview of the Milestone 3 profile store, which will later absorb this).
"""

import json
import os
import uuid


def default_path():
    # Portable: <app dir>/config/macros.json -- the project root from source, or
    # next to the .exe when frozen (see app.paths), so config travels with the app.
    from .paths import app_dir
    return os.path.join(app_dir(), "config", "macros.json")


class MacroStore:
    def __init__(self, path=None):
        self.path = path or default_path()
        self._macros = []          # list of {"id","name","events"}
        self.load()

    # -- persistence ----------------------------------------------------------
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._macros = [
                    {"id": str(m.get("id") or uuid.uuid4().hex[:8]),
                     "name": str(m.get("name", "Macro")),
                     "events": list(m.get("events", []))}
                    for m in data if isinstance(m, dict)
                ]
        except Exception:
            self._macros = []

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._macros, f, indent=2)
        except Exception:
            pass

    # -- queries --------------------------------------------------------------
    def all(self):
        return list(self._macros)

    def get(self, mid):
        return next((m for m in self._macros if m["id"] == mid), None)

    def index_of(self, mid):
        for i, m in enumerate(self._macros):
            if m["id"] == mid:
                return i
        return -1

    # -- mutations (each persists) -------------------------------------------
    def add(self, name=None):
        m = {"id": uuid.uuid4().hex[:8], "name": name or "New Macro", "events": []}
        self._macros.append(m)
        self.save()
        return m

    def delete(self, mid):
        self._macros = [m for m in self._macros if m["id"] != mid]
        self.save()

    def rename(self, mid, name):
        m = self.get(mid)
        if m is not None:
            m["name"] = name
            self.save()

    def set_events(self, mid, events):
        m = self.get(mid)
        if m is not None:
            m["events"] = list(events)
            self.save()
