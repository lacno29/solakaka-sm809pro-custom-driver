"""
app.widgets.controls -- small reusable themed controls used by the settings
panels (Lighting, Performance): a Card container and a Segmented selector.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QButtonGroup,
)


class Card(QFrame):
    """A titled settings card (surface panel with a heading + optional hint)."""
    def __init__(self, title, hint=None):
        super().__init__()
        self.setProperty("card", "true")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 18)
        lay.setSpacing(12)

        head = QLabel(title)
        head.setProperty("cardTitle", "true")
        lay.addWidget(head)
        if hint:
            h = QLabel(hint)
            h.setProperty("cardHint", "true")
            h.setWordWrap(True)
            lay.addWidget(h)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(12)
        lay.addLayout(self.body)

    def add(self, w):
        if isinstance(w, (QVBoxLayout, QHBoxLayout)):
            self.body.addLayout(w)
        else:
            self.body.addWidget(w)
        return w


class Segmented(QWidget):
    """A horizontal segmented selector (mutually-exclusive pill buttons).

    options: list of (label, value). Emits `changed(value)` on user click.
    """
    changed = Signal(object)

    def __init__(self, options, value=None):
        super().__init__()
        self._buttons = {}           # value -> QPushButton
        self._value = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for label, val in options:
            b = QPushButton(label)
            b.setProperty("segment", "true")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=val: self._on_click(v))
            self._group.addButton(b)
            self._buttons[val] = b
            lay.addWidget(b)
        lay.addStretch(1)
        if value is not None:
            self.set_value(value, emit=False)

    def _restyle(self):
        for val, b in self._buttons.items():
            sel = (val == self._value)
            b.setChecked(sel)
            b.setProperty("selected", "true" if sel else None)
            b.style().unpolish(b)
            b.style().polish(b)

    def _on_click(self, value):
        if value == self._value:
            self._restyle()  # keep the visual in sync (can't unselect)
            return
        self._value = value
        self._restyle()
        self.changed.emit(value)

    def value(self):
        return self._value

    def set_value(self, value, emit=False):
        if value not in self._buttons:
            return
        self._value = value
        self._restyle()
        if emit:
            self.changed.emit(value)

    def setEnabled(self, on):  # noqa: N802 (Qt naming)
        super().setEnabled(on)
        for b in self._buttons.values():
            b.setEnabled(on)
