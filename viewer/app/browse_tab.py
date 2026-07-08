import os

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
from app.elided_tooltip_delegate import ElidedTooltipDelegate
from app.replay_action_button import ReplayActionButton
from app.results_source import load_results_lib
from app.tooltip_header import install_header_tooltips
from app.trainer_names import TrainerNameResolver

COLUMNS = [
    "Trainer 1", "Trainer 2", "Seed", "Result", "Rnds",
    "T1 Rtg", "T2 Rtg", "Diff", "Abs diff",
]

# Explicit widths for every column -- the two trainer-name columns stay
# wider than the rest, everything else holds at most a handful of digits/
# short words, so giving each an explicit narrow width (rather than the
# ~100px Qt default) is what keeps the whole table -- all 9 columns, no
# optional/hidden ones anymore -- fitting the window without horizontal
# scrolling, matching the same narrow-numeric-column look the trainer
# page's highlights table uses.
COLUMN_WIDTHS = {0: 190, 1: 190, 2: 70, 3: 70, 4: 55, 5: 65, 6: 65, 7: 55, 8: 65}

# Explanations for the abbreviated headers -- see TooltipHeaderView, which
# is what actually makes hovering a header show these (QHeaderView doesn't
# do this on its own from a model's Qt.ToolTipRole).
COLUMN_TOOLTIPS = {
    4: "Number of rounds the battle lasted",
    5: "Trainer 1's rating in this format",
    6: "Trainer 2's rating in this format",
    7: "Signed rating difference, winner minus loser (negative = upset)",
    8: "Absolute rating difference between the two trainers",
}

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

    def set_rows(self, rows, lib, ratings=None):
        self.beginResetModel()
        self._rows = rows
        ratings = ratings or {}
        self._cache = [self._build_cache(row, lib, ratings) for row in rows]
        self._visible = list(range(len(rows)))
        # Reapply whatever sort was already active instead of dropping back
        # to load order -- previously this unconditionally cleared
        # _sort_column, so switching formats while sorted (any direction)
        # looked like it silently reset to ascending/load-order on refresh.
        if self._sort_column >= 0:
            self._resort()
        self.endResetModel()

    def _build_cache(self, row, lib, ratings):
        t1_raw = row.get("trainer1", "") or ""
        t2_raw = row.get("trainer2", "") or ""
        t1_disp = self._names.display_name(t1_raw)
        t2_disp = self._names.display_name(t2_raw)
        result = row.get("result")
        if result == lib.WIN:
            result_label = "T1 won"
        elif result == lib.LOSS:
            result_label = "T2 won"
        elif result == lib.DRAW:
            result_label = "Draw"
        else:
            result_label = str(result) if result is not None else ""

        t1_rating_row = ratings.get(t1_raw)
        t2_rating_row = ratings.get(t2_raw)
        t1_rating = t1_rating_row["rating"] if t1_rating_row else None
        t2_rating = t2_rating_row["rating"] if t2_rating_row else None

        # Signed diff is winner_rating - loser_rating (negative = upset), so
        # it needs a winner -- draws and missing ratings leave it blank
        # rather than silently falling back to a t1-vs-t2 reading, which
        # would mean something different (who's rated higher, not how
        # surprising the result was).
        if t1_rating is None or t2_rating is None or result not in (lib.WIN, lib.LOSS):
            rating_diff = None
        elif result == lib.WIN:
            rating_diff = t1_rating - t2_rating
        else:
            rating_diff = t2_rating - t1_rating

        abs_rating_diff = None if (t1_rating is None or t2_rating is None) else abs(t1_rating - t2_rating)

        return {
            "t1_disp": t1_disp,
            "t2_disp": t2_disp,
            "t1_search": f"{t1_raw} {t1_disp}".lower(),
            "t2_search": f"{t2_raw} {t2_disp}".lower(),
            "seed": row.get("seed") or 0,
            "seed_text": str(row.get("seed", "")),
            "rounds": row.get("rounds") or 0,
            # +1 for display: the engine's stored round count is 0-indexed
            # (see replay_runner.describe_result); sort key above stays raw
            # since a uniform +1 shift doesn't change ordering.
            "rounds_text": str(row.get("rounds") + 1) if row.get("rounds") is not None else "",
            "result": result,
            "result_label": result_label,
            "t1_rating": t1_rating,
            "t2_rating": t2_rating,
            "t1_rating_text": f"{t1_rating:.0f}" if t1_rating is not None else "",
            "t2_rating_text": f"{t2_rating:.0f}" if t2_rating is not None else "",
            "rating_diff": rating_diff,
            "rating_diff_text": f"{rating_diff:+.0f}" if rating_diff is not None else "",
            "abs_rating_diff": abs_rating_diff,
            "abs_rating_diff_text": f"{abs_rating_diff:.0f}" if abs_rating_diff is not None else "",
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

    # Columns 5-8 (ratings/diffs) can be None (missing rating / a draw with
    # no winner to sign the diff against) and need None to land at the same
    # end of the list -- always last -- no matter which way the column is
    # currently sorted. A plain (is_none, value) key handles this for
    # ascending, but list.sort(reverse=True) reverses the *whole* key
    # tuple, so under descending order the is_none flag flips too and Nones
    # jump to the front instead. These take the sort direction as an
    # explicit argument and negate the value themselves instead, keeping
    # the is_none rank constant regardless of direction.
    _NONE_LAST_SORT_KEYS = {
        5: lambda cache: cache["t1_rating"],
        6: lambda cache: cache["t2_rating"],
        7: lambda cache: cache["rating_diff"],
        8: lambda cache: cache["abs_rating_diff"],
    }

    @staticmethod
    def _none_last_key(value, reverse):
        if value is None:
            return (1, 0)
        return (0, -value if reverse else value)

    def _resort(self):
        cache = self._cache
        reverse = self._sort_order == Qt.DescendingOrder
        none_last_fn = self._NONE_LAST_SORT_KEYS.get(self._sort_column)
        if none_last_fn is not None:
            self._visible.sort(key=lambda i: self._none_last_key(none_last_fn(cache[i]), reverse))
        else:
            key_fn = self._SORT_KEYS[self._sort_column]
            self._visible.sort(key=lambda i: key_fn(cache[i]), reverse=reverse)

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
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return COLUMNS[section]
            if role == Qt.ToolTipRole:
                return COLUMN_TOOLTIPS.get(section)
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
                cache["t1_rating_text"],
                cache["t2_rating_text"],
                cache["rating_diff_text"],
                cache["abs_rating_diff_text"],
            )[col]
        return None


