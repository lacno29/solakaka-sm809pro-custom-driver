"""
app.widgets.overlay -- a small on-screen HUD (Milestone 3 step 5, optional).

A frameless, always-on-top, click-through translucent card that briefly appears
near the bottom of the primary screen to show DPI changes (from the Col04 status
push, incl. the physical DPI button) and profile switches (manual or auto). It
auto-hides after a short delay and fades out. Read-only display fed by existing
controller/profile signals; it never writes to the device.
"""

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation
from PySide6.QtGui import QGuiApplication, QCursor
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QLabel, QPushButton,
)

from .. import theme


POSITIONS = [
    "top-left", "top-center", "top-right",
    "mid-left", "center", "mid-right",
    "bottom-left", "bottom-center", "bottom-right",
]
POSITION_LABELS = {
    "top-left": "Top-left", "top-center": "Top-center", "top-right": "Top-right",
    "mid-left": "Mid-left", "center": "Center", "mid-right": "Mid-right",
    "bottom-left": "Bottom-left", "bottom-center": "Bottom-center",
    "bottom-right": "Bottom-right",
}


def _target_screen(widget, follow_cursor, monitor_index):
    """The monitor to place an overlay on: the one under the cursor (if
    following), else the chosen fixed monitor; falls back sensibly."""
    screens = QGuiApplication.screens()
    if follow_cursor:
        return (QGuiApplication.screenAt(QCursor.pos())
                or widget.screen() or QGuiApplication.primaryScreen())
    if 0 <= monitor_index < len(screens):
        return screens[monitor_index]
    return QGuiApplication.primaryScreen()


def place_widget(widget, pos, follow_cursor, monitor_index, margin=40):
    """Move `widget` to the `pos` corner/edge/center of its target screen."""
    screen = _target_screen(widget, follow_cursor, monitor_index)
    if screen is None:
        return
    geo = screen.availableGeometry()
    w = max(widget.width(), widget.sizeHint().width())
    h = max(widget.height(), widget.sizeHint().height())
    if "left" in pos:
        x = geo.x() + margin
    elif "right" in pos:
        x = geo.x() + geo.width() - w - margin
    else:
        x = geo.x() + (geo.width() - w) // 2
    if "top" in pos:
        y = geo.y() + margin
    elif "bottom" in pos:
        y = geo.y() + geo.height() - h - margin
    else:
        y = geo.y() + (geo.height() - h) // 2
    widget.move(x, y)


class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        # appearance (set via set_appearance from saved settings)
        self._pos = "bottom-center"
        self._opacity_shown = 0.92      # opacity while visible (transparency)
        self._scale = 1.0               # size multiplier
        self._hold_ms = 1400            # how long it stays before fading
        self._follow_cursor = True      # show on the monitor under the cursor
        self._monitor_index = 0         # fixed monitor when not following cursor
        # frameless, on-top, not in the taskbar, and transparent to input so it
        # never steals clicks from the game/app underneath it.
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame()
        self.card.setObjectName("overlayCard")
        self.card.setStyleSheet(
            f"#overlayCard {{ background: {theme.SURFACE_2}; border: 1px solid "
            f"{theme.BORDER}; border-radius: 12px; }}")
        wrap.addWidget(self.card)

        self._lay = QVBoxLayout(self.card)
        self._lay.setSpacing(2)
        self._restyle()

        # fade-out via the WINDOW opacity (not a QGraphicsOpacityEffect: on a
        # translucent frameless window that effect paints an opaque black box
        # behind letter-spaced labels -- the "black bars" bug).
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(350)
        self._fade.finished.connect(self._on_faded)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._start_fade)

    def _cap_style(self):
        s = self._scale
        return (f"color: {theme.TEXT_DIM}; font-family: {theme.FONT_MONO}; "
                f"font-size: {int(11 * s)}px; letter-spacing: 2px;")

    def _val_style(self):
        s = self._scale
        return (f"color: {theme.ACCENT}; font-family: {theme.FONT_MONO}; "
                f"font-size: {int(30 * s)}px; font-weight: 600;")

    def _restyle(self):
        s = self._scale
        self._lay.setContentsMargins(int(28 * s), int(16 * s), int(28 * s), int(16 * s))
        self.card.setStyleSheet(
            f"#overlayCard {{ background: {theme.SURFACE_2}; border: 1px solid "
            f"{theme.BORDER}; border-radius: {int(12 * s)}px; }}")

    def set_appearance(self, position=None, opacity_pct=None, scale_pct=None,
                       hold_ms=None, follow_cursor=None, monitor_index=None):
        """Configure where it appears, its visible opacity (transparency), its
        size scale, how long it stays, and which monitor it uses (follow the
        cursor, or a fixed monitor). Persisted/loaded by MainWindow."""
        if position in POSITIONS:
            self._pos = position
        if opacity_pct is not None:
            self._opacity_shown = max(0.2, min(1.0, opacity_pct / 100.0))
        if scale_pct is not None:
            self._scale = max(0.6, min(2.0, scale_pct / 100.0))
            self._restyle()
        if hold_ms is not None:
            self._hold_ms = max(300, int(hold_ms))
        if follow_cursor is not None:
            self._follow_cursor = bool(follow_cursor)
        if monitor_index is not None:
            self._monitor_index = max(0, int(monitor_index))

    def flash(self, value, caption="DPI", hold_ms=None):
        """Show a single (caption, value) line."""
        self.flash_lines([(caption, value)], hold_ms)

    def flash_lines(self, lines, hold_ms=None):
        """Show one or more (caption, value) rows together, then auto-hide.
        Used so the overlay can display Profile / DPI / Polling-rate at once."""
        # clear previous rows
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for cap, val in lines:
            c = QLabel(str(cap).upper())
            c.setAlignment(Qt.AlignCenter)
            c.setStyleSheet(self._cap_style())
            self._lay.addWidget(c)
            v = QLabel(str(val))
            v.setAlignment(Qt.AlignCenter)
            v.setStyleSheet(self._val_style())
            self._lay.addWidget(v)
        self._restyle()
        self._fade.stop()
        self.setWindowOpacity(self._opacity_shown)
        self.layout().activate()        # compute child sizes now (synchronous)
        self.adjustSize()
        self._reposition()              # position from sizeHint before showing
        self.show()
        self.raise_()
        # geometry is only final after the window is realized; re-place once the
        # event loop has processed the resize (fixes the first-flash / multi-
        # monitor mis-placement that show()-then-move alone didn't).
        QTimer.singleShot(0, self._reposition)
        self._hide_timer.start(hold_ms or self._hold_ms)

    def _reposition(self):
        place_widget(self, self._pos, self._follow_cursor, self._monitor_index)

    def _start_fade(self):
        self._fade.stop()
        self._fade.setStartValue(self._opacity_shown)
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_faded(self):
        if self.windowOpacity() <= 0.01:
            self.hide()


