"""
app.panels.lighting_panel -- the side-button lighting configuration panel.

Mirrors the official app's "Side Button Lighting": a single mode selector and
nothing else. The official app exposes no color picker, and on this firmware the
single-color modes (Red/Green/Blue Full) use their own predefined colors -- a
custom RGB does not take effect (hardware-confirmed). So we expose only the mode.

Brightness/speed/direction are likewise NOT exposed -- on this firmware they have
no observable effect (see LIGHTING_NOTE.md). Changes auto-apply to the mouse.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QFrame, QSizePolicy,
)

from .. import theme
from ..widgets.controls import Card
from sm809pro import protocol as P
from sm809pro import defaults as _D


def _hline():
    f = QFrame()
    f.setProperty("sep", "true")
    f.setFrameShape(QFrame.NoFrame)
    return f


class LightingPanel(QWidget):
    """Side-button lighting: a single mode selector (auto-applies)."""
    # (mode:int, color:(r,g,b)) -- color is kept for the device call but the
    # single-color modes use predefined colors on this firmware.
    apply_requested = Signal(int, tuple)

    def __init__(self, mode=None, color=None):
        super().__init__()
        self._suspend = False
        self._mode = _D.LIGHTING_MODE if mode is None else mode
        self._color = tuple(color) if color else tuple(_D.LIGHTING_COLOR)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        title = QLabel("Lighting")
        title.setProperty("panelTitle", "true")
        root.addWidget(title)
        sub = QLabel("Side-button lighting effect.")
        sub.setProperty("panelSubtitle", "true")
        root.addWidget(sub)
        root.addWidget(_hline())

        # --- Effect card: mode dropdown ---
        card = Card("SIDE BUTTON LIGHTING")
        mode_col = QVBoxLayout()
        mode_col.setSpacing(6)
        mlabel = QLabel("Effect")
        mlabel.setProperty("cardHint", "true")
        mode_col.addWidget(mlabel)
        self.mode_combo = QComboBox()
        for m in sorted(P.LIGHTING_MODES):
            self.mode_combo.addItem(P.LIGHTING_MODES[m], m)
        self.mode_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_col.addWidget(self.mode_combo)
        card.add(mode_col)
        root.addWidget(card)
        root.addStretch(1)

        self._load(self._mode)

    # -- helpers --------------------------------------------------------------
    def _load(self, mode):
        self._suspend = True
        try:
            idx = self.mode_combo.findData(mode)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
            self._mode = mode
        finally:
            self._suspend = False

    # -- events ---------------------------------------------------------------
    def _on_mode_changed(self, _idx):
        if self._suspend:
            return
        self._mode = self.mode_combo.currentData()
        self.apply_requested.emit(self._mode, self._color)

    # -- external -------------------------------------------------------------
    def set_state(self, mode, color=None):
        """Load mode from outside (e.g. factory restore) without applying."""
        if color:
            self._color = tuple(color)
        self._load(mode)
