"""
app.theme -- the "Precision Instrument" dark theme: palette, fonts, and a global
Qt stylesheet (QSS). Calm, technical, one sharp accent. Monospace numeric
readouts are the signature detail.
"""

# --- Palette ----------------------------------------------------------------
BG        = "#0E1116"
SURFACE   = "#161B22"
SURFACE_2 = "#1C232C"
BORDER    = "#2A323D"
TEXT      = "#E6EDF3"
TEXT_DIM  = "#8B949E"
ACCENT    = "#FF6B35"   # sharp warm orange, used sparingly for active state
ACCENT_2  = "#36C5F0"   # cool cyan, secondary
GOOD      = "#3FB950"
WARN      = "#D29922"
BAD       = "#F85149"

# --- Font stacks (no bundling; fall back cleanly across platforms) ----------
# Technical sans for UI; platform monospace for numeric "readout" values.
FONT_UI = '"Geist", "Segoe UI Variable", "Segoe UI", "Inter", system-ui, sans-serif'
FONT_MONO = '"Cascadia Code", "Cascadia Mono", "Consolas", "JetBrains Mono", "SF Mono", monospace'


try:
    from PySide6.QtGui import QPalette, QColor
except ImportError:  # pragma: no cover
    QPalette = None
    QColor = None


def dark_palette():
    """Return an application-wide dark QPalette matching the Precision Instrument theme."""
    if QPalette is None or QColor is None:
        return None
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(SURFACE))
    pal.setColor(QPalette.AlternateBase, QColor(SURFACE_2))
    pal.setColor(QPalette.ToolTipBase, QColor(SURFACE))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(SURFACE_2))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.BrightText, QColor(ACCENT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#1A1008"))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_DIM))
    pal.setColor(QPalette.Midlight, QColor(BORDER))
    pal.setColor(QPalette.Dark, QColor(BG))
    pal.setColor(QPalette.Mid, QColor(BORDER))
    pal.setColor(QPalette.Shadow, QColor(BG))
    return pal


def stylesheet() -> str:
    """Return the global QSS string."""
    return f"""
    * {{
        font-family: {FONT_UI};
        color: {TEXT};
        font-size: 13px;
    }}
    QMainWindow, QWidget#root {{
        background: {BG};
    }}

    /* ---- Left navigation rail ---- */
    QFrame#railFrame {{
        background: {SURFACE};
        border: none;
        border-right: 1px solid {BORDER};
    }}
    QListWidget#nav {{
        background: transparent;
        border: none;
        outline: 0;
        padding: 8px 6px;
    }}
    QListWidget#nav::item {{
        padding: 10px 14px;
        margin: 2px 4px;
        border-radius: 6px;
        color: {TEXT_DIM};
    }}
    QListWidget#nav::item:hover {{
        background: {SURFACE_2};
        color: {TEXT};
    }}
    QListWidget#nav::item:selected {{
        background: {SURFACE_2};
        color: {TEXT};
        border-left: 2px solid {ACCENT};
    }}

    /* ---- Top bar ---- */
    QFrame#topbar {{
        background: {SURFACE};
        border-bottom: 1px solid {BORDER};
    }}
    QLabel#deviceName {{
        font-size: 15px;
        font-weight: 600;
        letter-spacing: 0.3px;
    }}
    QLabel[pill="true"] {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 3px 10px;
        color: {TEXT_DIM};
        font-size: 11px;
    }}
    QLabel#dpiReadout {{
        font-family: {FONT_MONO};
        color: {ACCENT};
        font-size: 13px;
        font-weight: 600;
    }}
    QLabel#rateReadout {{
        font-family: {FONT_MONO};
        color: {ACCENT_2};
        font-size: 13px;
        font-weight: 600;
    }}

    /* ---- Panel scaffolding ---- */
    QLabel[panelTitle="true"] {{
        font-size: 18px;
        font-weight: 600;
        letter-spacing: 0.3px;
        padding: 0;
    }}
    QLabel[panelSubtitle="true"] {{
        color: {TEXT_DIM};
        font-size: 12px;
    }}
    QFrame[sep="true"] {{
        background: {BORDER};
        max-height: 1px;
        min-height: 1px;
        border: none;
    }}

    /* ---- Buttons panel rows ---- */
    QFrame#btnRow {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 8px;
    }}
    QLabel#btnBadge {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 13px;
        color: {ACCENT};
        font-family: {FONT_MONO};
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#actionField {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 8px 12px;
        text-align: left;
        color: {TEXT};
    }}
    QPushButton#actionField:hover {{
        border-color: {ACCENT};
    }}
    QLabel[groupLabel="true"] {{
        color: {TEXT_DIM};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QFrame#mouseRef {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 8px;
    }}

    /* ---- Reset (factory) button under the nav ---- */
    QPushButton#resetBtn {{
        background: transparent;
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 8px 12px;
        color: {TEXT_DIM};
        margin: 0px 10px;
    }}
    QPushButton#resetBtn:hover {{
        border-color: {WARN};
        color: {WARN};
    }}

    /* ---- Battery / status pill ---- */
    QLabel#battery {{
        font-family: {FONT_MONO};
        font-size: 12px;
        color: {TEXT_DIM};
    }}

    /* ---- DPI stage rows (object-name based; toggled live) ---- */
    QFrame#stageRow {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 8px;
    }}
    QFrame#stageRowActive {{
        background: {SURFACE_2};
        border: 1px solid {ACCENT};
        border-left: 3px solid {ACCENT};
        border-radius: 8px;
    }}
    QLabel[stageIndex="true"] {{
        color: {TEXT_DIM};
        font-family: {FONT_MONO};
        font-size: 12px;
    }}
    QLabel[stageIndexActive="true"] {{
        color: {ACCENT};
        font-family: {FONT_MONO};
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel#dpiValue {{
        font-family: {FONT_MONO};
        font-size: 20px;
        font-weight: 600;
        color: {TEXT};
    }}
    QLabel#dpiValueActive {{
        font-family: {FONT_MONO};
        font-size: 20px;
        font-weight: 600;
        color: {ACCENT};
    }}
    QLabel[unit="true"] {{
        color: {TEXT_DIM};
        font-family: {FONT_MONO};
        font-size: 11px;
    }}

    /* ---- Sliders ---- */
    QSlider::groove:horizontal {{
        height: 4px;
        background: {SURFACE_2};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {ACCENT};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {TEXT};
        width: 14px;
        height: 14px;
        margin: -6px 0;
        border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{
        background: {ACCENT};
    }}
    QSlider:disabled {{ }}
    QSlider::sub-page:horizontal:disabled {{ background: {BORDER}; }}
    QSlider::handle:horizontal:disabled {{ background: {BORDER}; }}

    /* ---- Buttons ---- */
    QPushButton {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 8px 16px;
        color: {TEXT};
    }}
    QPushButton:hover {{
        border-color: {TEXT_DIM};
    }}
    QPushButton:pressed {{
        background: {SURFACE};
    }}
    QPushButton#primary {{
        background: {ACCENT};
        border: 1px solid {ACCENT};
        color: #1a1008;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{
        background: #ff7d4d;
    }}
    QPushButton#primary:disabled {{
        background: {SURFACE_2};
        border-color: {BORDER};
        color: {TEXT_DIM};
    }}

    /* ---- Checkboxes / toggles ---- */
    QCheckBox {{
        spacing: 8px;
        color: {TEXT_DIM};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {BORDER};
        background: {SURFACE_2};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}

    /* ---- Combo boxes ---- */
    QComboBox {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 10px;
        min-width: 120px;
    }}
    QComboBox:hover {{ border-color: {TEXT_DIM}; }}
    QComboBox QAbstractItemView {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT};
        selection-color: #1a1008;
        outline: 0;
    }}

    /* ---- Profile selector (rail) ---- */
    QComboBox#profileCombo {{ min-width: 0; }}
    QToolButton#profileMenuBtn {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 6px;
        color: {TEXT_DIM};
        font-size: 16px;
        font-weight: bold;
        padding: 0;
    }}
    QToolButton#profileMenuBtn:hover {{ border-color: {TEXT_DIM}; color: {TEXT}; }}
    /* the three-dots button must NOT draw Qt's auto menu-arrow (it overlapped the dots) */
    QToolButton#profileMenuBtn::menu-indicator {{ image: none; width: 0; height: 0; }}

    /* ---- Popup menus (e.g. the profile actions menu) ---- */
    QMenu {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        padding: 4px;
    }}
    QMenu::item {{ padding: 6px 18px; color: {TEXT}; border-radius: 4px; }}
    QMenu::item:selected {{ background: {ACCENT}; color: #1a1008; }}

    /* ---- Segmented selector (e.g. polling rate, LOD) ---- */
    QPushButton[segment="true"] {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 9px 18px;
        color: {TEXT_DIM};
        font-weight: 500;
    }}
    QPushButton[segment="true"]:hover {{
        border-color: {TEXT_DIM};
        color: {TEXT};
    }}
    QPushButton[segment="true"][selected="true"] {{
        background: {ACCENT};
        border: 1px solid {ACCENT};
        color: #1a1008;
        font-weight: 600;
    }}
    QPushButton[segment="true"][selected="true"]:hover {{
        background: #ff7d4d;
    }}
    QPushButton[segment="true"]:disabled {{
        color: {BORDER};
        border-color: {SURFACE_2};
    }}

    /* ---- Settings card (Lighting / Performance sections) ---- */
    QFrame[card="true"] {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 8px;
    }}
    QLabel[cardTitle="true"] {{
        font-size: 13px;
        font-weight: 600;
        letter-spacing: 0.5px;
        color: {TEXT};
    }}
    QLabel[cardHint="true"] {{
        color: {TEXT_DIM};
        font-size: 11px;
    }}
    QLabel[monoValue="true"] {{
        font-family: {FONT_MONO};
        font-size: 16px;
        font-weight: 600;
        color: {ACCENT};
    }}

    /* ---- Generic lists (macro library, event list) ---- */
    QListWidget {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 8px;
        outline: 0;
        padding: 4px;
    }}
    QListWidget::item {{
        padding: 8px 10px;
        border-radius: 6px;
        color: {TEXT_DIM};
    }}
    QListWidget::item:hover {{
        background: {SURFACE_2};
        color: {TEXT};
    }}
    QListWidget::item:selected {{
        background: {SURFACE_2};
        color: {TEXT};
        border-left: 2px solid {ACCENT};
    }}
    QTableWidget#macroEvents {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 8px;
        outline: 0;
        gridline-color: {BORDER};
    }}
    QTableWidget#macroEvents::item {{
        padding: 0px;
        color: {TEXT};
    }}
    QTableWidget#macroEvents::item:selected {{
        background: {SURFACE_2};
        color: {ACCENT};
    }}
    QTableWidget#macroEvents QComboBox {{
        min-width: 0;
        padding: 4px 6px;
        background: transparent;
    }}
    QTableWidget#macroEvents QSpinBox {{
        min-width: 0;
        padding: 4px 4px;
        background: transparent;
    }}
    QTableWidget#macroEvents QToolButton {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 4px;
        color: {TEXT_DIM};
        font-size: 12px;
        padding: 1px;
        min-width: 22px;
        max-width: 28px;
        min-height: 22px;
    }}
    QTableWidget#macroEvents QToolButton:hover {{
        border-color: {ACCENT};
        color: {TEXT};
    }}
    QHeaderView::section {{
        background: {SURFACE_2};
        color: {TEXT_DIM};
        border: none;
        border-bottom: 1px solid {BORDER};
        padding: 6px 8px;
        font-size: 11px;
        font-weight: 600;
    }}
    QTableCornerButton::section {{
        background: {SURFACE_2};
        border: none;
    }}

    /* ---- Text & number inputs ---- */
    QLineEdit {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 7px 10px;
        color: {TEXT};
        selection-background-color: {ACCENT};
        selection-color: #1a1008;
    }}
    QLineEdit:focus {{
        border-color: {ACCENT};
    }}
    QSpinBox {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 5px 8px;
        color: {TEXT};
        min-width: 60px;
    }}
    QSpinBox:focus {{
        border-color: {ACCENT};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        width: 16px;
        border: none;
        background: transparent;
    }}

    /* ---- Scrollbars & Scroll Areas ---- */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER};
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollArea > QWidget#qt_scrollarea_viewport {{
        background: transparent;
    }}
    """
