"""
app.panels.profiles_panel -- the Profiles management tab.

A searchable, sortable, drag-to-reorder list of profiles. The list ORDER is the
auto-switch match priority (first matching profile wins), so reordering here
directly controls which profile takes precedence. Double-click a profile to make
it active. CRUD lives in the rail's profile menu; this tab is for organising.

Signals:
  profile_selected(str)  -- activate this profile id (double-click)
  order_changed(object)  -- new list of profile ids after a manual drag
  sort_changed(str)      -- a predefined sort was chosen (az|za|latest|oldest|custom)
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QListWidget, QListWidgetItem, QAbstractItemView, QPushButton,
)

SORTS = [
    ("Custom order", "custom"),
    ("Alphabetical (A to Z)", "az"),
    ("Alphabetical (Z to A)", "za"),
    ("Latest", "latest"),
    ("Oldest", "oldest"),
]


class ProfilesPanel(QWidget):
    profile_selected = Signal(str)
    order_changed = Signal(object)
    sort_changed = Signal(str)
    new_requested = Signal()
    duplicate_requested = Signal()
    rename_requested = Signal()
    delete_requested = Signal()
    import_requested = Signal()

    def __init__(self):
        super().__init__()
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(12)

        title = QLabel("Profiles")
        title.setProperty("panelTitle", "true")
        lay.addWidget(title)
        sub = QLabel("Drag to reorder — order sets auto-switch priority (first "
                     "matching profile wins). Double-click to activate.")
        sub.setProperty("panelSubtitle", "true")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("Search profiles…")
        self.search.textChanged.connect(self._apply_filter)
        lay.addWidget(self.search)

        srow = QVBoxLayout()
        srow.setSpacing(4)
        cap = QLabel("SORT BY")
        cap.setProperty("unit", "true")
        srow.addWidget(cap)
        self.sort = QComboBox()
        for label, key in SORTS:
            self.sort.addItem(label, key)
        self.sort.currentIndexChanged.connect(self._on_sort)
        srow.addWidget(self.sort)
        lay.addLayout(srow)

        self.list = QListWidget()
        self.list.setObjectName("profileList")
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemDoubleClicked.connect(self._on_activate)
        self.list.model().rowsMoved.connect(self._on_rows_moved)
        lay.addWidget(self.list, 1)

        # management actions (moved here from the rail menu)
        btns = QHBoxLayout()
        for label, sig in (("New", self.new_requested),
                           ("Duplicate", self.duplicate_requested),
                           ("Rename", self.rename_requested),
                           ("Delete", self.delete_requested),
                           ("Import .psf…", self.import_requested)):
            b = QPushButton(label)
            b.clicked.connect(sig)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

    # -- external -------------------------------------------------------------
    def set_profiles(self, profiles, active_id, sort_key="custom"):
        self._loading = True
        self.list.clear()
        for p in profiles:
            it = QListWidgetItem(p["name"])
            it.setData(Qt.UserRole, p["id"])
            if p["id"] == active_id:
                f = it.font()
                f.setWeight(QFont.DemiBold)
                it.setFont(f)
                it.setSelected(True)
            self.list.addItem(it)
        # reflect the persisted sort choice
        si = self.sort.findData(sort_key)
        self.sort.blockSignals(True)
        self.sort.setCurrentIndex(si if si >= 0 else 0)
        self.sort.blockSignals(False)
        self._loading = False
        self._apply_filter(self.search.text())

    def selected_id(self):
        """The id of the highlighted list row (the management target), or None."""
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it is not None else None

    # -- internals ------------------------------------------------------------
    def _ids_in_order(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def _apply_filter(self, text):
        t = (text or "").strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def _on_activate(self, item):
        pid = item.data(Qt.UserRole)
        if pid:
            self.profile_selected.emit(pid)

    def _on_rows_moved(self, *_):
        if self._loading:
            return
        # a manual drag implies a custom order
        self.sort.blockSignals(True)
        self.sort.setCurrentIndex(0)
        self.sort.blockSignals(False)
        self.order_changed.emit(self._ids_in_order())

    def _on_sort(self, _idx):
        if self._loading:
            return
        key = self.sort.currentData()
        if key and key != "custom":
            self.sort_changed.emit(key)
