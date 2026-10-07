"""
app.panels.dpi_panel -- the DPI configuration panel.

Six (up to eight) DPI stage rows. Each row: enable toggle, a 100..24000 slider,
a large monospace value readout, and a color swatch (the stage LED color). The
stage that is currently active on the device is highlighted live from the status
push. Changes auto-apply to the mouse (slider drags are debounced).
"""

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QCheckBox,
    QFrame, QScrollArea, QSizePolicy,
)

from .. import theme
from ..widgets.color_picker import pick_color
from sm809pro import defaults as _D

# Confirmed factory defaults (single source of truth in sm809pro.defaults).
DEFAULT_DPI = list(_D.DPI_VALUES)
DEFAULT_COLORS = list(_D.DPI_COLORS)
DPI_MIN, DPI_MAX, DPI_STEP = 100, _D.DPI_MAX, 100


def _hline():
    f = QFrame()
    f.setProperty("sep", "true")
    f.setFrameShape(QFrame.NoFrame)
    return f


class Swatch(QFrame):
    """A clickable color swatch representing a DPI stage's LED color."""
    changed = Signal()

    def __init__(self, rgb):
        super().__init__()
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self._rgb = rgb
        self._apply()

    def _apply(self):
        r, g, b = self._rgb
        self.setStyleSheet(
            f"background: rgb({r},{g},{b}); border-radius: 6px; "
            f"border: 1px solid {theme.BORDER};"
        )

    def rgb(self):
        return self._rgb

    def set_rgb(self, rgb):
        self._rgb = rgb
        self._apply()

    def mousePressEvent(self, e):
        rgb = pick_color(self._rgb, self.window())
        if rgb is not None:
            self.set_rgb(rgb)
            self.changed.emit()


class StageRow(QFrame):
    """One DPI stage: enable toggle + slider + value readout + color swatch.
    Clicking the index badge selects this stage as the active DPI."""
    edited = Signal()
    activate_requested = Signal(int)   # absolute stage index the user clicked

    def __init__(self, index: int, dpi: int, rgb, enabled: bool):
        super().__init__()
        self.index = index
        self.setObjectName("stageRow")
        self._active = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(16)

        # stage index label -- click to make this stage the active DPI
        self.idx_label = QLabel(f"{index + 1}")
        self.idx_label.setProperty("stageIndex", "true")
        self.idx_label.setFixedWidth(16)
        self.idx_label.setCursor(Qt.PointingHandCursor)
        self.idx_label.setToolTip("Set as active DPI")
        self.idx_label.mousePressEvent = self._on_idx_clicked
        lay.addWidget(self.idx_label)

        # enable toggle
        self.toggle = QCheckBox()
        self.toggle.setChecked(enabled)
        self.toggle.toggled.connect(self._on_toggle)
        lay.addWidget(self.toggle)

        # slider
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(DPI_MIN)
        self.slider.setMaximum(DPI_MAX)
        self.slider.setSingleStep(DPI_STEP)
        self.slider.setPageStep(400)
        self.slider.setValue(dpi)
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay.addWidget(self.slider, 1)

        # value readout (monospace)
        self.value = QLabel(str(self._snap(dpi)))
        self.value.setObjectName("dpiValue")
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value.setFixedWidth(86)
        lay.addWidget(self.value)

        unit = QLabel("DPI")
        unit.setProperty("unit", "true")
        lay.addWidget(unit)

        # color swatch
        self.swatch = Swatch(rgb)
        self.swatch.changed.connect(self.edited.emit)
        lay.addWidget(self.swatch)

        self._sync_enabled()

    @staticmethod
    def _snap(v):
        return int(round(v / DPI_STEP) * DPI_STEP)

    def _on_slider(self, v):
        self.value.setText(str(self._snap(v)))
        self.edited.emit()

    def _on_idx_clicked(self, e):
        # only enabled stages can be made active
        if self.toggle.isChecked():
            self.activate_requested.emit(self.index)

    def _on_toggle(self, _):
        self._sync_enabled()
        self.edited.emit()

    def _sync_enabled(self):
        on = self.toggle.isChecked()
        self.slider.setEnabled(on)
        self.value.setEnabled(on)
        self.swatch.setEnabled(on)

    def set_active(self, active: bool):
        """Highlight this row as the device's current stage (live)."""
        self._active = active
        self.setObjectName("stageRowActive" if active else "stageRow")
        self.value.setObjectName("dpiValueActive" if active else "dpiValue")
        # the index badge uses a dynamic property (object-name is used elsewhere)
        self.idx_label.setProperty("stageIndex", None if active else "true")
        self.idx_label.setProperty("stageIndexActive", "true" if active else None)
        # re-polish so the new styles apply
        for w in (self, self.value, self.idx_label):
            w.style().unpolish(w)
            w.style().polish(w)

    # data accessors
    def is_enabled(self):
        return self.toggle.isChecked()

    def dpi(self):
        return self._snap(self.slider.value())

    def rgb(self):
        return self.swatch.rgb()


