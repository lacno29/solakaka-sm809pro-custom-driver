"""
app.profile_store -- host-side PROFILE library (Milestone 3 step 1).

The SM809 Pro is write-only for config: it never reports its stored button map /
DPI / colors / lighting back (only live STATUS is pushed on Col04). So, exactly
like the official software's .psf profiles, the host must own the source of
truth. This store persists full config snapshots to JSON so settings -- crucially
the button BINDINGS -- survive restarts (M2 only persisted the macro library).

Mirrors app/macro_store.py: same default_path() under <root>/config/, same
load/save-on-mutate CRUD, same silent-fail persistence.

A profile:
    {
      "id": <8-hex>,
      "name": str,
      "match_rules": [ {"exe": str|None, "title": str|None}, ... ],  # M3 step 3
      "config": {                       # full device config snapshot
        "buttons": [ <16 entries> ],    # 3-byte tuples OR {"macro":id,..} dicts
        "dpi": {"values":[..], "colors":[[r,g,b],..], "enabled_count":int, "selected":int},
        "polling_hz": int,
        "lod_mm": int,
        "lighting": {"mode": int, "color": [r,g,b]},
        "power": {"sleep_min": int, "move_wakeup": bool, "move_lighting": bool},
        "sensor": {"angle_snap": bool, "motion_sync": bool, "ripple": bool},
      }
    }

On disk: {"active": <id|None>, "profiles": [ <profile>, ... ]}.
"""

import json
import os
import uuid

from sm809pro import defaults as D


def default_path():
    # Portable: <app dir>/config/profiles.json (next to macros.json) -- project
    # root from source, or next to the .exe when frozen (see app.paths).
    from .paths import app_dir
    return os.path.join(app_dir(), "config", "profiles.json")


def default_config():
    """A full config snapshot equal to the factory defaults (sm809pro.defaults).
    Used to seed the first profile so a fresh install has a sane baseline."""
    n = D.DPI_ENABLED_COUNT
    return {
        "buttons": [list(c) for c in D.button_codes()],
        "dpi": {
            "values": list(D.DPI_VALUES[:n]),
            "colors": [list(c) for c in D.DPI_COLORS[:n]],
            "enabled_count": n,
            "selected": D.DPI_SELECTED,
        },
        "polling_hz": D.POLLING_HZ,
        "lod_mm": D.LOD_MM,
        "lighting": {"mode": D.LIGHTING_MODE, "color": list(D.LIGHTING_COLOR)},
        "power": {
            "sleep_min": D.POWER_SLEEP_MIN,
            "move_wakeup": D.POWER_MOVE_WAKEUP,
            "move_lighting": D.POWER_MOVE_LIGHTING,
        },
        "sensor": {
            "angle_snap": D.SENSOR_ANGLE_SNAP,
            "motion_sync": D.SENSOR_MOTION_SYNC,
            "ripple": D.SENSOR_RIPPLE,
        },
    }


