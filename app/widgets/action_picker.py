"""
app.widgets.action_picker -- the action selection dialog + code<->label helpers.

Mirrors the official software's right-click menu. Produces a 3-byte action code
(type, p1, p2) for a chosen action, and renders any code back to a human label.

Categories (from the official menu + verified codes in sm809pro.actions):
  Mouse, DPI, Fire Key, Three Click, Macro, Key Combination, Multimedia,
  Word Office, Window Management, DPI Lock, Disable.

`pick_action(current_code, parent)` shows the dialog and returns a new code
(tuple) or None if cancelled.
"""

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QStackedWidget, QPushButton, QComboBox, QSpinBox,
    QLineEdit, QCheckBox, QFrame, QGridLayout,
)

from .. import theme
from ..psf_import import VK_TO_HID
from sm809pro import actions as A


def _build_qt_to_hid():
    m = {}
    for i in range(26):
        m[int(Qt.Key_A) + i] = 0x04 + i
    for i in range(1, 10):
        m[int(Qt.Key_0) + i] = 0x1E + (i - 1)
    m[int(Qt.Key_0)] = 0x27
    for i in range(12):
        m[int(Qt.Key_F1) + i] = 0x3A + i
    for i in range(12):
        if hasattr(Qt, f"Key_F{13 + i}"):
            m[int(getattr(Qt, f"Key_F{13 + i}"))] = 0x68 + i
    m.update({
        int(Qt.Key_Space): 0x2C, int(Qt.Key_Return): 0x28, int(Qt.Key_Enter): 0x28,
        int(Qt.Key_Tab): 0x2B, int(Qt.Key_Escape): 0x29, int(Qt.Key_Backspace): 0x2A,
        int(Qt.Key_Delete): 0x4C, int(Qt.Key_Insert): 0x49, int(Qt.Key_Home): 0x4A,
        int(Qt.Key_End): 0x4D, int(Qt.Key_PageUp): 0x4B, int(Qt.Key_PageDown): 0x4E,
        int(Qt.Key_Left): 0x50, int(Qt.Key_Right): 0x4F, int(Qt.Key_Up): 0x52,
        int(Qt.Key_Down): 0x51, int(Qt.Key_CapsLock): 0x39,
        int(Qt.Key_Print): 0x46, int(Qt.Key_ScrollLock): 0x47, int(Qt.Key_Pause): 0x48,
        int(Qt.Key_NumLock): 0x53, int(Qt.Key_Menu): 0x65,
        int(Qt.Key_Minus): 0x2D, int(Qt.Key_Equal): 0x2E, int(Qt.Key_BracketLeft): 0x2F,
        int(Qt.Key_BracketRight): 0x30, int(Qt.Key_Backslash): 0x31,
        int(Qt.Key_Semicolon): 0x33, int(Qt.Key_Apostrophe): 0x34,
        int(Qt.Key_QuoteLeft): 0x35, int(Qt.Key_Comma): 0x36, int(Qt.Key_Period): 0x37,
        int(Qt.Key_Slash): 0x38,
        int(Qt.Key_Asterisk): 0x55, int(Qt.Key_Plus): 0x57,
    })
    return m


_QT_TO_HID = _build_qt_to_hid()


# ---- code -> human label ---------------------------------------------------
# Reverse map from the known named codes for quick description.
_NAMED_BY_CODE = {tuple(v): k for k, v in A.BTN.items()}
_HID_NAME = {v: k for k, v in A.HID.items()}

# Optional resolver set by the app: macro_id -> display name (for dict bindings).
_MACRO_RESOLVER = None


def set_macro_resolver(fn):
    global _MACRO_RESOLVER
    _MACRO_RESOLVER = fn


def _mod_str(mask):
    parts = []
    if mask & A.MOD_CTRL:  parts.append("Ctrl")
    if mask & A.MOD_SHIFT: parts.append("Shift")
    if mask & A.MOD_ALT:   parts.append("Alt")
    if mask & A.MOD_WIN:   parts.append("Win")
    return "+".join(parts)


