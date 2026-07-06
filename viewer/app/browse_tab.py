from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app import format_selector, ui_settings
from app.results_source import load_results_lib
from app.trainer_names import TrainerNameResolver

COLUMNS = ["Trainer 1", "Trainer 2", "Seed", "Result", "Rounds"]

# Result filter combo entries: (label, results_lib attr name or None for "any").
RESULT_FILTERS = [
    ("All results", None),
    ("Trainer 1 won", "WIN"),
    ("Trainer 2 won", "LOSS"),
    ("Draw", "DRAW"),
]


class ResultsTableModel(QAbstractTableModel):
    """Backs the Browse tab's table with plain Python lists instead of
    QTableWidgetItems.

    Results files run into the hundreds of thousands of rows (a full
    singles format is ~150k). QTableWidget requires one QTableWidgetItem
    per cell up front, and both its built-in sort and a per-row
    setRowHidden() filter pass are driven by repeated Python-level
    callbacks across the Qt/C++ boundary -- fine for hundreds of rows,
    unusably slow at this scale (each header-click sort was doing on the
    order of n*log(n) individual Python __lt__ calls). A QAbstractTableModel
    lets filtering and sorting be plain bulk Python list operations
    (list comprehension / list.sort with a precomputed key), which is
    orders of magnitude faster, and cell text is computed lazily in
    data() only for rows actually painted rather than materialized for
    the whole table up front.
    """

    def __init__(self, names_resolver, parent=None):
        super().__init__(parent)
        self._names = names_resolver
        self._rows = []  # raw dicts for the current format, load order
        self._cache = []  # precomputed per-row display/search fields, same order as _rows
        self._visible = []  # indices into _rows/_cache, current filter+sort order
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder

    def set_rows(self, rows, lib):
        self.beginResetModel()
        self._rows = rows
        self._cache = [self._build_cache(row, lib) for row in rows]
        self._visible = list(range(len(rows)))
        self._sort_column = -1
        self.endResetModel()

    def _build_cache(self, row, lib):
        t1_raw = row.get("trainer1", "") or ""
        t2_raw = row.get("trainer2", "") or ""
        t1_disp = self._names.display_name(t1_raw)
        t2_disp = self._names.display_name(t2_raw)
        result = row.get("result")
        if result == lib.WIN:
            result_label = "Trainer 1 won"
        elif result == lib.LOSS:
            result_label = "Trainer 2 won"
        elif result == lib.DRAW:
            result_label = "Draw"
        else:
            result_label = str(result) if result is not None else ""
        return {
            "t1_disp": t1_disp,
            "t2_disp": t2_disp,
            "t1_search": f"{t1_raw} {t1_disp}".lower(),
            "t2_search": f"{t2_raw} {t2_disp}".lower(),
            "t1_raw": t1_raw,
            "t2_raw": t2_raw,
            "seed": row.get("seed") or 0,
            "seed_text": str(row.get("seed", "")),
            "rounds": row.get("rounds") or 0,
            # +1 for display: the engine's stored round count is 0-indexed
            # (see replay_runner.describe_result); sort key above stays raw
            # since a uniform +1 shift doesn't change ordering.
            "rounds_text": str(row.get("rounds") + 1) if row.get("rounds") is not None else "",
            "result": result,
            "result_label": result_label,
        }

    def apply_filter(self, t1_query, t2_query, wanted_result):
        self.beginResetModel()
        indices = range(len(self._rows))
        if t1_query:
            indices = [
                i for i in indices
                if t1_query in self._cache[i]["t1_search"] or t1_query in self._cache[i]["t2_search"]
            ]
        if t2_query:
            indices = [
                i for i in indices
                if t2_query in self._cache[i]["t1_search"] or t2_query in self._cache[i]["t2_search"]
            ]
        if wanted_result is not None:
            indices = [i for i in indices if self._cache[i]["result"] == wanted_result]
        self._visible = list(indices)
        if self._sort_column >= 0:
            self._resort()
        self.endResetModel()

    _SORT_KEYS = {
        0: lambda cache: cache["t1_disp"].lower(),
        1: lambda cache: cache["t2_disp"].lower(),
        2: lambda cache: cache["seed"],
        3: lambda cache: cache["result_label"].lower(),
        4: lambda cache: cache["rounds"],
    }

    def _resort(self):
        key_fn = self._SORT_KEYS[self._sort_column]
        cache = self._cache
        self._visible.sort(key=lambda i: key_fn(cache[i]), reverse=(self._sort_order == Qt.DescendingOrder))

    def sort(self, column, order=Qt.AscendingOrder):
        if column < 0:
            return
        self.beginResetModel()
        self._sort_column = column
        self._sort_order = order
        self._resort()
        self.endResetModel()

    def row_data(self, view_row):
        return self._rows[self._visible[view_row]]

    def total_row_count(self):
        return len(self._rows)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._visible)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        cache = self._cache[self._visible[index.row()]]
        col = index.column()
        if role == Qt.DisplayRole:
            return (
                cache["t1_disp"],
                cache["t2_disp"],
                cache["seed_text"],
                cache["result_label"],
                cache["rounds_text"],
            )[col]
        if role == Qt.ToolTipRole and col in (0, 1):
            return cache["t1_raw"] if col == 0 else cache["t2_raw"]
        return None


