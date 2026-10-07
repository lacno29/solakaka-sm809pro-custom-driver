"""
app.panels.performance_panel -- polling rate, lift-off distance, power
management, and sensor flags. Mirrors the official app's Performance tab, themed
to match. Every control auto-applies to the mouse on change (the power slider is
debounced so dragging applies once on release/pause).

Commands used are all hardware-validated:
  set_polling_rate(hz), set_lod(mm), set_power(sleep, wake, light), set_sensor_flags(...)
"""

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QCheckBox, QFrame,
    QScrollArea, QSizePolicy,
)

from .. import theme
from ..widgets.controls import Card, Segmented
from sm809pro import protocol as P
from sm809pro import defaults as _D

# Only expose polling rates the unit actually supports (caps at 1000 on this
# hardware). The enum has higher values but they're unavailable here.
SUPPORTED_POLLING = [125, 250, 500, 1000]
SLEEP_MIN, SLEEP_MAX = 0, 30   # power-down minutes (0 = never)


def _hline():
    f = QFrame()
    f.setProperty("sep", "true")
    f.setFrameShape(QFrame.NoFrame)
    return f


class PerformancePanel(QWidget):
    """Polling / LOD / power / sensor settings; auto-applies on change."""
    polling_changed = Signal(int)                 # hz
    lod_changed = Signal(int)                      # mm
    power_changed = Signal(int, bool, bool)        # sleep_min, move_wakeup, move_lighting
    sensor_changed = Signal(bool, bool, bool)      # angle_snap, motion_sync, ripple

    POWER_DEBOUNCE_MS = 250

    def __init__(self):
        super().__init__()
        self._suspend = False

        # debounce only the power slider (drag)
        self._power_timer = QTimer(self)
        self._power_timer.setSingleShot(True)
        self._power_timer.setInterval(self.POWER_DEBOUNCE_MS)
        self._power_timer.timeout.connect(self._emit_power)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        title = QLabel("Performance")
        title.setProperty("panelTitle", "true")
        root.addWidget(title)
        sub = QLabel("Polling rate, lift-off distance, power management, and "
                     "sensor tuning. Changes apply to the mouse automatically.")
        sub.setProperty("panelSubtitle", "true")
        root.addWidget(sub)
        root.addWidget(_hline())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(16)

        # --- Polling Rate ---
        poll_card = Card("POLLING RATE")
        self.polling = Segmented([(f"{hz}Hz", hz) for hz in SUPPORTED_POLLING],
                                 value=_D.POLLING_HZ)
        self.polling.changed.connect(self._on_polling)
        poll_card.add(self.polling)
        col.addWidget(poll_card)

        # --- Mouse LOD Height ---
        lod_card = Card("MOUSE LOD HEIGHT")
        self.lod = Segmented([("1mm", 1), ("2mm", 2)], value=_D.LOD_MM)
        self.lod.changed.connect(self._on_lod)
        lod_card.add(self.lod)
        col.addWidget(lod_card)

        # --- Power Management ---
        pwr_card = Card("POWER MANAGEMENT")
        srow = QHBoxLayout()
        srow.setSpacing(14)
        self.sleep = QSlider(Qt.Horizontal)
        self.sleep.setRange(SLEEP_MIN, SLEEP_MAX)
        self.sleep.setSingleStep(1)
        self.sleep.setPageStep(5)
        self.sleep.setValue(_D.POWER_SLEEP_MIN)
        self.sleep.valueChanged.connect(self._on_sleep_slider)
        self.sleep.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        srow.addWidget(self.sleep, 1)
        self.sleep_value = QLabel(self._sleep_text(_D.POWER_SLEEP_MIN))
        self.sleep_value.setProperty("monoValue", "true")
        self.sleep_value.setFixedWidth(96)
        self.sleep_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        srow.addWidget(self.sleep_value)
        pwr_card.add(srow)
        cap = QLabel("Power-down time (minutes of inactivity). 0 = never sleep.")
        cap.setProperty("cardHint", "true")
        pwr_card.add(cap)

        self.move_wake = QCheckBox("Keep motion wake up")
        self.move_wake.setChecked(_D.POWER_MOVE_WAKEUP)
        self.move_wake.toggled.connect(self._on_power_toggle)
        pwr_card.add(self.move_wake)
        self.move_light = QCheckBox("Lighting off while mouse moves")
        self.move_light.setChecked(_D.POWER_MOVE_LIGHTING)
        self.move_light.toggled.connect(self._on_power_toggle)
        pwr_card.add(self.move_light)
        col.addWidget(pwr_card)

        # --- Sensor Advanced Settings ---
        sensor_card = Card("SENSOR ADVANCED SETTINGS")
        srow2 = QHBoxLayout()
        srow2.setSpacing(28)
        self.angle_snap = QCheckBox("Angle Snap")
        self.angle_snap.setChecked(_D.SENSOR_ANGLE_SNAP)
        self.angle_snap.toggled.connect(self._on_sensor_toggle)
        self.motion_sync = QCheckBox("Motion Sync")
        self.motion_sync.setChecked(_D.SENSOR_MOTION_SYNC)
        self.motion_sync.toggled.connect(self._on_sensor_toggle)
        self.ripple = QCheckBox("Ripple Control")
        self.ripple.setChecked(_D.SENSOR_RIPPLE)
        self.ripple.toggled.connect(self._on_sensor_toggle)
        for c in (self.angle_snap, self.motion_sync, self.ripple):
            srow2.addWidget(c)
        srow2.addStretch(1)
        sensor_card.add(srow2)
        col.addWidget(sensor_card)

        col.addStretch(1)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)

    # -- helpers --------------------------------------------------------------
    @staticmethod
    def _sleep_text(v):
        return "Never" if v == 0 else f"{v} min"

    # -- polling / lod --------------------------------------------------------
    def _on_polling(self, hz):
        if self._suspend:
            return
        self.polling_changed.emit(hz)

    def _on_lod(self, mm):
        if self._suspend:
            return
        self.lod_changed.emit(mm)

    # -- power ----------------------------------------------------------------
    def _on_sleep_slider(self, v):
        self.sleep_value.setText(self._sleep_text(v))
        if self._suspend:
            return
        self._power_timer.start()

    def _on_power_toggle(self, _):
        if self._suspend:
            return
        self._power_timer.stop()
        self._emit_power()

    def _emit_power(self):
        self.power_changed.emit(self.sleep.value(),
                                self.move_wake.isChecked(),
                                self.move_light.isChecked())

    # -- sensor ---------------------------------------------------------------
    def _on_sensor_toggle(self, _):
        if self._suspend:
            return
        self.sensor_changed.emit(self.angle_snap.isChecked(),
                                 self.motion_sync.isChecked(),
                                 self.ripple.isChecked())

    # -- external -------------------------------------------------------------
    def set_state(self, polling_hz=None, lod_mm=None, sleep_min=None,
                  move_wakeup=None, move_lighting=None,
                  angle_snap=None, motion_sync=None, ripple=None):
        """Load values from outside (e.g. factory restore) without applying."""
        self._suspend = True
        try:
            if polling_hz is not None:
                self.polling.set_value(polling_hz)
            if lod_mm is not None:
                self.lod.set_value(lod_mm)
            if sleep_min is not None:
                self.sleep.setValue(sleep_min)
                self.sleep_value.setText(self._sleep_text(sleep_min))
            if move_wakeup is not None:
                self.move_wake.setChecked(move_wakeup)
            if move_lighting is not None:
                self.move_light.setChecked(move_lighting)
            if angle_snap is not None:
                self.angle_snap.setChecked(angle_snap)
            if motion_sync is not None:
                self.motion_sync.setChecked(motion_sync)
            if ripple is not None:
                self.ripple.setChecked(ripple)
        finally:
            self._suspend = False