class BrowseTab(QWidget):
    """Browses results/*.jsonl via analysis/results_lib.py and hands a
    selected match off to the Generate/Watch tabs -- same handoff pattern
    Bracket/Trainers use, never launching Game.exe itself."""

    match_selected = Signal(dict)
    watch_requested = Signal(str, dict)

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
        self.action_button = ReplayActionButton(self.config.replay_dir)
        filter_row.addWidget(self.search_t1_box, 2)
        filter_row.addWidget(self.search_t2_box, 2)
        filter_row.addWidget(self.result_filter_combo, 1)
        filter_row.addWidget(self.count_label)
        filter_row.addWidget(self.action_button)
        layout.addLayout(filter_row)

        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        for col_index, width in COLUMN_WIDTHS.items():
            self.table.setColumnWidth(col_index, width)
        install_header_tooltips(self.table)
        # Full trainer name as a tooltip, but only once the column's too
        # narrow to show it in full -- not on every cell regardless.
        name_tooltip_delegate = ElidedTooltipDelegate(self.table)
        self.table.setItemDelegateForColumn(0, name_tooltip_delegate)
        self.table.setItemDelegateForColumn(1, name_tooltip_delegate)
        layout.addWidget(self.table)

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
        self.action_button.generate_requested.connect(self.match_selected.emit)
        self.action_button.watch_requested.connect(self.watch_requested.emit)
        self.table.doubleClicked.connect(lambda _: self.action_button.click())
        self.table.selectionModel().selectionChanged.connect(self._refresh_action_button)

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
            self._refresh_action_button()
            return

        try:
            lib = self._lib()
            rows = lib.load_results(fmt, results_dir=self.config.results_dir)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            QMessageBox.warning(self, "Couldn't load results", str(exc))
            return

        # Missing ratings shouldn't block browsing raw results -- just leave
        # the rating/diff columns blank rather than erroring the whole tab.
        try:
            ratings = lib.load_ratings(fmt)
        except (OSError, FileNotFoundError):
            ratings = {}

        self._model.set_rows(rows, lib, ratings)
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
        self._refresh_action_button()

    def _selected_row(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        return self._model.row_data(selected_rows[0].row())

    @staticmethod
    def _match_slug(fmt, t1, t2, seed):
        """Deterministic filename-safe id for exactly this historical
        (format, trainer1, trainer2, seed) battle -- same idea as the
        Trainers tab's per-highlight slug, just without a highlight type
        since Browse only ever has one match selected at a time."""
        safe_t1 = "".join(ch if ch.isalnum() else "-" for ch in t1)
        safe_t2 = "".join(ch if ch.isalnum() else "-" for ch in t2)
        return f"browse_{fmt}_{safe_t1}_vs_{safe_t2}_{seed}"

    def _refresh_action_button(self):
        row = self._selected_row()
        if row is None or not self._current_format:
            self.action_button.refresh(None, None)
            return
        slug = self._match_slug(self._current_format, row.get("trainer1", ""), row.get("trainer2", ""), row.get("seed"))
        payload = dict(row)
        payload["format"] = self._current_format
        payload["output_name"] = slug
        self.action_button.refresh(slug, payload)

    def set_actions_blocked(self, blocked):
        self.action_button.set_vendor_blocked(blocked)

    def handle_generation_finished(self, dat_path, _result):
        name = os.path.splitext(os.path.basename(dat_path))[0]
        if self.action_button.matches_slug(name):
            self.action_button.recheck()

    def handle_replay_finished(self, dat_path, _result):
        name = os.path.splitext(os.path.basename(dat_path))[0]
        if self.action_button.matches_slug(name):
            self.action_button.recheck()
