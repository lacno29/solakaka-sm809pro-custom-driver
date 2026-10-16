"""
app.main_window -- the application shell.

Top bar (device name + connection pill + battery/charge + live DPI readout), a
left navigation rail with a Reset-to-Factory action in its footer, and a stacked
set of panels. Owns the DeviceController and routes its signals to the UI,
including battery % and online/offline state.

Nav order (user-chosen): Buttons, Macro, DPI, Lighting, Performance.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget,
    QListWidgetItem, QStackedWidget, QFrame, QLabel, QPushButton, QMessageBox,
    QSizePolicy, QAbstractItemView, QComboBox, QInputDialog, QMenu,
    QFileDialog, QSystemTrayIcon, QDialog, QCheckBox, QSlider, QDialogButtonBox,
    QGroupBox,
)

from . import theme
from .controller import DeviceController
from sm809pro import actions as A
from .panels.dpi_panel import DpiPanel
from .panels.buttons_panel import ButtonsPanel
from .panels.lighting_panel import LightingPanel
from .panels.performance_panel import PerformancePanel
from .panels.macro_panel import MacroPanel
from .panels.autoswitch_panel import AutoSwitchPanel
from .panels.profiles_panel import ProfilesPanel
from .macro_store import MacroStore
from .profile_store import ProfileStore, default_config
from .autoswitch import AutoSwitcher
from .widgets.overlay import Overlay, AlertOverlay, POSITIONS, POSITION_LABELS
from .paths import resource_path
from .widgets.action_picker import set_macro_resolver

# nav order requested by the user
NAV_ITEMS = ["Buttons", "Macro", "DPI", "Lighting", "Performance", "Auto-Switch",
             "Profiles"]


def app_icon():
    """The application icon (window / taskbar / tray), bundled at
    images/icon.ico (resolved frozen-safe via _MEIPASS)."""
    return QIcon(resource_path("images", "icon.ico"))


class Placeholder(QWidget):
    """A simple 'coming soon' panel for sections not yet built."""
    def __init__(self, name):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)
        t = QLabel(name)
        t.setProperty("panelTitle", "true")
        lay.addWidget(t)
        s = QLabel("This panel is coming soon.")
        s.setProperty("panelSubtitle", "true")
        lay.addWidget(s)
        lay.addStretch(1)


class TopBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("topbar")
        self.setFixedHeight(56)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(12)

        self.name = QLabel("SOLAKAKA SM809 Pro - Custom Driver")
        self.name.setObjectName("deviceName")
        lay.addWidget(self.name)

        lay.addStretch(1)

        # upload spinner: visible only while a config write is in flight
        self.spinner = QLabel("")
        self.spinner.setObjectName("spinner")
        lay.addWidget(self.spinner)
        self._spin_frames = [chr(c) for c in
                             (0x280B, 0x2819, 0x2839, 0x2838, 0x283C,
                              0x2834, 0x2826, 0x2827, 0x2807, 0x280F)]
        self._spin_i = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(80)
        self._spin_timer.timeout.connect(self._tick_spinner)

        # connection indicator (grouped on the right with the live stats)
        self.conn_pill = QLabel("connecting…")
        lay.addWidget(self.conn_pill)
        self.conn_pill.setStyleSheet(self._conn_style(theme.TEXT_DIM))

        # battery / charge status
        self.battery = QLabel("")
        self.battery.setObjectName("battery")
        lay.addWidget(self.battery)

        # live stat groups: each is a tight caption+value unit so the groups
        # sit at even spacing across the bar (no stray spacer)
        rate_group, self.rate_readout = self._stat("POLLING RATE", "rateReadout")
        lay.addWidget(rate_group)
        dpi_group, self.dpi_readout = self._stat("DPI", "dpiReadout")
        lay.addWidget(dpi_group)

    def _conn_style(self, color):
        # match the battery readout: plain mono text, 12px, no pill background
        return f"color: {color}; font-family: {theme.FONT_MONO}; font-size: 12px;"

    def _stat(self, caption, value_obj_name):
        # a tightly-spaced caption+value pair; the bar then spaces groups evenly
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        cap = QLabel(caption)
        cap.setProperty("unit", "true")
        val = QLabel("—")
        val.setObjectName(value_obj_name)
        h.addWidget(cap)
        h.addWidget(val)
        return w, val

    def set_connection(self, info):
        conn = info.get("connection", "?")
        label = {"2.4GHz": "2.4 GHz", "wired": "USB Wired", "bluetooth": "Bluetooth"}.get(conn, conn)
        self.conn_pill.setText(f"● {label}")
        self.conn_pill.setStyleSheet(self._conn_style(theme.GOOD))
        self._conn_label = label
        if not info.get("configurable", True):
            self.conn_pill.setToolTip(f"Connected via {label} (read-only; settings changes require 2.4GHz dongle or USB wired)")
        else:
            self.conn_pill.setToolTip(f"Connected via {label}")

    def set_offline(self):
        # dongle/cable present but the mouse isn't responding
        self.conn_pill.setText("● mouse offline")
        self.conn_pill.setStyleSheet(self._conn_style(theme.WARN))
        self.conn_pill.setToolTip("2.4GHz dongle is plugged in, but mouse is offline or switched to Bluetooth.")
        self.battery.setText("")
        self.dpi_readout.setText("—")
        self.rate_readout.setText("—")

    def set_disconnected(self):
        self.conn_pill.setText("● not connected")
        self.conn_pill.setStyleSheet(self._conn_style(theme.BAD))
        self.conn_pill.setToolTip("Mouse not detected. Searching for connection…")
        self.battery.setText("")
        self.dpi_readout.setText("—")
        self.rate_readout.setText("—")

    def set_error(self, msg):
        self.conn_pill.setText("● not connected")
        self.conn_pill.setStyleSheet(self._conn_style(theme.BAD))
        self.conn_pill.setToolTip(msg)

    def set_battery(self, percent, charging=False):
        if percent is None:
            self.battery.setText("")
            return
        icon = "⚡" if charging else "▮"
        color = theme.GOOD if percent > 40 else theme.WARN if percent > 15 else theme.BAD
        if charging:
            color = theme.ACCENT_2
        self.battery.setText(f"{icon} {percent}%")
        self.battery.setStyleSheet(f"color: {color}; font-family: {theme.FONT_MONO}; font-size: 12px;")

    def set_dpi_readout(self, text):
        self.dpi_readout.setText(text)

    def set_busy(self, busy):
        if busy:
            if not self._spin_timer.isActive():
                self._spin_timer.start()
                self._tick_spinner()
        else:
            self._spin_timer.stop()
            self.spinner.setText("")

    def _tick_spinner(self):
        self._spin_i = (self._spin_i + 1) % len(self._spin_frames)
        self.spinner.setText(f"{self._spin_frames[self._spin_i]} applying...")
        self.spinner.setStyleSheet(f"color: {theme.ACCENT_2};")

    def set_rate_readout(self, hz):
        self.rate_readout.setText(f"{hz}" if hz is not None else "—")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SOLAKAKA SM809 Pro - Custom Driver")
        self.setWindowIcon(app_icon())
        self.resize(1000, 680)
        self.setMinimumSize(820, 560)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # profile store (host-side source of truth; makes bindings persist)
        self.profiles = ProfileStore()
        self._current_config = None
        self._loading_profile = False
        self._profile_mru = []      # recently-active profile ids (most-recent first)

        self.topbar = TopBar()
        outer.addWidget(self.topbar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # ---- left rail: full-height surface; nav at top, reset near bottom ----
        rail = QFrame()
        rail.setObjectName("railFrame")
        rail.setFixedWidth(180)
        rail.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        rail_lay = QVBoxLayout(rail)
        rail_lay.setContentsMargins(0, 0, 0, 0)
        rail_lay.setSpacing(0)

        # profile selector at the top of the rail
        rail_lay.addWidget(self._build_profile_bar())

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFrameShape(QFrame.NoFrame)
        for name in NAV_ITEMS:
            QListWidgetItem(name, self.nav)
        self.nav.currentRowChanged.connect(self._on_nav)
        # the list shows all items and sizes to fit (it never scrolls); the rail
        # frame provides the full-height background behind it
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.nav.setSelectionMode(QAbstractItemView.SingleSelection)
        rail_lay.addWidget(self.nav, 0)

        # push the reset button down toward the bottom of the rail
        rail_lay.addStretch(1)

        sep = QFrame()
        sep.setProperty("sep", "true")
        sep.setFrameShape(QFrame.NoFrame)
        rail_lay.addWidget(sep)
        rail_lay.addSpacing(10)

        self.reset_btn = QPushButton("Reset to Factory")
        self.reset_btn.setObjectName("resetBtn")
        self.reset_btn.clicked.connect(self._confirm_reset)
        rail_lay.addWidget(self.reset_btn, 0)
        rail_lay.addSpacing(14)

        body.addWidget(rail)

        # now that items/styles exist, size the nav to exactly fit its rows
        self._fit_nav_height()

        # ---- stacked panels (order matches NAV_ITEMS) ----
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)

        self.store = MacroStore()
        set_macro_resolver(lambda mid: (self.store.get(mid) or {}).get("name", "Macro"))
        self.buttons_panel = ButtonsPanel(get_macros=self.store.all)
        self.macro_panel = MacroPanel(self.store)
        self.dpi_panel = DpiPanel()
        self.lighting_panel = LightingPanel()
        self.performance_panel = PerformancePanel()
        self.autoswitch_panel = AutoSwitchPanel()
        self.profiles_panel = ProfilesPanel()
        self.stack.addWidget(self.buttons_panel)         # 0 Buttons
        self.stack.addWidget(self.macro_panel)            # 1 Macro
        self.stack.addWidget(self.dpi_panel)              # 2 DPI
        self.stack.addWidget(self.lighting_panel)         # 3 Lighting
        self.stack.addWidget(self.performance_panel)      # 4 Performance
        self.stack.addWidget(self.autoswitch_panel)       # 5 Auto-Switch
        self.stack.addWidget(self.profiles_panel)         # 6 Profiles
        self.nav.setCurrentRow(0)

        # ---- controller ----
        self.ctrl = DeviceController()
        self.ctrl.connected.connect(self._on_connected)
        self.ctrl.disconnected.connect(self.topbar.set_disconnected)
        self.ctrl.error.connect(self._on_error)
        self.ctrl.dpi_level_changed.connect(self._on_dpi_push)
        self.ctrl.rate_changed.connect(self._on_rate_push)
        self.ctrl.battery_changed.connect(self._on_battery)
        self.ctrl.charging_changed.connect(self._on_charging)
        self.ctrl.alive_changed.connect(self._on_alive)
        self.ctrl.runapp_pressed.connect(self._on_runapp)
        self.ctrl.command_done.connect(self._on_command_done)
        self.ctrl.busy_changed.connect(self.topbar.set_busy)
        self.ctrl.busy_changed.connect(self._on_busy_overlay)

        self.dpi_panel.apply_requested.connect(self._apply_dpi)
        self.dpi_panel.active_dpi_requested.connect(self._apply_active_dpi)
        self.buttons_panel.apply_requested.connect(self._apply_buttons)
        self.lighting_panel.apply_requested.connect(self._apply_lighting)
        self.performance_panel.polling_changed.connect(self._apply_polling)
        self.performance_panel.lod_changed.connect(self._apply_lod)
        self.performance_panel.power_changed.connect(self._apply_power)
        self.performance_panel.sensor_changed.connect(self._apply_sensor)
        self.macro_panel.library_changed.connect(self._on_library_changed)
        self.autoswitch_panel.enable_toggled.connect(self._toggle_autoswitch)
        self.autoswitch_panel.rules_changed.connect(self._on_rules_changed)
        self.autoswitch_panel.app_detected.connect(self._on_app_detected)
        self.profiles_panel.profile_selected.connect(self._select_profile)
        self.profiles_panel.order_changed.connect(self._on_profile_reorder)
        self.profiles_panel.sort_changed.connect(self._on_profile_sort)
        self.profiles_panel.new_requested.connect(self._profile_new)
        self.profiles_panel.duplicate_requested.connect(self._profile_duplicate)
        self.profiles_panel.rename_requested.connect(self._profile_rename)
        self.profiles_panel.delete_requested.connect(self._profile_delete)
        self.profiles_panel.import_requested.connect(self._profile_import_psf)

        self._charging = False
        self._battery = None

        # debounce a device re-sync when a bound macro's body is edited
        self._macro_resync = QTimer(self)
        self._macro_resync.setSingleShot(True)
        self._macro_resync.setInterval(500)
        self._macro_resync.timeout.connect(self._resync_macros)

        # seed every panel from the active profile (display only; the device is
        # pushed once it connects, see _on_connected). This is what makes button
        # bindings + all settings survive restarts.
        active = self.profiles.active()
        self._applied_id = active["id"] if active else None   # what's on the device
        if active is not None:
            self._current_config = dict(active["config"])
            self._seed_panels(self._current_config)
        self._refresh_profile_combo()

        # on-screen overlay HUD (optional): flashes DPI / profile / rate changes.
        # A separate AlertOverlay handles persistent battery alerts.
        self.overlay = Overlay()
        self.alert_overlay = AlertOverlay()
        self._overlay_enabled = bool(self.profiles.get_setting("overlay", False))
        self._overlay_show = dict(self.profiles.get_setting(
            "overlay_show", {"profile": True, "dpi": True, "rate": False}))
        self._apply_overlay_appearance()
        self._prev_dpi_level = None
        self._prev_rate = None
        self._prev_overlay_pid = self._applied_id
        self._overlay_pending = False    # flash the overlay when an apply finishes
        # current live values the overlay can show together
        self._cur_dpi = None
        self._cur_rate = None
        self._cur_profile = active["name"] if active else None
        # battery-alert state (persistent alerts at 20%/10% + fully-charged)
        self._batt_alerted = set()      # thresholds already alerted (re-arm on recharge)
        self._full_alerted = False

        # per-app auto-switch (the headline feature). Base = the manual profile;
        # see app/autoswitch.py. Apply by id WITHOUT changing the manual base.
        self._auto = AutoSwitcher(self.profiles, self._apply_by_id,
                                  lambda: self._applied_id)
        self._auto.set_base(self._applied_id)
        self._auto.switched.connect(self._on_auto_switched)
        self._setup_tray()
        if self.profiles.get_setting("auto_switch", False):
            self._auto.set_enabled(True)
            self._sync_autoswitch_ui(True)
        self._sync_overlay_ui(self._overlay_enabled)

        self.ctrl.start()

    # -- nav ------------------------------------------------------------------
    def _fit_nav_height(self):
        """Set the nav list's height to exactly fit all rows (no scrolling)."""
        n = self.nav.count()
        if n == 0:
            return
        row_h = self.nav.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 40
        # list has 8px top+bottom padding from the stylesheet; add a little slack
        total = row_h * n + 16 + 4
        self.nav.setFixedHeight(total)

    def _on_nav(self, row):
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    # -- profiles -------------------------------------------------------------
    def _build_profile_bar(self):
        """A compact profile QUICK-SWITCH combo pinned at the top of the nav rail.
        Profile management (New/Duplicate/Rename/Delete/Import) lives in the
        Profiles tab."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 14, 12, 10)
        lay.setSpacing(6)
        cap = QLabel("PROFILE")
        cap.setProperty("unit", "true")
        lay.addWidget(cap)

        self.profile_combo = QComboBox()
        self.profile_combo.setObjectName("profileCombo")
        self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        lay.addWidget(self.profile_combo)
        return w

    def _refresh_profile_combo(self):
        """Rebuild the combo from the store without triggering a profile apply."""
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        active_idx = 0
        for i, p in enumerate(self.profiles.all()):
            self.profile_combo.addItem(p["name"], p["id"])
            if p["id"] == self.profiles.active_id:
                active_idx = i
        self.profile_combo.setCurrentIndex(active_idx)
        self.profile_combo.blockSignals(False)
        # keep the Auto-Switch + Profiles tabs in sync
        if hasattr(self, "autoswitch_panel"):
            self.autoswitch_panel.set_profiles(self.profiles.all(),
                                               self.profiles.active_id)
        if hasattr(self, "profiles_panel"):
            self.profiles_panel.set_profiles(
                self.profiles.all(), self.profiles.active_id,
                self.profiles.get_setting("profile_sort", "custom"))

    def _on_profile_reorder(self, ids):
        self.profiles.reorder(ids)
        self.profiles.set_setting("profile_sort", "custom")
        self._refresh_profile_combo()
        if self._auto is not None and self._auto.is_enabled():
            self._auto.poll()      # match priority changed -> re-evaluate

    def _on_profile_sort(self, key):
        self.profiles.sort_by(key)
        self.profiles.set_setting("profile_sort", key)
        self._refresh_profile_combo()
        if self._auto is not None and self._auto.is_enabled():
            self._auto.poll()

    def _on_rules_changed(self, pid, rules):
        self.profiles.set_match_rules(pid, rules)
        if getattr(self, "_auto", None) is not None and self._auto.is_enabled():
            self._auto.poll()   # let a just-added rule take effect immediately

    def _on_app_detected(self, exe, title):
        """Flash the on-screen overlay to confirm what 'Detect app' captured --
        shown even if the overlay is otherwise disabled (the user explicitly
        asked to detect), and inheriting the overlay's appearance settings."""
        lines = [("Detected App", exe)]
        if title:
            lines.append(("Window", title if len(title) <= 28 else title[:27] + "…"))
        self.overlay.flash_lines(lines)

    def _on_profile_selected(self, idx):
        # a MANUAL selection from the combo -> this becomes the sticky base
        if idx < 0:
            return
        pid = self.profile_combo.itemData(idx)
        if self.profiles.get(pid) is None:
            return
        self._select_profile(pid)

    def _select_profile(self, pid):
        """Manually activate a profile: it becomes the auto-switch base AND is
        applied to the device. Records the profile we're leaving in the MRU so a
        later delete can fall back to it (alt-tab style)."""
        prev = self.profiles.active_id
        if prev and prev != pid:
            self._profile_mru = [prev] + [x for x in self._profile_mru if x not in (prev, pid)]
        self.profiles.set_active(pid)
        if getattr(self, "_auto", None) is not None:
            self._auto.set_base(pid)
        self._apply_by_id(pid)

    def _apply_by_id(self, pid):
        """Apply the profile `pid` to panels + device and mark it as what's
        currently on the device. Does NOT change the manual base (so auto-switch
        overrides revert correctly). Updates the combo display silently."""
        prof = self.profiles.get(pid)
        if prof is None:
            return
        changed = (pid != self._applied_id)
        self._applied_id = pid
        self._sync_combo(pid)
        self._cur_profile = prof["name"]
        if (self._overlay_enabled and self._overlay_show.get("profile", True)
                and changed and pid != self._prev_overlay_pid):
            # immediate "Switching to X" feedback while the writes are in flight
            # (useful when auto-switching from a fullscreen game); the detailed
            # card replaces it once the apply finishes (_on_busy_overlay).
            self.overlay.flash_lines([("Switching to", prof["name"])], hold_ms=5000)
            self._overlay_pending = True
        self._prev_overlay_pid = pid
        self.apply_profile(prof["config"])

    def _overlay_flash(self):
        """Flash the overlay showing every ENABLED field's current value."""
        if not self._overlay_enabled:
            return
        show = self._overlay_show
        lines = []
        if show.get("profile", True) and self._cur_profile:
            lines.append(("Profile", self._cur_profile))
        if show.get("dpi", True) and self._cur_dpi is not None:
            lines.append(("DPI", self._cur_dpi))
        if show.get("rate", False) and self._cur_rate is not None:
            lines.append(("Polling Rate", f"{self._cur_rate} Hz"))
        if lines:
            self.overlay.flash_lines(lines)

    def _on_busy_overlay(self, busy):
        """When the device write queue drains after a profile apply, flash the
        overlay -- so it confirms the profile is DONE applying, not just queued."""
        if not busy and self._overlay_pending:
            self._overlay_pending = False
            self._overlay_flash()

    def _apply_overlay_appearance(self):
        """Push the saved overlay appearance settings to BOTH overlays (the
        transient HUD and the persistent battery alert)."""
        kw = dict(
            position=self.profiles.get_setting("overlay_pos", "bottom-center"),
            opacity_pct=self.profiles.get_setting("overlay_opacity", 92),
            scale_pct=self.profiles.get_setting("overlay_scale", 100),
            hold_ms=self.profiles.get_setting("overlay_hold", 1400),
            follow_cursor=self.profiles.get_setting("overlay_follow_cursor", True),
            monitor_index=self.profiles.get_setting("overlay_monitor", 0))
        self.overlay.set_appearance(**kw)
        self.alert_overlay.set_appearance(**kw)   # ignores hold_ms

    def _check_battery_alerts(self, pct):
        """Persistent, manually-dismissed alerts: low at 20%/10% (once per
        downward crossing, re-armed on recharge) + fully-charged while charging."""
        if pct is None:
            return
        # keep only thresholds we're still at/below (rising back above re-arms them)
        self._batt_alerted = {t for t in self._batt_alerted if pct <= t}
        for th in (10, 20):                       # most-critical first; show one
            if pct <= th and th not in self._batt_alerted:
                self._batt_alerted.add(th)
                if th == 10:
                    self.alert_overlay.alert("Battery Critically Low", f"{pct}%", theme.BAD)
                else:
                    self.alert_overlay.alert("Battery Low", f"{pct}%", theme.WARN)
                break
        # fully charged (while charging)
        if self._charging and pct >= 100:
            if not self._full_alerted:
                self._full_alerted = True
                self.alert_overlay.alert("Fully Charged", "100%", theme.GOOD)
        else:
            self._full_alerted = False

    def _sync_combo(self, pid):
        """Point the combo at `pid` without triggering a manual selection."""
        self.profile_combo.blockSignals(True)
        for i in range(self.profile_combo.count()):
            if self.profile_combo.itemData(i) == pid:
                self.profile_combo.setCurrentIndex(i)
                break
        self.profile_combo.blockSignals(False)

    def _on_auto_switched(self, pid):
        prof = self.profiles.get(pid)
        if prof is not None and hasattr(self, "tray") and self.tray is not None:
            self.tray.showMessage("Profile switched", prof["name"],
                                  QSystemTrayIcon.Information, 1500)

    def apply_profile(self, config, force=False):
        """Load a config into every panel AND push it to the device. Only the
        sections that DIFFER from what's currently applied are pushed (a full
        profile is 7 writes at ~60ms each + macro upload, so diffing makes a
        switch that only changes a couple of sections much faster and eases the
        stateful device). `force=True` pushes everything (used on connect, where
        the device state is unknown)."""
        old = None if force else self._current_config
        self._current_config = dict(config)
        self._seed_panels(config)              # always refresh the UI (cheap, no I/O)

        def changed(section):
            return old is None or old.get(section) != config.get(section)

        # push to the device (guarded so a failed/absent device just no-ops)
        if changed("dpi"):
            dpi = config.get("dpi", {})
            self.ctrl.call("set_dpi", dpi.get("values", []),
                           selected=dpi.get("selected", 0), colors=dpi.get("colors"))
        if changed("polling_hz"):
            self.ctrl.call("set_polling_rate", config.get("polling_hz", 500))
        if changed("lod_mm"):
            self.ctrl.call("set_lod", config.get("lod_mm", 2))
        if changed("lighting"):
            light = config.get("lighting", {})
            self.ctrl.call("set_lighting", light.get("mode", 2),
                           color=tuple(light.get("color", (0, 0, 255))))
        if changed("power"):
            pw = config.get("power", {})
            self.ctrl.call("set_power", sleep_time=pw.get("sleep_min", 20),
                           move_wakeup=pw.get("move_wakeup", True),
                           move_lighting=pw.get("move_lighting", True))
        if changed("sensor"):
            sn = config.get("sensor", {})
            self.ctrl.call("set_sensor_flags", angle_snap=sn.get("angle_snap", False),
                           motion_sync=sn.get("motion_sync", True),
                           ripple=sn.get("ripple", False))
        # buttons (+ any referenced macros) last
        if changed("buttons"):
            codes, macros = self._resolve_bindings(config.get("buttons", []))
            self.ctrl.call("apply_macro_buttons", codes, macros)

    def _seed_panels(self, config):
        """Set every panel from a config dict WITHOUT emitting apply signals."""
        self._loading_profile = True
        try:
            dpi = config.get("dpi", {})
            self.buttons_panel.set_codes(config.get("buttons", []))
            self.buttons_panel.refresh_labels()
            self.dpi_panel.set_values(dpi.get("values", []),
                                      dpi.get("colors"),
                                      enabled_count=dpi.get("enabled_count"))
            self.dpi_panel.set_active_stage(dpi.get("selected", 0))
            light = config.get("lighting", {})
            self.lighting_panel.set_state(light.get("mode", 2),
                                          tuple(light.get("color", (0, 0, 255))))
            pw = config.get("power", {})
            sn = config.get("sensor", {})
            self.performance_panel.set_state(
                polling_hz=config.get("polling_hz"), lod_mm=config.get("lod_mm"),
                sleep_min=pw.get("sleep_min"), move_wakeup=pw.get("move_wakeup"),
                move_lighting=pw.get("move_lighting"),
                angle_snap=sn.get("angle_snap"), motion_sync=sn.get("motion_sync"),
                ripple=sn.get("ripple"))
        finally:
            self._loading_profile = False

    def _update_config(self, section, value):
        """Record a live edit into the active profile and persist it. This is how
        button bindings + every other setting survive restarts."""
        if self._current_config is None or self._loading_profile:
            return
        self._current_config[section] = value
        if self.profiles.active_id:
            self.profiles.set_config(self.profiles.active_id, self._current_config)

    def _profile_new(self):
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:",
                                        text="New Profile")
        if not ok or not name.strip():
            return
        # a new profile starts from FACTORY DEFAULTS (not a copy of the current
        # one -- use Duplicate for that)
        p = self.profiles.add(name.strip(), config=default_config())
        self._refresh_profile_combo()
        self._select_profile(p["id"])

    def _target_profile_id(self):
        """Management actions (Duplicate/Rename/Delete) target the row SELECTED in
        the Profiles tab, falling back to the active profile."""
        pid = self.profiles_panel.selected_id() if hasattr(self, "profiles_panel") else None
        return pid if (pid and self.profiles.get(pid)) else self.profiles.active_id

    def _profile_duplicate(self):
        cur = self._target_profile_id()
        if not cur:
            return
        p = self.profiles.duplicate(cur)
        if p is not None:
            self._refresh_profile_combo()
            self._select_profile(p["id"])

    def _profile_rename(self):
        cur = self.profiles.get(self._target_profile_id())
        if cur is None:
            return
        name, ok = QInputDialog.getText(self, "Rename profile", "Profile name:",
                                        text=cur["name"])
        if ok and name.strip():
            self.profiles.rename(cur["id"], name.strip())
            self._refresh_profile_combo()

    def _profile_delete(self):
        cur = self.profiles.get(self._target_profile_id())
        if cur is None:
            return
        if len(self.profiles.all()) <= 1:
            QMessageBox.information(self, "Delete profile",
                                    "Can't delete the only profile.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Delete profile")
        box.setText(f"Delete profile “{cur['name']}”?")
        box.setIcon(QMessageBox.Warning)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Yes:
            return
        was_active = (cur["id"] == self.profiles.active_id)
        idx = self.profiles.index_of(cur["id"])
        self.profiles.delete(cur["id"])
        remaining = self.profiles.all()
        if not remaining:
            return
        ids = {p["id"] for p in remaining}
        self._profile_mru = [x for x in self._profile_mru if x in ids]
        self._refresh_profile_combo()
        # deleting a NON-active profile leaves the active one alone; deleting the
        # active one falls back to the last profile set (MRU), else the neighbour.
        if was_active:
            target = self._profile_mru[0] if self._profile_mru else \
                remaining[max(0, min(idx - 1, len(remaining) - 1))]["id"]
            self.profiles.set_active(target)
            if self._auto is not None:
                self._auto.set_base(target)
            self._apply_by_id(target)

    def _profile_import_psf(self):
        from . import psf_import
        path, _ = QFileDialog.getOpenFileName(
            self, "Import profile from official software",
            "", "SM809 profile (*.psf);;All files (*)")
        if not path:
            return
        try:
            imported = psf_import.import_psf(path)
        except Exception as e:
            QMessageBox.warning(self, "Import failed", f"Could not import this .psf:\n{e}")
            return
        # add any imported macros to the library and remap their temp ids -> real
        macros = imported.get("macros", [])
        idmap = {}
        for mac in macros:
            m = self.store.add(mac["name"])
            self.store.set_events(m["id"], mac["events"])
            idmap[mac["tempid"]] = m["id"]
        for b in imported["config"]["buttons"]:
            if isinstance(b, dict) and b.get("macro") in idmap:
                b["macro"] = idmap[b["macro"]]
        if macros:
            self.macro_panel._refresh_list()       # show the imported macros

        p = self.profiles.add(imported["name"], config=imported["config"],
                              match_rules=imported["match_rules"])
        self._refresh_profile_combo()
        self._select_profile(p["id"])              # base + load panels + push device
        macro_note = (f"\n{len(macros)} macro(s) were added to your Macro library."
                      if macros else
                      "\nPer-button macros: none found in this profile.")
        QMessageBox.information(
            self, "Profile imported",
            f"Imported “{imported['name']}”.\n\n"
            "Buttons, DPI, colors, polling, lift-off, lighting mode, power, sensor "
            "settings, and Run-App launchers were imported." + macro_note)

    # -- controller handlers --------------------------------------------------
    def _on_connected(self, info):
        self.topbar.set_connection(info)
        # Wired is always "charging". Over 2.4GHz, charging is reported live by
        # the status push (see _on_charging); start from not-charging there.
        self._charging = (info.get("connection") == "wired")
        # the device is write-only for config, so push the active profile now so
        # the hardware matches our persisted settings (mirrors the official app).
        # force=True: on connect the device state is unknown, push every section.
        if info.get("configurable", True) and self._current_config is not None:
            self.apply_profile(self._current_config, force=True)

    def _on_error(self, msg):
        self.topbar.set_error(msg)

    def _on_dpi_push(self, level):
        self.dpi_panel.set_active_stage(level)
        if 0 <= level < len(self.dpi_panel.rows):
            dpi = self.dpi_panel.rows[level].dpi()
            self.topbar.set_dpi_readout(f"{dpi}")
            self._cur_dpi = dpi
            # flash the HUD on a real DPI change (skip the first push at connect)
            if (self._overlay_show.get("dpi", True)
                    and self._prev_dpi_level is not None
                    and level != self._prev_dpi_level):
                self._overlay_flash()
            self._prev_dpi_level = level

    def _on_rate_push(self, hz):
        self.topbar.set_rate_readout(hz)
        # keep the Performance panel's selector in sync with the live rate
        self.performance_panel.set_state(polling_hz=hz)
        self._cur_rate = hz
        if (self._overlay_show.get("rate", False)
                and self._prev_rate is not None and hz != self._prev_rate):
            self._overlay_flash()
        self._prev_rate = hz

    def _on_battery(self, percent):
        self._battery = percent
        self.topbar.set_battery(percent, charging=self._charging)
        self._check_battery_alerts(percent)

    def _on_charging(self, charging):
        # over 2.4GHz the push tells us; wired stays True regardless
        if getattr(self.ctrl._dev, "connection", None) != "wired":
            self._charging = charging
            if self._battery is not None:
                self.topbar.set_battery(self._battery, charging=self._charging)
                self._check_battery_alerts(self._battery)

    def _on_alive(self, alive):
        if alive:
            # restore the normal connection pill + the readouts set_offline() cleared
            self.topbar.set_connection({
                "connection": getattr(self.ctrl._dev, "connection", None),
                "configurable": getattr(self.ctrl._dev, "configurable", True),
            })
            if self._battery is not None:
                self.topbar.set_battery(self._battery, charging=self._charging)
            if self._cur_dpi is not None:
                self.topbar.set_dpi_readout(f"{self._cur_dpi}")
            if self._cur_rate is not None:
                self.topbar.set_rate_readout(self._cur_rate)
        else:
            if getattr(self.ctrl._dev, "connection", None) == "2.4GHz":
                self.topbar.set_offline()
            else:
                self.topbar.set_disconnected()

    def _on_runapp(self, code):
        """A host-side Run-APP button was pressed (report-04 byte[7]=code). Map
        it to the physical button, look up that button's exe in the ACTIVE
        profile, and launch it detached."""
        phys = A.runapp_code_to_physical(code)   # 1-based physical button
        if phys is None or self._current_config is None:
            return
        buttons = self._current_config.get("buttons", [])
        if not (1 <= phys <= len(buttons)):
            return
        binding = buttons[phys - 1]
        if not (isinstance(binding, dict) and binding.get("runapp")):
            return
        path = binding["runapp"]
        from PySide6.QtCore import QProcess
        import os
        ok = QProcess.startDetached(path, [], os.path.dirname(path) or "")
        if not ok and self.tray is not None:
            self.tray.showMessage("Run App failed", f"Couldn't launch:\n{path}",
                                  QSystemTrayIcon.Warning, 2500)

    def _on_command_done(self, method, ok):
        pass

    # -- actions --------------------------------------------------------------
    def _apply_dpi(self, dpi_values, colors, selected):
        self.ctrl.call("set_dpi", dpi_values, selected=selected, colors=colors)
        self._update_config("dpi", {
            "values": list(dpi_values),
            "colors": [list(c) for c in colors],
            "enabled_count": len(dpi_values),
            "selected": selected,
        })

    def _apply_active_dpi(self, dpi_values, selected):
        # switch the live DPI stage: re-send the class-0x02 DPI config pair with
        # the new selected stage (confirmed by USB capture). No color write.
        self.ctrl.call("set_active_dpi", dpi_values, selected)
        if self._current_config is not None and not self._loading_profile:
            dpi = dict(self._current_config.get("dpi", {}))
            dpi["selected"] = selected
            self._update_config("dpi", dpi)

    def _apply_buttons(self, bindings):
        codes, macros = self._resolve_bindings(bindings)
        self.ctrl.call("apply_macro_buttons", codes, macros)
        # persist the raw bindings (tuples and/or macro dicts) into the profile
        self._update_config("buttons", [list(b) if isinstance(b, tuple) else b
                                        for b in bindings])

    def _resolve_bindings(self, bindings):
        """Turn the 16-entry button list (3-byte tuples and/or {'macro':id,..}
        dicts) into final 3-byte codes + a {slot: events} upload set. Slots are
        assigned only to BOUND macros (<=16 buttons -> fit 0..15), so the library
        stays unlimited and a macro reaches the device only when assigned."""
        slot_for = {}
        macros = {}
        codes = []
        for b in bindings:
            if isinstance(b, dict) and "macro" in b:
                m = self.store.get(b["macro"])
                if m is None:
                    codes.append(A.BTN["unset"])
                    continue
                mid = b["macro"]
                if mid not in slot_for:
                    if len(slot_for) >= 15:   # slots 1..15, so 15 macros max
                        codes.append(A.BTN["unset"])
                        continue
                    slot = len(slot_for) + 1   # slots 1..15 (official app uses 1+, slot 0 unused)
                    slot_for[mid] = slot
                    macros[slot] = m["events"]
                slot = slot_for[mid]
                codes.append(A.macro_action(slot, b.get("playmode", 1), b.get("repeat", 0)))
            elif isinstance(b, dict) and "runapp" in b:
                # host-side launcher: device gets the placeholder; the exe path
                # stays in the profile and is launched by _on_runapp on press.
                codes.append(A.BTN["run_app"])
            else:
                codes.append(tuple(b) if b else A.BTN["unset"])
        return codes, macros

    def _on_library_changed(self):
        # if a bound macro was deleted, reset that button to its factory default
        # and push the corrected key map now; otherwise a body edit to a bound
        # macro should re-sync to the device (debounced).
        ids = {m["id"] for m in self.store.all()}
        defaults = A.default_button_codes()
        reset_any = False
        for i, b in enumerate(self.buttons_panel.bindings()):
            if isinstance(b, dict) and "macro" in b and b["macro"] not in ids:
                self.buttons_panel.set_binding(i + 1, defaults[i])
                reset_any = True
        self.buttons_panel.refresh_labels()
        if reset_any:
            self._apply_buttons(self.buttons_panel.bindings())
        else:
            self._macro_resync.start()

    def _resync_macros(self):
        bindings = self.buttons_panel.bindings()
        if any(isinstance(b, dict) and "macro" in b for b in bindings):
            self._apply_buttons(bindings)

    def _apply_lighting(self, mode, color):
        self.ctrl.call("set_lighting", mode, color=color)
        self._update_config("lighting", {"mode": mode, "color": list(color)})

    def _apply_polling(self, hz):
        self.ctrl.call("set_polling_rate", hz)
        self._update_config("polling_hz", hz)

    def _apply_lod(self, mm):
        self.ctrl.call("set_lod", mm)
        self._update_config("lod_mm", mm)

    def _apply_power(self, sleep_min, move_wakeup, move_lighting):
        self.ctrl.call("set_power", sleep_time=sleep_min,
                       move_wakeup=move_wakeup, move_lighting=move_lighting)
        self._update_config("power", {"sleep_min": sleep_min,
                                      "move_wakeup": move_wakeup,
                                      "move_lighting": move_lighting})

    def _apply_sensor(self, angle_snap, motion_sync, ripple):
        self.ctrl.call("set_sensor_flags", angle_snap=angle_snap,
                       motion_sync=motion_sync, ripple=ripple)
        self._update_config("sensor", {"angle_snap": angle_snap,
                                       "motion_sync": motion_sync,
                                       "ripple": ripple})

    def _confirm_reset(self):
        box = QMessageBox(self)
        box.setWindowTitle("Reset to Factory")
        box.setText("Reset the mouse to factory defaults?")
        box.setInformativeText("This restores DPI stages, colors, polling, lift-off, "
                               "lighting, power, sensor settings, and the button "
                               "layout — like the official Restore. Your saved macros "
                               "are kept.")
        box.setIcon(QMessageBox.Warning)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() == QMessageBox.Yes:
            self.ctrl.call("factory_reset")   # single 0x0F, matches the official Restore exactly
            # reflect the restored defaults across all panels AND fold them into
            # the active profile so the reset persists (bindings reset to factory).
            cfg = default_config()
            self._current_config = cfg
            self._seed_panels(cfg)
            if self.profiles.active_id:
                self.profiles.set_config(self.profiles.active_id, cfg)

    # -- auto-switch + tray ---------------------------------------------------
    def _tray_icon(self):
        """The app icon for the tray; falls back to a painted accent dot if the
        icon file can't be loaded."""
        ic = app_icon()
        if not ic.isNull():
            return ic
        pm = QPixmap(32, 32)
        pm.fill(QColor(theme.BG))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(theme.ACCENT))
        p.setPen(QColor(theme.ACCENT))
        p.drawEllipse(8, 8, 16, 16)
        p.end()
        return QIcon(pm)

    def _setup_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._force_quit = False
        from PySide6.QtWidgets import QApplication
        QApplication.setQuitOnLastWindowClosed(False)
        self.tray = QSystemTrayIcon(self._tray_icon(), self)
        self.tray.setToolTip("SM809 Pro — Custom Driver")
        menu = QMenu()
        menu.addAction("Show window", self._show_from_tray)

        # Profiles submenu -- rebuilt each time it opens so it tracks renames/adds
        self.tray_profiles_menu = QMenu("Profiles", menu)
        self.tray_profiles_menu.aboutToShow.connect(self._rebuild_tray_profiles)
        menu.addMenu(self.tray_profiles_menu)

        self.tray_autoswitch = QAction("Enable auto-switch", self, checkable=True)
        self.tray_autoswitch.toggled.connect(self._toggle_autoswitch)
        menu.addAction(self.tray_autoswitch)
        self.tray_overlay = QAction("Show on-screen overlay", self, checkable=True)
        self.tray_overlay.toggled.connect(self._toggle_overlay)
        menu.addAction(self.tray_overlay)
        menu.addAction("Overlay settings…", self._overlay_settings)
        menu.addSeparator()
        from . import autostart
        if autostart.supported():
            self.tray_autostart = QAction("Start with Windows", self, checkable=True)
            self.tray_autostart.setChecked(autostart.is_enabled())
            self.tray_autostart.toggled.connect(self._toggle_autostart)
            menu.addAction(self.tray_autostart)
            menu.addSeparator()
        menu.addAction("Quit", self._quit_from_tray)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self._show_from_tray()
            if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _rebuild_tray_profiles(self):
        """Populate the tray Profiles submenu; the manual base is checkmarked."""
        m = self.tray_profiles_menu
        m.clear()
        for p in self.profiles.all():
            act = QAction(p["name"], m, checkable=True)
            act.setChecked(p["id"] == self.profiles.active_id)
            act.triggered.connect(lambda _=False, pid=p["id"]: self._select_profile(pid))
            m.addAction(act)

    def _quit_from_tray(self):
        self._force_quit = True
        self.close()

    def _toggle_autoswitch(self, on):
        if self._auto.is_enabled() == bool(on):
            self._sync_autoswitch_ui(on)
            return
        self._auto.set_enabled(on)
        self.profiles.set_setting("auto_switch", bool(on))
        self._sync_autoswitch_ui(on)

    def _sync_autoswitch_ui(self, on):
        act = getattr(self, "tray_autoswitch", None)
        if act is not None and act.isChecked() != bool(on):
            act.blockSignals(True)
            act.setChecked(bool(on))
            act.blockSignals(False)
        if hasattr(self, "autoswitch_panel"):
            self.autoswitch_panel.set_enabled_state(on)

    def _toggle_overlay(self, on):
        self._overlay_enabled = bool(on)
        self.profiles.set_setting("overlay", self._overlay_enabled)
        self._sync_overlay_ui(on)
        if on:
            self.overlay.flash("ON", "OVERLAY")     # confirm it's visible
        else:
            self.overlay.hide()

    def _toggle_autostart(self, on):
        from . import autostart
        autostart.set_enabled(on)
        # reflect the real registry state (revert the check if it failed)
        actual = autostart.is_enabled()
        if hasattr(self, "tray_autostart") and self.tray_autostart.isChecked() != actual:
            self.tray_autostart.blockSignals(True)
            self.tray_autostart.setChecked(actual)
            self.tray_autostart.blockSignals(False)

    def _sync_overlay_ui(self, on):
        act = getattr(self, "tray_overlay", None)
        if act is not None and act.isChecked() != bool(on):
            act.blockSignals(True)
            act.setChecked(bool(on))
            act.blockSignals(False)

    def _overlay_settings(self):
        """Configure what the overlay shows + its position / transparency / size."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Overlay settings")
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)

        enable = QCheckBox("Show on-screen overlay")
        enable.setChecked(self._overlay_enabled)
        lay.addWidget(enable)

        grp = QGroupBox("Show on change")
        gl = QVBoxLayout(grp)
        cb_prof = QCheckBox("Profile name"); cb_prof.setChecked(self._overlay_show.get("profile", True))
        cb_dpi = QCheckBox("DPI"); cb_dpi.setChecked(self._overlay_show.get("dpi", True))
        cb_rate = QCheckBox("Polling rate"); cb_rate.setChecked(self._overlay_show.get("rate", False))
        for c in (cb_prof, cb_dpi, cb_rate):
            gl.addWidget(c)
        lay.addWidget(grp)

        prow = QHBoxLayout()
        prow.addWidget(QLabel("Position"))
        pos = QComboBox()
        for p in POSITIONS:
            pos.addItem(POSITION_LABELS[p], p)
        i = pos.findData(self.profiles.get_setting("overlay_pos", "bottom-center"))
        pos.setCurrentIndex(i if i >= 0 else POSITIONS.index("bottom-center"))
        prow.addWidget(pos, 1)
        lay.addLayout(prow)

        # monitor: follow the cursor's monitor, or pin to a chosen one
        follow = QCheckBox("Show on the monitor under the cursor")
        follow.setChecked(bool(self.profiles.get_setting("overlay_follow_cursor", True)))
        lay.addWidget(follow)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("Monitor"))
        mon = QComboBox()
        for si, scr in enumerate(QGuiApplication.screens()):
            g = scr.geometry()
            tag = " (primary)" if scr is QGuiApplication.primaryScreen() else ""
            mon.addItem(f"Monitor {si + 1} — {g.width()}x{g.height()}{tag}", si)
        mon.setCurrentIndex(min(int(self.profiles.get_setting("overlay_monitor", 0)),
                                max(0, mon.count() - 1)))
        mon.setEnabled(not follow.isChecked())
        follow.toggled.connect(lambda on: mon.setEnabled(not on))
        mrow.addWidget(mon, 1)
        lay.addLayout(mrow)

        op_lbl = QLabel()
        op = QSlider(Qt.Horizontal); op.setRange(30, 100)
        op.setValue(int(self.profiles.get_setting("overlay_opacity", 92)))
        op.valueChanged.connect(lambda v: op_lbl.setText(f"Transparency (opacity): {v}%"))
        op.valueChanged.emit(op.value())
        lay.addWidget(op_lbl); lay.addWidget(op)

        sc_lbl = QLabel()
        sc = QSlider(Qt.Horizontal); sc.setRange(60, 200)
        sc.setValue(int(self.profiles.get_setting("overlay_scale", 100)))
        sc.valueChanged.connect(lambda v: sc_lbl.setText(f"Size: {v}%"))
        sc.valueChanged.emit(sc.value())
        lay.addWidget(sc_lbl); lay.addWidget(sc)

        dur_lbl = QLabel()
        dur = QSlider(Qt.Horizontal); dur.setRange(3, 50)   # 0.3s .. 5.0s (x100ms)
        dur.setValue(int(self.profiles.get_setting("overlay_hold", 1400)) // 100)
        dur.valueChanged.connect(lambda v: dur_lbl.setText(f"Duration on screen: {v / 10:.1f} s"))
        dur.valueChanged.emit(dur.value())
        lay.addWidget(dur_lbl); lay.addWidget(dur)

        def _preview():
            self.overlay.set_appearance(pos.currentData(), op.value(), sc.value(),
                                        hold_ms=dur.value() * 100,
                                        follow_cursor=follow.isChecked(),
                                        monitor_index=mon.currentData() or 0)
            lines = []
            if cb_prof.isChecked():
                lines.append(("Profile", self._cur_profile
                              or (self.profiles.active() or {}).get("name", "Default")))
            if cb_dpi.isChecked():
                lines.append(("DPI", self._cur_dpi if self._cur_dpi is not None else 1600))
            if cb_rate.isChecked():
                lines.append(("Polling Rate", f"{self._cur_rate or 1000} Hz"))
            self.overlay.flash_lines(lines or [("Overlay", "nothing selected")])

        prev = QPushButton("Preview")
        prev.clicked.connect(_preview)
        lay.addWidget(prev)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)

        if dlg.exec() == QDialog.Accepted:
            self._overlay_show = {"profile": cb_prof.isChecked(),
                                  "dpi": cb_dpi.isChecked(), "rate": cb_rate.isChecked()}
            self.profiles.set_setting("overlay_show", self._overlay_show)
            self.profiles.set_setting("overlay_pos", pos.currentData())
            self.profiles.set_setting("overlay_opacity", op.value())
            self.profiles.set_setting("overlay_scale", sc.value())
            self.profiles.set_setting("overlay_hold", dur.value() * 100)
            self.profiles.set_setting("overlay_follow_cursor", follow.isChecked())
            self.profiles.set_setting("overlay_monitor", mon.currentData() or 0)
            self._apply_overlay_appearance()      # applies to overlay + alert overlay
            if enable.isChecked() != self._overlay_enabled:
                self._toggle_overlay(enable.isChecked())
        else:
            self._apply_overlay_appearance()      # revert preview tweaks to saved

    def closeEvent(self, e):
        # with a tray icon, closing hides to tray (keeps auto-switch running)
        if self.tray is not None and not getattr(self, "_force_quit", False):
            e.ignore()
            self.hide()
            self.tray.showMessage(
                "Still running", "Auto-switch stays active. Quit from the tray icon.",
                QSystemTrayIcon.Information, 2000)
            return
        if self._auto is not None:
            self._auto.set_enabled(False)
        if self.tray is not None:
            self.tray.hide()
        if getattr(self, "overlay", None) is not None:
            self.overlay.hide()
        if getattr(self, "alert_overlay", None) is not None:
            self.alert_overlay.hide()
        self.ctrl.shutdown()
        super().closeEvent(e)
        if getattr(self, "_force_quit", False):
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
