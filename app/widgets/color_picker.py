"""
app.widgets.color_picker -- a themed color picker dialog.

Qt's native QColorDialog renders with platform styling and a live-preview
background that bleeds through and hurts contrast. This is a small custom dialog
that uses the app's own dark palette: a saturation/value field, a hue strip,
RGB + hex inputs, and a fixed (non-adaptive) dark background.

Usage:
    rgb = pick_color((255, 0, 0), parent)   # returns (r,g,b) or None if cancelled
"""

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QPen
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QFrame,
)

from .. import theme


class _SVField(QWidget):
    """Saturation (x) / Value (y) square for the currently selected hue."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(240, 200)
        self.setCursor(Qt.CrossCursor)
        self._hue = 0.0   # 0..1
        self._sat = 1.0
        self._val = 1.0

    def set_hue(self, h):
        self._hue = h
        self.update()

    def set_sv(self, s, v):
        self._sat, self._val = s, v
        self.update()

    def sv(self):
        return self._sat, self._val

    def paintEvent(self, _):
        p = QPainter(self)
        rect = self.rect()
        base = QColor.fromHsvF(self._hue, 1.0, 1.0)
        gx = QLinearGradient(rect.topLeft(), rect.topRight())
        gx.setColorAt(0, QColor(255, 255, 255))
        gx.setColorAt(1, base)
        p.fillRect(rect, gx)
        gy = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gy.setColorAt(0, QColor(0, 0, 0, 0))
        gy.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(rect, gy)
        x = int(self._sat * rect.width())
        y = int((1.0 - self._val) * rect.height())
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawEllipse(QPoint(x, y), 5, 5)
        p.setPen(QPen(QColor(0, 0, 0), 1))
        p.drawEllipse(QPoint(x, y), 6, 6)

    def _set_from_pos(self, pos):
        w, h = self.width(), self.height()
        self._sat = min(1.0, max(0.0, pos.x() / w))
        self._val = min(1.0, max(0.0, 1.0 - pos.y() / h))
        self.update()
        self.changed.emit()

    def mousePressEvent(self, e):
        self._set_from_pos(e.position().toPoint())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._set_from_pos(e.position().toPoint())


class _HueStrip(QWidget):
    """Vertical hue selector."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(22, 200)
        self.setCursor(Qt.PointingHandCursor)
        self._hue = 0.0

    def set_hue(self, h):
        self._hue = h
        self.update()

    def hue(self):
        return self._hue

    def paintEvent(self, _):
        p = QPainter(self)
        rect = self.rect()
        g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        for i in range(7):
            g.setColorAt(i / 6.0, QColor.fromHsvF(i / 6.0, 1.0, 1.0))
        p.fillRect(rect, g)
        y = int(self._hue * rect.height())
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(0, y, rect.width(), y)
        p.setPen(QPen(QColor(0, 0, 0), 1))
        p.drawLine(0, y + 1, rect.width(), y + 1)

    def _set_from_pos(self, pos):
        self._hue = min(0.9999, max(0.0, pos.y() / self.height()))
        self.update()
        self.changed.emit()

    def mousePressEvent(self, e):
        self._set_from_pos(e.position().toPoint())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._set_from_pos(e.position().toPoint())


# Preset swatches shown in the grid (mirrors the official picker's palette).
PRESET_COLORS = [
    (255, 0, 0), (0, 0, 255), (0, 255, 0), (255, 255, 0), (0, 255, 255), (255, 0, 255),
    (255, 255, 255), (88, 196, 188), (90, 160, 200), (150, 200, 150), (240, 200, 120), (255, 160, 220),
    (90, 150, 240), (120, 80, 220), (0, 200, 200), (240, 160, 70), (40, 170, 130), (230, 110, 50),
]