class BrowseTab(QWidget):
    """Browses results/*.jsonl via analysis/results_lib.py and hands a
    selected match off to the Generate tab."""

    match_selected = Signal(dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._results_lib = None
        self._current_format = None
        self._names = TrainerNameResolver(config)
        self._model = ResultsTableModel(self._names)

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.battle_type_combo = QComboBox()
        for value, label in format_selector.BATTLE_TYPES:
            self.battle_type_combo.addItem(label, value)
        self.curse_variant_combo = QComboBox()
        for value, label in format_selector.CURSE_VARIANTS:
            self.curse_variant_combo.addItem(label, value)
        self.refresh_button = QPushButton("Refresh")
        top.addWidget(self.battle_type_combo, 1)
        top.addWidget(self.curse_variant_combo, 1)
        top.addWidget(self.refresh_button)
        layout.addLayout(top)

        filter_row = QHBoxLayout()
        self.search_t1_box = QLineEdit()
        self.search_t1_box.setPlaceholderText("Search Trainer 1...")
        self.search_t2_box = QLineEdit()
        self.search_t2_box.setPlaceholderText("Search Trainer 2...")
        self.result_filter_combo = QComboBox()
        for label, _attr in RESULT_FILTERS:
            self.result_filter_combo.addItem(label)
        self.count_label = QLabel()
        filter_row.addWidget(self.search_t1_box, 2)
        filter_row.addWidget(self.search_t2_box, 2)
        filter_row.addWidget(self.result_filter_combo, 1)
        filter_row.addWidget(self.count_label)
        layout.addLayout(filter_row)

        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(1, 220)
        layout.addWidget(self.table)

        self.use_button = QPushButton("Use selected match")
        layout.addWidget(self.use_button)

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(150)
        self._filter_timer.timeout.connect(self._apply_filter)

        self.battle_type_combo.currentIndexChanged.connect(self._reload)
        self.curse_variant_combo.currentIndexChanged.connect(self._reload)
        self.refresh_button.clicked.connect(self.refresh)
        self.search_t1_box.textChanged.connect(lambda _: self._filter_timer.start())
        self.search_t2_box.textChanged.connect(lambda _: self._filter_timer.start())
        self.result_filter_combo.currentIndexChanged.connect(self._apply_filter)
        self.use_button.clicked.connect(self._emit_selected)
        self.table.doubleClicked.connect(lambda _: self._emit_selected())

        settings = QSettings()
        ui_settings.bind_combo(settings, "browse/battle_type", self.battle_type_combo)
        ui_settings.bind_combo(settings, "browse/curse_variant", self.curse_variant_combo)
        ui_settings.bind_combo(settings, "browse/result_filter", self.result_filter_combo)

        self.refresh()

    def _lib(self):
        if self._results_lib is None:
            self._results_lib = load_results_lib(self.config.analysis_dir)
        return self._results_lib

    def _current_fmt(self):
        return format_selector.format_key(
            self.battle_type_combo.currentData(), self.curse_variant_combo.currentData()
        )

    def refresh(self):
        self._reload()

    def _reload(self):
        self._load_format(self._current_fmt())

    def _load_format(self, fmt):
        self._current_format = fmt or None
        if not fmt:
            self._model.set_rows([], None)
            self.count_label.setText("")
            return

        try:
            lib = self._lib()
            rows = lib.load_results(fmt, results_dir=self.config.results_dir)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            QMessageBox.warning(self, "Couldn't load results", str(exc))
            return

        self._model.set_rows(rows, lib)
        self._apply_filter()

    def _apply_filter(self):
        t1_query = self.search_t1_box.text().strip().lower()
        t2_query = self.search_t2_box.text().strip().lower()
        _label, attr = RESULT_FILTERS[self.result_filter_combo.currentIndex()]
        wanted_result = getattr(self._lib(), attr) if (attr and self._current_format) else None

        self._model.apply_filter(t1_query, t2_query, wanted_result)
        shown = self._model.rowCount()
        total = self._model.total_row_count()
        self.count_label.setText(f"{shown} / {total}" if total else "")

    def _emit_selected(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return
        row = self._model.row_data(selected_rows[0].row())
        payload = dict(row)
        payload["format"] = self._current_format
        self.match_selected.emit(payload)