def describe_action(code) -> str:
    """Render an action as a label: a 3-byte code, a {'macro':id,..} binding, or
    a {'runapp': path} host-side launcher binding."""
    if isinstance(code, dict) and "runapp" in code:
        import os
        path = code.get("runapp") or ""
        return f"Run App: {os.path.basename(path) or '(none)'}"
    if isinstance(code, dict) and "macro" in code:
        name = (_MACRO_RESOLVER(code["macro"]) if _MACRO_RESOLVER else None) or "Macro"
        pm = code.get("playmode", 1)
        rep = code.get("repeat", 0)
        mode = {1: "hold", 2: f"x{rep}", 4: "toggle"}.get(pm, "?")
        return f"Macro: {name} ({mode})"
    t, p1, p2 = (tuple(code) + (0, 0, 0))[:3]
    # exact named match first (covers mouse, dpi, media, office, window-mgmt, etc.)
    named = _NAMED_BY_CODE.get((t, p1, p2))
    if named:
        return A.ACTION_LABELS.get(named, named)
    if t == 0x70:  # keyboard combo or modifier-only
        mod = _mod_str(p1)
        if p2 == 0:
            return mod if mod else "(none)"
        key = _HID_NAME.get(p2, f"0x{p2:02X}").upper()
        return f"{mod}+{key}" if mod else f"Key: {key}"
    if t == 0x30:  # fire
        return f"Fire ({p1}ms x{p2 or '∞'})"
    if t == 0x50:  # dpi lock
        return f"DPI Lock {100 + p1 * 100}"
    if t == 0x90:  # macro
        playmode = (p1 >> 4) & 0x0F
        slot = p1 & 0x0F
        mode = {1: "hold", 2: f"x{p2}", 4: "toggle"}.get(playmode, "?")
        return f"Macro #{slot} ({mode})"
    if t == 0xFF:
        return "(unset)"
    return f"{t:02X} {p1:02X} {p2:02X}"


# ---- category tree (for the picker UI) -------------------------------------
# Each category yields either a flat list of (label, code) or a custom editor.
ACTION_TREE = {
    "Mouse": [
        ("Left Button", A.BTN["left"]), ("Right Button", A.BTN["right"]),
        ("Middle Button", A.BTN["middle"]), ("Forward", A.BTN["forward"]),
        ("Backward", A.BTN["back"]),
    ],
    "DPI": [
        ("DPI +", A.BTN["dpi_up"]), ("DPI -", A.BTN["dpi_down"]),
        ("DPI Loop", A.BTN["dpi_cycle"]),
    ],
    "Multimedia": [
        ("Media Select", A.BTN["media_select"]), ("Prev Track", A.BTN["prev_track"]),
        ("Next Track", A.BTN["next_track"]), ("Stop", A.BTN["stop"]),
        ("Play/Pause", A.BTN["play_pause"]), ("Mute", A.BTN["mute"]),
        ("Volume +", A.BTN["vol_up"]), ("Volume -", A.BTN["vol_down"]),
        ("Mail", A.BTN["email"]), ("Calculator", A.BTN["calculator"]),
    ],
    "Word Office": [
        ("Copy", A.BTN["copy"]), ("Paste", A.BTN["paste"]), ("Cut", A.BTN["cut"]),
        ("Select All", A.BTN["select_all"]), ("New", A.BTN["new"]),
        ("Save", A.BTN["save"]), ("Print", A.BTN["print"]), ("Open", A.BTN["open"]),
        ("Undo", A.BTN["undo"]),
    ],
    "Window Management": [
        ("My Computer", A.BTN["my_computer"]), ("Close Window", A.BTN["close_window"]),
        ("Display Desktop", A.BTN["display_desktop"]), ("Run", A.BTN["run"]),
        ("Minimize", A.BTN["minimize"]), ("Maximize", A.BTN["maximize"]),
    ],
    "DPI Lock": [
        (f"{100 + i * 100} DPI", A.dpi_lock(i)) for i in range(1, 12)
    ],
    "Quick": [
        ("Three Click", A.BTN["triple"]), ("Fire Key", A.BTN["fire"]),
        ("Switch Effect (lighting)", A.BTN["light_toggle"]),
        ("Disable", A.BTN["disable"]),
    ],
}
# Categories needing a custom editor pane (not just a list):
CUSTOM_CATEGORIES = ["Key Combination", "Fire Key", "Macro", "Run App"]
CATEGORY_ORDER = (["Mouse", "DPI", "Quick", "Key Combination", "Fire Key",
                   "Macro", "Run App", "Multimedia", "Word Office",
                   "Window Management", "DPI Lock"])