class DpiPanel(QWidget):
    """The DPI panel: a column of stage rows. Changes auto-apply to the mouse.
    Clicking a stage's number selects it as the active DPI."""
    # (dpi_values, colors, selected_index_within_enabled) for enabled stages
    apply_requested = Signal(list, list, int)
    # user clicked a stage to make it active: (enabled_dpi_values, selected_idx)
    # -- the switch command re-sends the DPI config with the new active stage
    active_dpi_requested = Signal(list, int)

    # debounce window (ms) so dragging a slider applies once on pause/release,
    # not on every intermediate value
    APPLY_DEBOUNCE_MS = 250

    def __init__(self, dpi=None, colors=None, enabled_count=6):
        super().__init__()
        dpi = dpi or DEFAULT_DPI
        colors = colors or DEFAULT_COLORS
        self._suspend_apply = False  # set while programmatically loading values
        self._selected = _D.DPI_SELECTED  # absolute active-stage index (0-based)

        # debounce timer for auto-apply
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(self.APPLY_DEBOUNCE_MS)
        self._apply_timer.timeout.connect(self._emit_apply)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        # header
        title = QLabel("DPI Stages")
        title.setProperty("panelTitle", "true")
        root.addWidget(title)
        sub = QLabel("Configure resolution stages and their indicator colors. "
                     "Click a stage number to make it the active DPI.")
        sub.setProperty("panelSubtitle", "true")
        root.addWidget(sub)
        root.addWidget(_hline())

        # scrollable stage list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)

        # fallback DPI for rows beyond the provided list / beyond DEFAULT_DPI
        def fallback_dpi(i):
            if i < len(DEFAULT_DPI):
                return DEFAULT_DPI[i]
            return DPI_MAX

        self.rows = []
        for i in range(8):
            row = StageRow(
                i,
                dpi[i] if i < len(dpi) else fallback_dpi(i),
                colors[i] if i < len(colors) else DEFAULT_COLORS[i % len(DEFAULT_COLORS)],
                enabled=i < enabled_count,
            )
            row.edited.connect(self._on_any_edit)
            row.activate_requested.connect(self._on_activate_requested)
            self.rows.append(row)
            col.addWidget(row)
        col.addStretch(1)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)

        # reflect the initial active stage
        self.set_active_stage(self._selected)

    def _on_any_edit(self):
        # auto-apply (debounced); ignore edits we triggered programmatically
        if self._suspend_apply:
            return
        self._apply_timer.start()

    def _on_activate_requested(self, abs_index):
        """User clicked a stage number -> make it the active DPI on the device.

        CONFIRMED via USB capture (session 9j): switching the live DPI is done
        by re-sending the class-0x02 DPI config as a PAIR of packets with the
        new `selected`. So we emit the enabled DPI values + the selected index
        within that enabled list, and the controller calls set_active_dpi().
        Updates the highlight immediately; the switch is not debounced.
        """
        if self._suspend_apply:
            return
        if not self.rows[abs_index].is_enabled():
            return
        self._selected = abs_index
        self.set_active_stage(abs_index)
        enabled = self._enabled_indices()
        dpis = [self.rows[i].dpi() for i in enabled]
        sel = enabled.index(abs_index)
        # any pending debounced full-config apply is redundant now; cancel it
        self._apply_timer.stop()
        self.active_dpi_requested.emit(dpis, sel)

    def _enabled_indices(self):
        return [i for i, r in enumerate(self.rows) if r.is_enabled()]

    def _emit_apply(self):
        enabled = self._enabled_indices()
        if not enabled:
            return
        dpis = [self.rows[i].dpi() for i in enabled]
        cols = [self.rows[i].rgb() for i in enabled]
        # the device's `selected` is an index into the enabled list; clamp if the
        # active stage was just disabled
        if self._selected in enabled:
            sel = enabled.index(self._selected)
        else:
            sel = 0
            self._selected = enabled[0]
            self.set_active_stage(self._selected)
        self.apply_requested.emit(dpis, cols, sel)

    def set_active_stage(self, level: int):
        """Highlight the stage at `level` (0-based absolute index among 8 rows)."""
        self._selected = level
        for i, row in enumerate(self.rows):
            row.set_active(i == level)

    def set_values(self, dpi, colors=None, enabled_count=None):
        """Set the stage DPI values (and optionally colors) from outside, e.g.
        after a factory restore. Does NOT auto-apply (the caller pushes)."""
        self._suspend_apply = True
        try:
            for i, row in enumerate(self.rows):
                if i < len(dpi):
                    row.slider.blockSignals(True)
                    row.slider.setValue(dpi[i])
                    row.slider.blockSignals(False)
                    row.value.setText(str(row._snap(dpi[i])))
                if colors and i < len(colors):
                    row.swatch.set_rgb(colors[i])
                if enabled_count is not None:
                    row.toggle.blockSignals(True)
                    row.toggle.setChecked(i < enabled_count)
                    row.toggle.blockSignals(False)
                    row._sync_enabled()
        finally:
            self._suspend_apply = False