class AlertOverlay(QWidget):
    """A persistent, MANUALLY-dismissed on-screen alert (battery low / full).

    Unlike Overlay it accepts input (so its Dismiss button works) and never
    auto-hides. It shares the same appearance settings (position / opacity / size
    / monitor) as the main overlay for consistency.
    """

    def __init__(self):
        super().__init__()
        self._pos = "bottom-center"
        self._opacity_shown = 0.92
        self._scale = 1.0
        self._follow_cursor = True
        self._monitor_index = 0
        # frameless + on-top + not in taskbar; NOT click-through (Dismiss must be
        # clickable) and doesn't grab focus from a game.
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame()
        self.card.setObjectName("alertCard")
        wrap.addWidget(self.card)
        self._lay = QVBoxLayout(self.card)
        self._lay.setSpacing(4)

        self.caption = QLabel("")
        self.caption.setAlignment(Qt.AlignCenter)
        self._lay.addWidget(self.caption)
        self.value = QLabel("")
        self.value.setAlignment(Qt.AlignCenter)
        self._lay.addWidget(self.value)
        self.dismiss = QPushButton("Dismiss")
        self.dismiss.setCursor(Qt.PointingHandCursor)
        self.dismiss.clicked.connect(self.hide)
        self._lay.addWidget(self.dismiss)
        self._restyle()

    def set_appearance(self, position=None, opacity_pct=None, scale_pct=None,
                       follow_cursor=None, monitor_index=None, **_):
        """Shares the overlay's position/opacity/size/monitor settings (ignores
        hold_ms via **_, since an alert stays until dismissed)."""
        if position in POSITIONS:
            self._pos = position
        if opacity_pct is not None:
            self._opacity_shown = max(0.2, min(1.0, opacity_pct / 100.0))
        if scale_pct is not None:
            self._scale = max(0.6, min(2.0, scale_pct / 100.0))
            self._restyle()
        if follow_cursor is not None:
            self._follow_cursor = bool(follow_cursor)
        if monitor_index is not None:
            self._monitor_index = max(0, int(monitor_index))

    def _restyle(self, accent=None):
        s = self._scale
        self._lay.setContentsMargins(int(28 * s), int(16 * s), int(28 * s), int(16 * s))
        self.card.setStyleSheet(
            f"#alertCard {{ background: {theme.SURFACE_2}; border: 1px solid "
            f"{theme.BORDER}; border-radius: {int(12 * s)}px; }}")
        self.caption.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-family: {theme.FONT_MONO}; "
            f"font-size: {int(11 * s)}px; letter-spacing: 2px;")
        self.value.setStyleSheet(
            f"color: {accent or theme.ACCENT}; font-family: {theme.FONT_MONO}; "
            f"font-size: {int(28 * s)}px; font-weight: 600;")
        self.dismiss.setStyleSheet(
            f"QPushButton {{ background: {theme.SURFACE}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 6px; "
            f"padding: {int(6 * s)}px {int(16 * s)}px; margin-top: {int(6 * s)}px; }}"
            f"QPushButton:hover {{ border-color: {theme.TEXT_DIM}; }}")

    def alert(self, caption, value, accent=None):
        """Show a persistent alert with a coloured value; stays until dismissed."""
        self.caption.setText(str(caption).upper())
        self.value.setText(str(value))
        self._restyle(accent)
        self.setWindowOpacity(self._opacity_shown)
        self.layout().activate()
        self.adjustSize()
        place_widget(self, self._pos, self._follow_cursor, self._monitor_index)
        self.show()
        self.raise_()
        QTimer.singleShot(0, lambda: place_widget(
            self, self._pos, self._follow_cursor, self._monitor_index))