class _ComboEditor(QWidget):
    """Editor for a custom keyboard combination (mods + a key)."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._listening = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        lay.addWidget(QLabel("Modifiers"))
        mods = QHBoxLayout()
        self.ctrl = QCheckBox("Ctrl"); self.shift = QCheckBox("Shift")
        self.alt = QCheckBox("Alt"); self.win = QCheckBox("Win")
        for c in (self.ctrl, self.shift, self.alt, self.win):
            mods.addWidget(c)
            c.stateChanged.connect(lambda *_: self.changed.emit())
        mods.addStretch(1)
        lay.addLayout(mods)
        lay.addWidget(QLabel("Key"))
        key_row = QHBoxLayout()
        self.key = QComboBox()
        self.key.addItem("None", 0)
        for name in A.HID:
            self.key.addItem(name.upper(), A.HID[name])
        self.key.currentIndexChanged.connect(lambda *_: self.changed.emit())
        key_row.addWidget(self.key, 1)

        self.detect_btn = QPushButton("Detect Key")
        self.detect_btn.setCheckable(True)
        self.detect_btn.setToolTip("Click, then press any key on your keyboard to auto-select it")
        self.detect_btn.clicked.connect(self._toggle_detect)
        key_row.addWidget(self.detect_btn)
        lay.addLayout(key_row)
        lay.addStretch(1)

    def _toggle_detect(self):
        if self.detect_btn.isChecked():
            self._start_listening()
        else:
            self._stop_listening()

    def _start_listening(self):
        self._listening = True
        self.detect_btn.setChecked(True)
        self.detect_btn.setText("Press any key…")
        self.detect_btn.setStyleSheet(f"background: {theme.ACCENT}; color: #1a1008; font-weight: bold;")
        win = self.window()
        if win:
            win.installEventFilter(self)
        self.setFocus()

    def _stop_listening(self):
        if not self._listening and not self.detect_btn.isChecked():
            return
        self._listening = False
        self.detect_btn.setChecked(False)
        self.detect_btn.setText("Detect Key")
        self.detect_btn.setStyleSheet("")
        win = self.window()
        if win:
            try:
                win.removeEventFilter(self)
            except Exception:
                pass

    def hideEvent(self, e):
        self._stop_listening()
        super().hideEvent(e)

    def eventFilter(self, watched, event):
        if self._listening:
            if event.type() == QEvent.KeyPress:
                self._handle_key_press(event)
                return True
            elif event.type() == QEvent.MouseButtonPress:
                if watched != self.detect_btn:
                    self._stop_listening()
        return super().eventFilter(watched, event)

    def _handle_key_press(self, event):
        k = event.key()
        # Modifier pressed alone: select that modifier alone and set Key to None
        if k in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            self.ctrl.setChecked(k == Qt.Key_Control)
            self.shift.setChecked(k == Qt.Key_Shift)
            self.alt.setChecked(k == Qt.Key_Alt)
            self.win.setChecked(k == Qt.Key_Meta)
            self.key.setCurrentIndex(0)  # None
            self._stop_listening()
            self.changed.emit()
            return

        # Regular key pressed: capture modifiers held down at that instant
        mods = event.modifiers()
        self.ctrl.setChecked(bool(mods & Qt.ControlModifier))
        self.shift.setChecked(bool(mods & Qt.ShiftModifier))
        self.alt.setChecked(bool(mods & Qt.AltModifier))
        self.win.setChecked(bool(mods & Qt.MetaModifier))

        # Look up HID usage by Qt Key or Windows Virtual Key
        usage = _QT_TO_HID.get(k)
        if usage is None and hasattr(event, "nativeVirtualKey"):
            vk = event.nativeVirtualKey()
            usage = VK_TO_HID.get(vk)

        if usage is not None:
            idx = self.key.findData(usage)
            if idx >= 0:
                self.key.setCurrentIndex(idx)

        self._stop_listening()
        self.changed.emit()

    def set_current(self, code):
        """Pre-populate modifiers and key from an existing action."""
        if not code or isinstance(code, dict):
            return
        t, p1, p2 = (tuple(code) + (0, 0, 0))[:3]
        if t == 0x60 and p1 == 0 and p2 == 0:  # Disable
            self.ctrl.setChecked(False)
            self.shift.setChecked(False)
            self.alt.setChecked(False)
            self.win.setChecked(False)
            self.key.setCurrentIndex(0)  # None
            return
        if t != 0x70:
            return
        self.ctrl.setChecked(bool(p1 & A.MOD_CTRL))
        self.shift.setChecked(bool(p1 & A.MOD_SHIFT))
        self.alt.setChecked(bool(p1 & A.MOD_ALT))
        self.win.setChecked(bool(p1 & A.MOD_WIN))
        idx = self.key.findData(p2)
        if idx >= 0:
            self.key.setCurrentIndex(idx)
        elif p2 == 0:
            self.key.setCurrentIndex(0)

    def code(self):
        mask = 0
        if self.ctrl.isChecked():  mask |= A.MOD_CTRL
        if self.shift.isChecked(): mask |= A.MOD_SHIFT
        if self.alt.isChecked():   mask |= A.MOD_ALT
        if self.win.isChecked():   mask |= A.MOD_WIN
        k = self.key.currentData() or 0
        if mask == 0 and k == 0:
            return A.BTN["disable"]
        return A.kb(k, mask)




class _FireEditor(QWidget):
    """Editor for a fire/rapid-fire action (interval + count)."""
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        lay.addWidget(QLabel("Repeat interval (ms)"))
        self.interval = QSpinBox(); self.interval.setRange(1, 255); self.interval.setValue(50)
        lay.addWidget(self.interval)
        lay.addWidget(QLabel("Click count (0 = fire while held)"))
        self.count = QSpinBox(); self.count.setRange(0, 255); self.count.setValue(0)
        lay.addWidget(self.count)
        lay.addStretch(1)

    def code(self):
        return A.fire(self.interval.value(), self.count.value())


class _MacroEditor(QWidget):
    """Bind a button to a macro from the library (by name) + play mode."""
    def __init__(self, macros=None):
        super().__init__()
        self._macros = macros or []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        lay.addWidget(QLabel("Macro"))
        self.macro = QComboBox()
        if self._macros:
            for m in self._macros:
                self.macro.addItem(m["name"], m["id"])
        else:
            self.macro.addItem("(no macros — create one in the Macro tab)", None)
            self.macro.setEnabled(False)
        lay.addWidget(self.macro)
        lay.addWidget(QLabel("Play mode"))
        self.mode = QComboBox()
        self.mode.addItem("Repeat while held", 1)
        self.mode.addItem("Play N times", 2)
        self.mode.addItem("Toggle on/off", 4)   # playmode 4 = toggle (CONFIRMED pcap; not 3)
        lay.addWidget(self.mode)
        self.count_label = QLabel("Times (N)")
        self.count = QSpinBox(); self.count.setRange(1, 255); self.count.setValue(1)
        lay.addWidget(self.count_label)
        lay.addWidget(self.count)
        self.mode.currentIndexChanged.connect(self._sync)
        lay.addStretch(1)
        self._sync()

    def _sync(self):
        is_n = self.mode.currentData() == 2
        self.count_label.setVisible(is_n)
        self.count.setVisible(is_n)

    def set_current(self, binding):
        if not isinstance(binding, dict):
            return
        i = self.macro.findData(binding.get("macro"))
        if i >= 0:
            self.macro.setCurrentIndex(i)
        mi = self.mode.findData(binding.get("playmode", 1))
        if mi >= 0:
            self.mode.setCurrentIndex(mi)
        self.count.setValue(binding.get("repeat", 1) or 1)
        self._sync()

    def code(self):
        mid = self.macro.currentData()
        if mid is None:
            return None
        pm = self.mode.currentData()
        rep = self.count.value() if pm == 2 else 0
        return {"macro": mid, "playmode": pm, "repeat": rep}


class _RunAppEditor(QWidget):
    """Pick an executable to launch when this button is pressed (host-side).

    The device gets the (0x60,0x05,0x00) placeholder; the host watches report-04
    byte[7] and launches this exe (see app.autoswitch / MainWindow._on_runapp).
    """
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        lay.addWidget(QLabel("Application to launch"))
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("C:\\Path\\To\\App.exe")
        row.addWidget(self.path, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        lay.addLayout(row)
        hint = QLabel("Launched by the app while it runs (the mouse button itself "
                      "does nothing on the device).")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)

    def _browse(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose application", "",
            "Programs (*.exe *.lnk *.bat *.cmd);;All files (*)")
        if path:
            self.path.setText(path)

    def set_current(self, binding):
        if isinstance(binding, dict):
            self.path.setText(binding.get("runapp") or "")

    def code(self):
        p = self.path.text().strip()
        return {"runapp": p} if p else None


class ActionPicker(QDialog):
    def __init__(self, current_code=None, parent=None, phys=None, macros=None):
        super().__init__(parent)
        self.setWindowTitle("Assign action")
        self.setModal(True)
        self.setFixedSize(560, 420)
        self._result = None
        self._phys = phys   # 1-based physical button being edited (for "Default")
        self._macros = macros or []
        self.setStyleSheet(f"""
            QDialog {{ background: {theme.BG}; }}
            QLabel {{ color: {theme.TEXT_DIM}; }}
            QListWidget {{
                background: {theme.SURFACE}; border: 1px solid {theme.BORDER};
                border-radius: 8px; outline: 0; padding: 4px;
            }}
            QListWidget::item {{ padding: 9px 12px; border-radius: 6px; color: {theme.TEXT_DIM}; }}
            QListWidget::item:hover {{ background: {theme.SURFACE_2}; color: {theme.TEXT}; }}
            QListWidget::item:selected {{ background: {theme.SURFACE_2}; color: {theme.TEXT};
                border-left: 2px solid {theme.ACCENT}; }}
            QComboBox, QSpinBox, QLineEdit {{
                background: {theme.SURFACE_2}; border: 1px solid {theme.BORDER};
                border-radius: 6px; padding: 6px 10px; color: {theme.TEXT};
            }}
            QComboBox QAbstractItemView {{ background: {theme.SURFACE_2};
                border: 1px solid {theme.BORDER}; selection-background-color: {theme.ACCENT};
                selection-color: #1a1008; outline: 0; }}
            QCheckBox {{ color: {theme.TEXT_DIM}; spacing: 7px; }}
            QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px;
                border: 1px solid {theme.BORDER}; background: {theme.SURFACE_2}; }}
            QCheckBox::indicator:checked {{ background: {theme.ACCENT}; border-color: {theme.ACCENT}; }}
            QPushButton {{ background: {theme.SURFACE_2}; border: 1px solid {theme.BORDER};
                border-radius: 6px; padding: 7px 16px; color: {theme.TEXT}; }}
            QPushButton:hover {{ border-color: {theme.TEXT_DIM}; }}
            QPushButton#ok {{ background: {theme.ACCENT}; border: 1px solid {theme.ACCENT};
                color: #1a1008; font-weight: 600; }}
            QPushButton#ok:hover {{ background: #ff7d4d; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(12)

        # left: category list
        self.cats = QListWidget()
        self.cats.setFixedWidth(180)
        for name in CATEGORY_ORDER:
            QListWidgetItem(name, self.cats)
        self.cats.currentRowChanged.connect(self._on_cat)
        body.addWidget(self.cats)

        # right: stacked panes (a list pane reused for list categories + editors)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)

        # pane 0: a generic list for "list" categories
        self.list_pane = QListWidget()
        self.list_pane.itemDoubleClicked.connect(lambda *_: self._accept_from_list())
        self.stack.addWidget(self.list_pane)        # index 0

        # editor panes
        self.combo_editor = _ComboEditor(); self.stack.addWidget(self.combo_editor)   # 1
        self.fire_editor = _FireEditor();   self.stack.addWidget(self.fire_editor)     # 2
        self.macro_editor = _MacroEditor(self._macros); self.stack.addWidget(self.macro_editor)    # 3
        self.runapp_editor = _RunAppEditor(); self.stack.addWidget(self.runapp_editor)              # 4

        root.addLayout(body, 1)

        # footer
        footer = QHBoxLayout()
        self.preview = QLabel(describe_action(current_code or A.BTN["unset"]))
        self.preview.setStyleSheet(f"color: {theme.ACCENT}; font-family: {theme.FONT_MONO};")
        footer.addWidget(self.preview)
        footer.addStretch(1)
        # "Default" resets to this physical button's factory action (if known)
        if self._phys is not None:
            default_btn = QPushButton("Default")
            default_btn.setToolTip("Reset this button to its factory default")
            default_btn.clicked.connect(self._accept_default)
            footer.addWidget(default_btn)
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        self.ok_btn = QPushButton("OK"); self.ok_btn.setObjectName("ok"); self.ok_btn.clicked.connect(self._accept)
        footer.addWidget(cancel); footer.addWidget(self.ok_btn)
        root.addLayout(footer)

        # Wire live preview updates
        self.list_pane.currentItemChanged.connect(lambda *_: self._update_preview())
        self.combo_editor.changed.connect(self._update_preview)
        self.fire_editor.interval.valueChanged.connect(lambda *_: self._update_preview())
        self.fire_editor.count.valueChanged.connect(lambda *_: self._update_preview())
        self.macro_editor.macro.currentIndexChanged.connect(lambda *_: self._update_preview())
        self.macro_editor.mode.currentIndexChanged.connect(lambda *_: self._update_preview())
        self.macro_editor.count.valueChanged.connect(lambda *_: self._update_preview())
        self.runapp_editor.path.textChanged.connect(lambda *_: self._update_preview())

        # Select initial category and pre-populate if needed
        matched = False
        if isinstance(current_code, dict) and "macro" in current_code:
            self.cats.setCurrentRow(CATEGORY_ORDER.index("Macro"))
            self.macro_editor.set_current(current_code)
            matched = True
        elif isinstance(current_code, dict) and "runapp" in current_code:
            self.cats.setCurrentRow(CATEGORY_ORDER.index("Run App"))
            self.runapp_editor.set_current(current_code)
            matched = True
        elif isinstance(current_code, (tuple, list)) and len(current_code) >= 3 and current_code[0] == 0x70 and tuple(current_code[:3]) not in _NAMED_BY_CODE:
            self.cats.setCurrentRow(CATEGORY_ORDER.index("Key Combination"))
            self.combo_editor.set_current(current_code)
            matched = True
        elif isinstance(current_code, (tuple, list)) and len(current_code) >= 3 and current_code[0] == 0x30 and tuple(current_code[:3]) not in _NAMED_BY_CODE:
            self.cats.setCurrentRow(CATEGORY_ORDER.index("Fire Key"))
            self.fire_editor.interval.setValue(current_code[1])
            self.fire_editor.count.setValue(current_code[2])
            matched = True
        elif isinstance(current_code, (tuple, list)) and len(current_code) >= 3:
            target = tuple(current_code[:3])
            for cat_name, items in ACTION_TREE.items():
                for idx, (label, code) in enumerate(items):
                    if tuple(code) == target:
                        self.cats.setCurrentRow(CATEGORY_ORDER.index(cat_name))
                        self.list_pane.setCurrentRow(idx)
                        matched = True
                        break
                if matched:
                    break
        if not matched:
            self.cats.setCurrentRow(0)
        self._update_preview()

    def _accept_default(self):
        """Resolve this physical button's factory-default code and accept it."""
        if self._phys is None:
            return
        defaults = A.default_button_codes()  # 0-based physical index
        idx = self._phys - 1
        if 0 <= idx < len(defaults):
            self._result = tuple(defaults[idx])
            self.accept()

    def _update_preview(self):
        code = self._current_code()
        if code is not None:
            self.preview.setText(describe_action(code))
            self.ok_btn.setEnabled(True)
        else:
            self.preview.setText("(none)")
            self.ok_btn.setEnabled(False)

    def _on_cat(self, row):
        name = CATEGORY_ORDER[row]
        if name in CUSTOM_CATEGORIES:
            idx = {"Key Combination": 1, "Fire Key": 2, "Macro": 3, "Run App": 4}[name]
            self.stack.setCurrentIndex(idx)
        else:
            self.list_pane.clear()
            for label, code in ACTION_TREE[name]:
                it = QListWidgetItem(label)
                it.setData(Qt.UserRole, tuple(code))
                self.list_pane.addItem(it)
            self.list_pane.setCurrentRow(0)
            self.stack.setCurrentIndex(0)
        self._update_preview()

    def _current_code(self):
        idx = self.stack.currentIndex()
        if idx == 0:
            it = self.list_pane.currentItem()
            return it.data(Qt.UserRole) if it else None
        if idx == 1:
            return self.combo_editor.code()
        if idx == 2:
            return self.fire_editor.code()
        if idx == 3:
            return self.macro_editor.code()
        if idx == 4:
            return self.runapp_editor.code()
        return None

    def _accept_from_list(self):
        self._accept()

    def _accept(self):
        code = self._current_code()
        if code is not None:
            self._result = code if isinstance(code, dict) else tuple(code)
            self.accept()

    def result_code(self):
        return self._result


def pick_action(current_code=None, parent=None, phys=None, macros=None):
    dlg = ActionPicker(current_code, parent, phys=phys, macros=macros)
    if dlg.exec() == QDialog.Accepted:
        return dlg.result_code()
    return None