class ProfileStore:
    def __init__(self, path=None):
        self.path = path or default_path()
        self._profiles = []        # list of profile dicts
        self._active = None        # active (manual/base) profile id
        self._settings = {}        # app-level settings (e.g. auto-switch on)
        self._seq = 0              # monotonic counter for "created" ordering
        self.load()

    # -- persistence ----------------------------------------------------------
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            profiles = data.get("profiles", []) if isinstance(data, dict) else []
            self._profiles = [self._coerce(p) for p in profiles if isinstance(p, dict)]
            self._active = data.get("active") if isinstance(data, dict) else None
            self._settings = dict(data.get("settings", {})) if isinstance(data, dict) else {}
        except Exception:
            self._profiles = []
            self._active = None
            self._settings = {}
        if not self._profiles:
            # seed a baseline "Default" profile so the app always has one
            self._profiles = [self._coerce({"name": "Default",
                                            "config": default_config()})]
            self._active = self._profiles[0]["id"]
            self.save()
        elif self._active not in {p["id"] for p in self._profiles}:
            self._active = self._profiles[0]["id"]
        # assign a "created" order-key to any profile missing one (older = lower),
        # and advance the seq counter past the highest so new profiles sort latest
        for i, p in enumerate(self._profiles):
            if not isinstance(p.get("created"), (int, float)):
                p["created"] = i
        self._seq = max([p["created"] for p in self._profiles], default=0)

    def _coerce(self, p):
        return {
            "id": str(p.get("id") or uuid.uuid4().hex[:8]),
            "name": str(p.get("name", "Profile")),
            "match_rules": list(p.get("match_rules", [])),
            "config": dict(p.get("config") or default_config()),
            "created": p.get("created"),
        }

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"active": self._active, "profiles": self._profiles,
                           "settings": self._settings}, f, indent=2)
        except Exception:
            pass

    # -- app-level settings ---------------------------------------------------
    def get_setting(self, key, default=None):
        return self._settings.get(key, default)

    def set_setting(self, key, value):
        self._settings[key] = value
        self.save()

    # -- queries --------------------------------------------------------------
    def all(self):
        return list(self._profiles)

    def get(self, pid):
        return next((p for p in self._profiles if p["id"] == pid), None)

    def index_of(self, pid):
        for i, p in enumerate(self._profiles):
            if p["id"] == pid:
                return i
        return -1

    @property
    def active_id(self):
        return self._active

    def active(self):
        return self.get(self._active)

    # -- mutations (each persists) -------------------------------------------
    def set_active(self, pid):
        if self.get(pid) is not None:
            self._active = pid
            self.save()

    def unique_name(self, name, exclude_id=None):
        """Return `name`, or `name (1)` / `name (2)` ... if it collides with an
        existing profile (case-insensitive). Profile names are kept unique."""
        name = (name or "Profile").strip() or "Profile"
        existing = {p["name"].lower() for p in self._profiles if p["id"] != exclude_id}
        if name.lower() not in existing:
            return name
        i = 1
        while f"{name} ({i})".lower() in existing:
            i += 1
        return f"{name} ({i})"

    def add(self, name=None, config=None, match_rules=None):
        self._seq += 1
        p = self._coerce({"name": self.unique_name(name or "New Profile"),
                          "config": config or default_config(),
                          "match_rules": match_rules or [], "created": self._seq})
        self._profiles.append(p)
        self.save()
        return p

    def reorder(self, ids):
        """Reorder profiles to match the given id list (drag-to-arrange). Ids not
        present are ignored; any profile missing from `ids` keeps its tail order."""
        rank = {pid: i for i, pid in enumerate(ids)}
        self._profiles.sort(key=lambda p: rank.get(p["id"], len(rank)))
        self.save()

    def sort_by(self, key):
        """Apply a predefined sort to the stored order (which is also the
        auto-switch match priority). key: az|za|latest|oldest (else no change)."""
        if key == "az":
            self._profiles.sort(key=lambda p: p["name"].lower())
        elif key == "za":
            self._profiles.sort(key=lambda p: p["name"].lower(), reverse=True)
        elif key == "latest":
            self._profiles.sort(key=lambda p: p.get("created") or 0, reverse=True)
        elif key == "oldest":
            self._profiles.sort(key=lambda p: p.get("created") or 0)
        else:
            return
        self.save()

    def duplicate(self, pid, name=None):
        src = self.get(pid)
        if src is None:
            return None
        # deep-ish copy via JSON round-trip (config is plain JSON data)
        cfg = json.loads(json.dumps(src["config"]))
        rules = json.loads(json.dumps(src["match_rules"]))
        return self.add(name=name or f"{src['name']} copy", config=cfg,
                        match_rules=rules)

    def delete(self, pid):
        self._profiles = [p for p in self._profiles if p["id"] != pid]
        if not self._profiles:
            # never leave the store empty; reseed a Default
            self._profiles = [self._coerce({"name": "Default",
                                            "config": default_config()})]
        if self._active == pid:
            self._active = self._profiles[0]["id"]
        self.save()

    def rename(self, pid, name):
        p = self.get(pid)
        if p is not None:
            p["name"] = self.unique_name(name, exclude_id=pid)
            self.save()

    def set_config(self, pid, config):
        p = self.get(pid)
        if p is not None:
            p["config"] = dict(config)
            self.save()

    def set_match_rules(self, pid, rules):
        p = self.get(pid)
        if p is not None:
            p["match_rules"] = list(rules)
            self.save()
