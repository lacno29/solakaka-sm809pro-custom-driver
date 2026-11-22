"""
app.widgets.jiggler_dialog -- Mouse Jiggler settings dialog.

Reuses app.widgets.controls.Card and app.theme ("Precision Instrument" dark
aesthetic), exposing all options from arkane-systems/mousejiggler: mode,
interval, randomization, distance multiplier, lock-state pause, global hotkey,
startup auto-jiggle, and a live test-jiggle preview button.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
)

from .. import theme
from ..jiggler import (
    HOTKEY_TEXT,
    JIGGLE_MODES,
    MAX_DISTANCE,
    MAX_PERIOD,
    MIN_DISTANCE,
    MIN_PERIOD,
    MODE_DESCRIPTIONS,
)
from .controls import Card


class JigglerSettingsDialog(QDialog):
    """Modal configuration dialog for the Mouse Jiggler feature."""

    def __init__(self, jiggler, autostart: bool = False, parent=None):
        super().__init__(parent)
        self._jiggler = jiggler
        self.setWindowTitle("Mouse Jiggler settings")
        self.setMinimumWidth(460)

        self.setStyleSheet(
            f"""
            QDialog {{
                background: {theme.BG};
            }}
            QFrame[card="true"] QLabel, QFrame[card="true"] QCheckBox {{
                background: transparent;
            }}
            QSpinBox:disabled {{
                background: {theme.BG};
                color: {theme.TEXT_DIM};
                border-color: {theme.BORDER};
            }}
            """
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        # --- Top enable toggle + live status readout ---
        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        self.enable_cb = QCheckBox("Enable mouse jiggler")
        self.enable_cb.setChecked(bool(jiggler.enabled))
        top_row.addWidget(self.enable_cb)
        top_row.addStretch(1)
        lay.addLayout(top_row)

        self.status_lbl = QLabel()
        self.status_lbl.setWordWrap(True)
        lay.addWidget(self.status_lbl)

        # --- Movement card ---
        move_card = Card("MOVEMENT")
        move_card.body.setSpacing(8)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        mode_lbl = QLabel("Jiggle mode")
        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumHeight(30)
        for m in JIGGLE_MODES:
            self.mode_combo.addItem(m, m)
        idx = self.mode_combo.findData(jiggler.mode)
        self.mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        grid.addWidget(mode_lbl, 0, 0)
        grid.addWidget(self.mode_combo, 0, 1)

        self.mode_hint = QLabel()
        self.mode_hint.setProperty("cardHint", "true")
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        grid.addWidget(self.mode_hint, 1, 1)

        period_lbl = QLabel("Interval")
        self.period_spin = QSpinBox()
        self.period_spin.setMinimumHeight(30)
        self.period_spin.setRange(MIN_PERIOD, MAX_PERIOD)
        self.period_spin.setSuffix(" s")
        self.period_spin.setAlignment(Qt.AlignRight)
        self.period_spin.setValue(int(jiggler.period))
        grid.addWidget(period_lbl, 2, 0)
        grid.addWidget(self.period_spin, 2, 1)

        self.random_cb = QCheckBox("Randomize interval (1 s up to interval)")
        self.random_cb.setChecked(bool(jiggler.random_timer))
        grid.addWidget(self.random_cb, 3, 1)

        dist_lbl = QLabel("Distance multiplier")
        self.distance_spin = QSpinBox()
        self.distance_spin.setMinimumHeight(30)
        self.distance_spin.setRange(MIN_DISTANCE, MAX_DISTANCE)
        self.distance_spin.setSuffix("\u00d7")
        self.distance_spin.setAlignment(Qt.AlignRight)
        self.distance_spin.setValue(int(jiggler.distance))
        self.distance_spin.valueChanged.connect(self._update_distance_state)
        grid.addWidget(dist_lbl, 4, 0)
        grid.addWidget(self.distance_spin, 4, 1)

        self.distance_hint = QLabel(
            "High multipliers move the pointer significantly."
        )
        self.distance_hint.setWordWrap(True)
        self.distance_hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.distance_hint.setStyleSheet(f"color: {theme.WARN}; font-size: 11px;")
        grid.addWidget(self.distance_hint, 5, 1)

        move_card.body.addLayout(grid)
        lay.addWidget(move_card)

        # --- Behavior card ---
        beh_card = Card("BEHAVIOR")
        beh_card.body.setSpacing(8)

        self.respect_lock_cb = QCheckBox("Pause when Windows is locked")
        self.respect_lock_cb.setToolTip(
            "Pauses jiggling and allows sleep while the workstation is locked, resuming on unlock."
        )
        self.respect_lock_cb.setChecked(bool(jiggler.respect_locked_state))
        beh_card.add(self.respect_lock_cb)

        self.hotkey_cb = QCheckBox(f"Global toggle hotkey ({HOTKEY_TEXT})")
        self.hotkey_cb.setChecked(bool(jiggler.hotkey_enabled))
        self.hotkey_cb.toggled.connect(self._update_hotkey_warning)
        beh_card.add(self.hotkey_cb)

        self.hotkey_warn = QLabel(
            f"Could not register {HOTKEY_TEXT} \u2014 it may already be in use by another app."
        )
        self.hotkey_warn.setWordWrap(True)
        self.hotkey_warn.setStyleSheet(f"color: {theme.WARN}; font-size: 11px;")
        beh_card.add(self.hotkey_warn)

        self.autostart_cb = QCheckBox("Start jiggling when app launches")
        self.autostart_cb.setChecked(bool(autostart))
        beh_card.add(self.autostart_cb)

        info_hint = QLabel(
            "Pauses automatically while you move the mouse and prevents sleep while active."
        )
        info_hint.setProperty("cardHint", "true")
        info_hint.setWordWrap(True)
        beh_card.add(info_hint)

        lay.addWidget(beh_card)

        # --- Bottom action row ---
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.test_btn = QPushButton("Test jiggle")
        self.test_btn.clicked.connect(self._on_test)
        btn_row.addWidget(self.test_btn)
        btn_row.addStretch(1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = self.buttons.button(QDialogButtonBox.Ok)
        if ok_btn is not None:
            ok_btn.setObjectName("primary")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        btn_row.addWidget(self.buttons)
        lay.addLayout(btn_row)

        # Live status syncing while dialog is open
        self._jiggler.status_changed.connect(self._refresh_status)
        self._jiggler.tick_completed.connect(self._on_tick_completed)
        self.finished.connect(self._disconnect_signals)

        self._on_mode_changed()
        self._update_hotkey_warning()
        self._refresh_status()

    def _disconnect_signals(self, *_):
        try:
            self._jiggler.status_changed.disconnect(self._refresh_status)
        except (RuntimeError, TypeError):
            pass
        try:
            self._jiggler.tick_completed.disconnect(self._on_tick_completed)
        except (RuntimeError, TypeError):
            pass

    def _on_tick_completed(self, *_):
        self._refresh_status()

    def _refresh_status(self):
        if self._jiggler.is_paused_locked:
            color = theme.WARN
        elif self._jiggler.is_active:
            color = theme.GOOD
        else:
            color = theme.TEXT_DIM
        self.status_lbl.setText(f"Status: {self._jiggler.status_summary()}")
        self.status_lbl.setStyleSheet(
            f"color: {color}; font-family: {theme.FONT_MONO}; font-size: 12px;"
        )

    def _on_mode_changed(self, *_):
        mode = self.mode_combo.currentData() or "Normal"
        self.mode_hint.setText(MODE_DESCRIPTIONS.get(mode, ""))
        is_zen = (mode == "Zen")
        self.distance_spin.setEnabled(not is_zen)
        self.distance_spin.setToolTip(
            "Not used in Zen mode"
            if is_zen
            else "Multiplier applied to jiggle step size (1\u2013120)"
        )
        self._update_distance_state()

    def _update_distance_state(self, *_):
        mode = self.mode_combo.currentData() or "Normal"
        high = (mode != "Zen" and self.distance_spin.value() > 20)
        self.distance_hint.setVisible(high)
        if self.isVisible():
            self.adjustSize()

    def _update_hotkey_warning(self, *_):
        show_warn = (
            self.hotkey_cb.isChecked()
            and bool(self._jiggler.hotkey_registration_failed)
        )
        self.hotkey_warn.setVisible(show_warn)

    def _on_test(self):
        mode = self.mode_combo.currentData() or "Normal"
        distance = self.distance_spin.value()
        self._jiggler.pulse_preview(mode=mode, distance=distance)

    def values(self) -> dict:
        """Return the configured jiggler fields from the dialog controls."""
        return {
            "enabled": self.enable_cb.isChecked(),
            "mode": self.mode_combo.currentData() or "Normal",
            "period": self.period_spin.value(),
            "distance": self.distance_spin.value(),
            "random_timer": self.random_cb.isChecked(),
            "respect_locked_state": self.respect_lock_cb.isChecked(),
            "hotkey_enabled": self.hotkey_cb.isChecked(),
            "autostart": self.autostart_cb.isChecked(),
        }