class ColorPicker(QDialog):
    """A fully-themed color picker: preset grid + optional custom SV/hue editor."""

    def __init__(self, rgb=(255, 0, 0), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Level Color")
        self.setModal(True)
        self._r, self._g, self._b = rgb
        self._custom_open = False
        # hard dark background so nothing adapts to the chosen color
        self.setStyleSheet(f"""
            QDialog {{ background: {theme.BG}; }}
            QLabel {{ color: {theme.TEXT}; }}
            QLineEdit {{
                background: {theme.SURFACE_2}; border: 1px solid {theme.BORDER};
                border-radius: 5px; padding: 5px 8px; color: {theme.TEXT};
                font-family: {theme.FONT_MONO};
            }}
            QLineEdit:focus {{ border-color: {theme.ACCENT}; }}
            QPushButton {{
                background: {theme.SURFACE_2}; border: 1px solid {theme.BORDER};
                border-radius: 6px; padding: 7px 16px; color: {theme.TEXT};
            }}
            QPushButton:hover {{ border-color: {theme.TEXT_DIM}; }}
            QPushButton#ok {{
                background: {theme.ACCENT}; border: 1px solid {theme.ACCENT};
                color: #1a1008; font-weight: 600;
            }}
            QPushButton#ok:hover {{ background: #ff7d4d; }}
            QPushButton#customToggle {{ text-align: left; padding: 8px 10px; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ---- preset swatch grid (6 columns) ----
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self._preset_btns = []
        for i, col in enumerate(PRESET_COLORS):
            sw = QPushButton()
            sw.setFixedSize(54, 36)
            sw.setCursor(Qt.PointingHandCursor)
            r, g, b = col
            sw.setStyleSheet(
                f"background: rgb({r},{g},{b}); border: 2px solid transparent; "
                f"border-radius: 7px;"
            )
            sw.clicked.connect(lambda _=False, c=col: self._pick_preset(c))
            self._preset_btns.append((sw, col))
            grid.addWidget(sw, i // 6, i % 6)
        root.addLayout(grid)

        # ---- custom color toggle row ----
        toggle_row = QHBoxLayout()
        self.custom_swatch = QFrame()
        self.custom_swatch.setFixedSize(22, 22)
        self._refresh_custom_swatch()
        toggle_row.addWidget(self.custom_swatch)
        self.custom_toggle = QPushButton("Custom Color  \u25be")
        self.custom_toggle.setObjectName("customToggle")
        self.custom_toggle.clicked.connect(self._toggle_custom)
        toggle_row.addWidget(self.custom_toggle)
        toggle_row.addStretch(1)
        root.addLayout(toggle_row)

        # ---- collapsible custom editor ----
        self.custom_area = QWidget()
        ca = QVBoxLayout(self.custom_area)
        ca.setContentsMargins(0, 0, 0, 0)
        ca.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.field = _SVField()
        self.hue = _HueStrip()
        top.addWidget(self.field)
        top.addWidget(self.hue)
        right = QVBoxLayout()
        right.setSpacing(8)
        self.preview = QFrame()
        self.preview.setFixedSize(80, 40)
        right.addWidget(self.preview)
        igrid = QGridLayout()
        igrid.setHorizontalSpacing(6); igrid.setVerticalSpacing(6)
        self.in_r = QLineEdit(); self.in_g = QLineEdit(); self.in_b = QLineEdit()
        for lbl, fld, rr in (("R", self.in_r, 0), ("G", self.in_g, 1), ("B", self.in_b, 2)):
            cap = QLabel(lbl); cap.setFixedWidth(14)
            fld.setFixedWidth(56)
            fld.editingFinished.connect(self._from_rgb_inputs)
            igrid.addWidget(cap, rr, 0); igrid.addWidget(fld, rr, 1)
        right.addLayout(igrid)
        hexrow = QHBoxLayout()
        hc = QLabel("HEX"); hc.setFixedWidth(28)
        self.in_hex = QLineEdit(); self.in_hex.setFixedWidth(80)
        self.in_hex.editingFinished.connect(self._from_hex_input)
        hexrow.addWidget(hc); hexrow.addWidget(self.in_hex)
        right.addLayout(hexrow)
        right.addStretch(1)
        top.addLayout(right)
        top.addStretch(1)
        ca.addLayout(top)
        self.custom_area.setVisible(False)
        root.addWidget(self.custom_area)

        # ---- footer ----
        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        ok = QPushButton("Confirm"); ok.setObjectName("ok"); ok.clicked.connect(self.accept)
        footer.addWidget(cancel); footer.addWidget(ok)
        root.addLayout(footer)

        self.field.changed.connect(self._from_field)
        self.hue.changed.connect(self._from_hue)
        self._set_rgb(rgb, sync_hsv=True)

    # -- preset / custom toggle ----------------------------------------------
    def _pick_preset(self, col):
        self._set_rgb(col, sync_hsv=True)
        self._highlight_selected(col)

    def _highlight_selected(self, col):
        for sw, c in self._preset_btns:
            r, g, b = c
            border = theme.ACCENT if tuple(c) == tuple(col) else "transparent"
            sw.setStyleSheet(
                f"background: rgb({r},{g},{b}); border: 2px solid {border}; "
                f"border-radius: 7px;"
            )

    def _toggle_custom(self):
        self._custom_open = not self._custom_open
        self.custom_area.setVisible(self._custom_open)
        arrow = "\u25b4" if self._custom_open else "\u25be"
        self.custom_toggle.setText(f"Custom Color  {arrow}")
        self.adjustSize()

    def _refresh_custom_swatch(self):
        self.custom_swatch.setStyleSheet(
            f"background: rgb({self._r},{self._g},{self._b}); "
            f"border: 1px solid {theme.BORDER}; border-radius: 5px;"
        )

    # -- conversions ----------------------------------------------------------
    def _set_rgb(self, rgb, sync_hsv=False):
        r, g, b = (max(0, min(255, int(v))) for v in rgb)
        self._r, self._g, self._b = r, g, b
        if sync_hsv:
            c = QColor(r, g, b)
            h, s, v, _ = c.getHsvF()
            self.hue.set_hue(max(0.0, h if (h is not None and h >= 0) else 0.0))
            self.field.set_hue(self.hue.hue())
            self.field.set_sv(s, v)
        self._refresh_outputs()

    def _refresh_outputs(self):
        self.preview.setStyleSheet(
            f"background: rgb({self._r},{self._g},{self._b}); "
            f"border: 1px solid {theme.BORDER}; border-radius: 6px;"
        )
        self._refresh_custom_swatch()
        for fld, val in ((self.in_r, self._r), (self.in_g, self._g), (self.in_b, self._b)):
            fld.blockSignals(True); fld.setText(str(val)); fld.blockSignals(False)
        self.in_hex.blockSignals(True)
        self.in_hex.setText(f"{self._r:02X}{self._g:02X}{self._b:02X}")
        self.in_hex.blockSignals(False)

    def _from_field(self):
        s, v = self.field.sv()
        c = QColor.fromHsvF(self.hue.hue(), s, v)
        self._set_rgb((c.red(), c.green(), c.blue()))

    def _from_hue(self):
        self.field.set_hue(self.hue.hue())
        self._from_field()

    def _from_rgb_inputs(self):
        def parse(fld, cur):
            try:
                return max(0, min(255, int(fld.text())))
            except ValueError:
                return cur
        self._set_rgb((parse(self.in_r, self._r), parse(self.in_g, self._g),
                       parse(self.in_b, self._b)), sync_hsv=True)

    def _from_hex_input(self):
        t = self.in_hex.text().strip().lstrip("#")
        if len(t) == 6:
            try:
                self._set_rgb((int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)), sync_hsv=True)
                return
            except ValueError:
                pass
        self._refresh_outputs()

    def selected_rgb(self):
        return (self._r, self._g, self._b)


def pick_color(rgb=(255, 0, 0), parent=None):
    """Show the themed picker; return (r,g,b) or None if cancelled."""
    dlg = ColorPicker(rgb, parent)
    if dlg.exec() == QDialog.Accepted:
        return dlg.selected_rgb()
    return None
