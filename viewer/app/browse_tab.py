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

from app import format_selector, replay_env, ui_settings
from app.elided_tooltip_delegate import ElidedTooltipDelegate
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
        self._lib = None  # results_lib module for the current format, needed by data()'s lazy result-label formatting
        self._cache = []  # precomputed per-row search/sort fields, same order as _rows -- display *_text formatting is done lazily in data(), see _build_cache
        self._visible = []  # indices into _rows/_cache, current filter+sort order
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder

    def set_rows(self, rows, lib, ratings=None, cache=None):
        """cache lets a caller that already built this exact rows list's
        per-row cache once (see BrowseTab's format-keyed cache -- there are
        only 4 possible battle_type x curse_variant combos, so keeping all
        4 built caches resident is a small, bounded memory cost) skip
        rebuilding it. Returns the cache actually used, so a first-time
        caller can stash what got built here for reuse later."""
        self.beginResetModel()
        self._rows = rows
        self._lib = lib
        if cache is None:
            cache = self.build_row_cache(rows, lib, ratings)
        self._cache = cache
        self._visible = list(range(len(rows)))
        # Reapply whatever sort was already active instead of dropping back
        # to load order -- previously this unconditionally cleared
        # _sort_column, so switching formats while sorted (any direction)
        # looked like it silently reset to ascending/load-order on refresh.
        if self._sort_column >= 0:
            self._resort()
        self.endResetModel()
        return self._cache

    def build_row_cache(self, rows, lib, ratings):
        """The per-row cache list for `rows`, without touching this model's
        own live state -- lets a caller precompute another format's cache
        (e.g. BrowseTab warming the other 3 battle_type x curse_variant
        combos during boot, under the splash screen, rather than paying for
        it as a hitch the first time the user switches there) without
        resetting/flickering whatever's currently on screen."""
        ratings = ratings or {}
        names_map = self._names.names_map()
        return [self._build_cache(row, lib, ratings, names_map) for row in rows]

    def _build_cache(self, row, lib, ratings, names_map):
        """Precomputes only what filtering (apply_filter) and sorting
        (_resort) need over *every* row up front. Formatted display strings
        (seed_text, rounds_text, result_label, the rating/diff *_text
        fields) are deliberately left out and computed lazily in data()
        instead -- a results file runs into the hundreds of thousands of
        rows, but a QTableView only ever calls data() for the couple dozen
        rows actually painted in the viewport, so eagerly formatting all of
        them here on every load (format switch, refresh) was doing orders
        of magnitude more string formatting than the UI could ever show.

        t1_disp/t2_disp *do* still belong here, unlike those -- display,
        search, and sort all need them for every row, not just visible
        ones. names_map is the resolver's already-loaded label -> name dict
        (see TrainerNameResolver.names_map), looked up once per set_rows()
        call rather than going through display_name()'s per-call
        _ensure_loaded() check hundreds of thousands of times."""
        t1_raw = row.get("trainer1", "") or ""
        t2_raw = row.get("trainer2", "") or ""
        t1_disp = names_map.get(t1_raw, t1_raw) if t1_raw else t1_raw
        t2_disp = names_map.get(t2_raw, t2_raw) if t2_raw else t2_raw
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
            # Precomputed once here rather than in the column-0/1/3 sort key
            # lambdas below: _resort() re-runs those lambdas over every
            # visible row on every sort *and* every filter change (since a
            # filter reapplies the active sort), so a .lower() there was
            # redone from scratch each time instead of once per row per load.
            "t1_disp_lower": t1_disp.lower(),
            "t2_disp_lower": t2_disp.lower(),
            "t1_search": f"{t1_raw} {t1_disp}".lower(),
            "t2_search": f"{t2_raw} {t2_disp}".lower(),
            "seed": row.get("seed") or 0,
            "rounds": row.get("rounds") or 0,
            "result": result,
            "result_label_lower": result_label.lower(),
            "t1_rating": t1_rating,
            "t2_rating": t2_rating,
            "rating_diff": rating_diff,
            "abs_rating_diff": abs_rating_diff,
        }

    def _result_label(self, result):
        lib = self._lib
        if result == lib.WIN:
            return "T1 won"
        if result == lib.LOSS:
            return "T2 won"
        if result == lib.DRAW:
            return "Draw"
        return str(result) if result is not None else ""

    def apply_filter(self, t1_query, t2_query, wanted_result):
        self.beginResetModel()
        indices = range(len(self._rows))
        if t1_query or t2_query:
            indices = [i for i in indices if self._pair_matches(self._cache[i], t1_query, t2_query)]
        if wanted_result is not None:
            indices = [i for i in indices if self._cache[i]["result"] == wanted_result]
        self._visible = list(indices)
        if self._sort_column >= 0:
            self._resort()
        self.endResetModel()

    @staticmethod
    def _pair_matches(cache, t1_query, t2_query):
        """Whether some assignment of the two (order-independent) search
        boxes to the row's actual Trainer 1/Trainer 2 slots satisfies both
        -- not just "each query matches somewhere in the row" independently,
        which is what the old per-box OR-across-both-columns check did.
        That distinction only bites when both boxes hold the same (or an
        overlapping) name: independently, "Bob" in box 1 and "Bob" in box 2
        each trivially match any row with a single Bob in it, surfacing
        every match Bob played rather than just Bob-vs-Bob. Requiring one
        straight-or-crossed full assignment fixes that while leaving
        distinct-name, single-box, and blank-box behavior unchanged."""
        straight = (not t1_query or t1_query in cache["t1_search"]) and (
            not t2_query or t2_query in cache["t2_search"]
        )
        crossed = (not t1_query or t1_query in cache["t2_search"]) and (
            not t2_query or t2_query in cache["t1_search"]
        )
        return straight or crossed

    _SORT_KEYS = {
        0: lambda cache: cache["t1_disp_lower"],
        1: lambda cache: cache["t2_disp_lower"],
        2: lambda cache: cache["seed"],
        3: lambda cache: cache["result_label_lower"],
        4: lambda cache: cache["rounds"],
    }

    # Columns 5-8 (ratings/diffs) can be None (missing rating / a draw with
    # no winner to sign the diff against) and need None to land at the same
    # end of the list -- always last -- no matter which way the column is
    # currently sorted. A plain (is_none, value) key handles this for
    # ascending, but list.sort(reverse=True) reverses the *whole* key
    # tuple, so under descending order the is_none flag flips too and Nones
    # jump to the front instead.
    _NONE_LAST_SORT_FIELDS = {
        5: "t1_rating",
        6: "t2_rating",
        7: "rating_diff",
        8: "abs_rating_diff",
    }

    def _resort(self):
        cache = self._cache
        reverse = self._sort_order == Qt.DescendingOrder
        none_last_field = self._NONE_LAST_SORT_FIELDS.get(self._sort_column)
        if none_last_field is not None:
            # A plain ascending sort over (is_none, maybe-negated value)
            # keeps None last regardless of direction without ever needing
            # reverse=True here -- negating inline in one flat local
            # function instead of going through the wrapper-lambda-calling-
            # another-lambda-calling-a-staticmethod chain this used to be.
            # That indirection cost 2 extra function calls per row on every
            # _resort() (which runs on every filter change too, not just a
            # header click) -- measured at ~150-225ms for a full ~150k-row
            # format. Deliberately NOT precomputed in _build_cache instead:
            # that traded a per-sort cost for a per-load cost, but paid for
            # every row of every format regardless of whether it's ever
            # sorted by rating, and got paid up to 4x over now that Browse
            # precomputes every format's cache at boot (see
            # _precompute_other_formats) -- worse net cost than this.
            if reverse:
                def key(i):
                    value = cache[i][none_last_field]
                    return (1, 0) if value is None else (0, -value)
            else:
                def key(i):
                    value = cache[i][none_last_field]
                    return (1, 0) if value is None else (0, value)
            self._visible.sort(key=key)
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
        if role != Qt.DisplayRole:
            return None
        actual = self._visible[index.row()]
        cache = self._cache[actual]
        col = index.column()
        if col == 0:
            return cache["t1_disp"]
        if col == 1:
            return cache["t2_disp"]
        if col == 2:
            return str(self._rows[actual].get("seed", ""))
        if col == 3:
            return self._result_label(cache["result"])
        if col == 4:
            # +1 for display: the engine's stored round count is 0-indexed
            # (see results_lib.display_rounds); the sort key in _resort
            # stays raw since a uniform +1 shift doesn't change ordering.
            rounds = self._lib.display_rounds(self._rows[actual].get("rounds"))
            return str(rounds) if rounds is not None else ""
        if col == 5:
            return self._rating_text(cache["t1_rating"])
        if col == 6:
            return self._rating_text(cache["t2_rating"])
        if col == 7:
            diff = cache["rating_diff"]
            return f"{diff:+.0f}" if diff is not None else ""
        if col == 8:
            return self._rating_text(cache["abs_rating_diff"])
        return None

    @staticmethod
    def _rating_text(value):
        return f"{value:.0f}" if value is not None else ""


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
        self._vendor_blocked = False
        self._current_slug = None
        self._current_payload = None
        self._current_dat_path = None
        self._names = TrainerNameResolver(config)
        self._model = ResultsTableModel(self._names)
        # fmt -> (rows, lib, built per-row cache), so switching back to an
        # already-visited format skips rebuilding ResultsTableModel's cache
        # from scratch. Bounded to however many format_selector combos
        # exist (4 today: battle_type x curse_variant) rather than growing
        # unboundedly, so keeping every entry resident for the tab's
        # lifetime is a small, fixed memory cost -- not the "duplicate
        # everything" RAM tax that sounds expensive at a glance.
        self._format_row_cache = {}

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.battle_type_combo = QComboBox()
        for value, label in format_selector.BATTLE_TYPES:
            self.battle_type_combo.addItem(label, value)
        self.curse_variant_combo = QComboBox()
        for value, label in format_selector.CURSE_VARIANTS:
            self.curse_variant_combo.addItem(label, value)
        top.addWidget(self.battle_type_combo, 1)
        top.addWidget(self.curse_variant_combo, 1)
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
        # Two independent buttons rather than one toggling label -- Generate
        # is always available (so an existing replay can be regenerated,
        # e.g. after an engine fix, without deleting the old .dat first),
        # Watch only lights up once a replay actually exists for the
        # selected match.
        self.generate_button = QPushButton("Generate")
        self.generate_button.setEnabled(False)
        self.watch_button = QPushButton("Watch")
        self.watch_button.setEnabled(False)
        filter_row.addWidget(self.search_t1_box, 2)
        filter_row.addWidget(self.search_t2_box, 2)
        filter_row.addWidget(self.result_filter_combo, 1)
        filter_row.addWidget(self.count_label)
        filter_row.addWidget(self.generate_button)
        filter_row.addWidget(self.watch_button)
        layout.addLayout(filter_row)

        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        # Qt's own default when sorting is enabled with no sort indicator
        # set yet is column 0, *descending* -- not ascending, and not "load
        # order" -- so without this the table opens Trainer 1 Z-A. Pin an
        # explicit A-Z default instead of inheriting that.
        self.table.sortByColumn(0, Qt.AscendingOrder)
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
        self.search_t1_box.textChanged.connect(lambda _: self._filter_timer.start())
        self.search_t2_box.textChanged.connect(lambda _: self._filter_timer.start())
        self.result_filter_combo.currentIndexChanged.connect(self._apply_filter)
        self.generate_button.clicked.connect(self._on_generate_clicked)
        self.watch_button.clicked.connect(self._on_watch_clicked)
        self.table.doubleClicked.connect(lambda _: self._on_double_clicked())
        self.table.selectionModel().selectionChanged.connect(self._refresh_match_buttons)

        settings = QSettings()
        ui_settings.bind_combo(settings, "browse/battle_type", self.battle_type_combo)
        ui_settings.bind_combo(settings, "browse/curse_variant", self.curse_variant_combo)
        ui_settings.bind_combo(settings, "browse/result_filter", self.result_filter_combo)

        self.refresh()
        self._precompute_other_formats()

    def _lib(self):
        if self._results_lib is None:
            self._results_lib = load_results_lib(self.config.analysis_dir)
        return self._results_lib

    def _precompute_other_formats(self):
        """Builds and stashes every other battle_type x curse_variant
        combo's row cache right after construction, so later switching to
        one of them (via the combo boxes) hits the bounded cache in
        _load_format instead of paying the full build cost as a mid-session
        hitch. This runs during MainWindow's construction, while the boot
        splash screen is already up for the unavoidable initial-load wait --
        clustering the wait there instead of leaving it scattered across
        whichever format the user happens to click into first. Silently
        skips a format that fails to load (e.g. no ratings dumped for it
        yet) rather than raising -- _load_format still surfaces that error
        properly if the user actually navigates there themselves."""
        lib = self._lib()
        for battle_type, _ in format_selector.BATTLE_TYPES:
            for curse_variant, _ in format_selector.CURSE_VARIANTS:
                fmt = format_selector.format_key(battle_type, curse_variant)
                if not fmt or fmt == self._current_format or fmt in self._format_row_cache:
                    continue
                try:
                    rows = lib.load_results(fmt, results_dir=self.config.results_dir)
                except (OSError, FileNotFoundError, ValueError):
                    continue
                # Missing ratings shouldn't block precomputing this format --
                # matches _load_format's own tolerance for a format with no
                # ratings dumped yet (blank rating columns, not an error).
                try:
                    ratings = lib.load_ratings(fmt)
                except (OSError, FileNotFoundError):
                    ratings = {}
                cache = self._model.build_row_cache(rows, lib, ratings)
                self._format_row_cache[fmt] = (rows, lib, cache)

    def _current_fmt(self):
        return format_selector.format_key(
            self.battle_type_combo.currentData(), self.curse_variant_combo.currentData()
        )

    def refresh(self):
        # An explicit Refresh click means "get whatever's on disk now" --
        # results_lib's own load_results cache already auto-invalidates
        # against shard file mtimes, but this tab's own built-cache layer
        # doesn't check that on every format switch (that's the whole
        # point, it's what makes revisiting a format instant), so Refresh
        # has to drop it or a click here would keep showing whatever was
        # cached at first visit.
        self._format_row_cache = {}
        self._reload()

    def _reload(self):
        self._load_format(self._current_fmt())

    def _load_format(self, fmt):
        self._current_format = fmt or None
        if not fmt:
            self._model.set_rows([], None)
            self.count_label.setText("")
            self._refresh_match_buttons()
            return

        cached = self._format_row_cache.get(fmt)
        if cached is not None:
            rows, lib, cache = cached
            self._model.set_rows(rows, lib, cache=cache)
            self._apply_filter()
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

        cache = self._model.set_rows(rows, lib, ratings)
        self._format_row_cache[fmt] = (rows, lib, cache)
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
        self._refresh_match_buttons()

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

    def _current_match_payload(self):
        """(slug, payload) for whatever's selected right now, or (None,
        None) if nothing's selected/loaded."""
        row = self._selected_row()
        if row is None or not self._current_format:
            return None, None
        slug = self._match_slug(self._current_format, row.get("trainer1", ""), row.get("trainer2", ""), row.get("seed"))
        payload = dict(row)
        payload["format"] = self._current_format
        payload["output_name"] = slug
        return slug, payload

    def _refresh_match_buttons(self):
        self._current_slug, payload = self._current_match_payload()
        self._current_payload = payload
        self._current_dat_path = (
            replay_env.find_existing_replay(self.config.replay_dir, self._current_slug) if self._current_slug else None
        )
        self.generate_button.setEnabled(payload is not None and not self._vendor_blocked)
        self.watch_button.setEnabled(self._current_dat_path is not None and not self._vendor_blocked)

    def _on_generate_clicked(self):
        if self._current_payload is not None:
            self.match_selected.emit(self._current_payload)

    def _on_watch_clicked(self):
        if self._current_dat_path is not None:
            self.watch_requested.emit(self._current_dat_path, {})

    def _on_double_clicked(self):
        if self._current_dat_path is not None:
            self._on_watch_clicked()
        else:
            self._on_generate_clicked()

    def set_actions_blocked(self, blocked):
        self._vendor_blocked = blocked
        self._refresh_match_buttons()

    def handle_generation_finished(self, dat_path, _result):
        name = os.path.splitext(os.path.basename(dat_path))[0]
        if name == self._current_slug:
            self._refresh_match_buttons()

    def handle_replay_finished(self, dat_path, _result):
        name = os.path.splitext(os.path.basename(dat_path))[0]
        if name == self._current_slug:
            self._refresh_match_buttons()
