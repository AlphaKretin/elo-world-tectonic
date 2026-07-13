"""Trainers tab: per-trainer curated highlights (best win, worst loss,
self-mirror upset) across every format at once, analogous to the website's
trainer cards but live in the app -- computed in-memory from the same
results/ratings data the rest of the viewer already has, not read back from
analysis/best_worst/*.json, so there's nothing else to keep in sync.

Never launches Game.exe itself -- Generate hands a prefilled request off to
the Generate tab (same as Bracket/Browse's own handoff), and Watch only
ever opens a replay that's already on disk, so backdrop customization,
debug mode, etc. all stay available through the real Generate tab instead
of being reimplemented here.
"""
import os

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import format_selector, ui_settings
from app.elided_tooltip_delegate import ElidedTooltipDelegate
from app.replay_action_button import ReplayActionButton
from app.results_source import load_results_lib
from app.sprite_loader import SpriteLoader
from app.tooltip_header import install_header_tooltips
from app.trainer_names import TrainerNameResolver, load_trainer_naming

# Full native resolution -- a whole page is dedicated to one trainer here,
# unlike the bracket's small cramped cards, so there's no reason to downscale.
PROFILE_SPRITE_SIZE = 160
PROFILE_BADGE_SIZE = 48

HIGHLIGHT_BEST_WIN = "best_win"
HIGHLIGHT_WORST_LOSS = "worst_loss"
HIGHLIGHT_SELF_MIRROR = "self_mirror"
HIGHLIGHT_LABELS = {
    HIGHLIGHT_BEST_WIN: "Best win",
    HIGHLIGHT_WORST_LOSS: "Worst loss",
    HIGHLIGHT_SELF_MIRROR: "Self-mirror upset",
}

class _NumericItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by a stored numeric value instead of the
    displayed text (so "980" doesn't sort after "1400" as strings would).
    Missing values (value=None) are treated as the lowest possible rating/
    count rather than chasing a direction-invariant "always last" -- unlike
    Browse tab's rating-diff sort, there's no explicit default-descending
    expectation here, and an unrated trainer sorting to the bottom on a
    plain ascending-by-default click is the natural reading."""

    def __init__(self, text, value):
        super().__init__(text)
        self._value = value if value is not None else -1

    def __lt__(self, other):
        return self._value < getattr(other, "_value", -1)


class TrainersTab(QWidget):
    watch_requested = Signal(str, dict)
    generate_requested = Signal(dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._names = TrainerNameResolver(config)
        self._trainer_data_cache = None
        self._naming_cache = None
        self._best_worst_lib = None
        self._notable_matches_lib = None
        self._sprites = SpriteLoader(config, self._trainer_data, self._is_cursed)
        self._format_data = {}  # fmt -> {battle_type, curse_variant, ratings, best_win, worst_loss, self_mirror_by_loser}
        self._selected_label = None
        self._vendor_blocked = False
        self._row_buttons = []  # one ReplayActionButton per highlights_table row, see _add_highlight_row

        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        rating_format_row = QHBoxLayout()
        rating_format_row.addWidget(QLabel("Rating format:"))
        self.rating_battle_type_combo = QComboBox()
        for value, label in format_selector.BATTLE_TYPES:
            self.rating_battle_type_combo.addItem(label, value)
        self.rating_curse_variant_combo = QComboBox()
        for value, label in format_selector.CURSE_VARIANTS:
            self.rating_curse_variant_combo.addItem(label, value)
        rating_format_row.addWidget(self.rating_battle_type_combo, 1)
        rating_format_row.addWidget(self.rating_curse_variant_combo, 1)
        left_layout.addLayout(rating_format_row)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search trainers...")
        # A plain QTableWidget (not Browse tab's custom QAbstractTableModel)
        # is enough here -- trainer_data.json only ever has a few hundred
        # rows (see TrainerNameResolver's docstring), nowhere near the
        # ~150k-row scale that model exists to handle. Rating and Highlights
        # columns let a self-mirror upset (which bumps Highlights above the
        # usual best_win+worst_loss x 4 formats = 8 baseline) surface by
        # sorting, without needing to already know which trainer has one.
        self.trainer_table = QTableWidget(0, 3)
        self.trainer_table.setHorizontalHeaderLabels(["Name", "Rtg", "Hlts"])
        self.trainer_table.horizontalHeaderItem(1).setToolTip(
            "Rating in the format selected above"
        )
        self.trainer_table.horizontalHeaderItem(2).setToolTip(
            "Notable-match count across every format (best win + worst loss x 4 formats = 8 baseline; "
            "higher means a self-mirror upset in at least one format)"
        )
        self.trainer_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.trainer_table.setColumnWidth(1, 45)
        self.trainer_table.setColumnWidth(2, 50)
        self.trainer_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trainer_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trainer_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.trainer_table.verticalHeader().setVisible(False)
        self.trainer_table.setSortingEnabled(True)
        install_header_tooltips(self.trainer_table)
        # Full name as a tooltip, but only once the column's too narrow to
        # show it in full -- not on every cell regardless.
        self.trainer_table.setItemDelegateForColumn(0, ElidedTooltipDelegate(self.trainer_table))
        left_layout.addWidget(self.search_box)
        left_layout.addWidget(self.trainer_table)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        header_row = QHBoxLayout()
        self.sprite_label = QLabel()
        self.sprite_label.setFixedSize(PROFILE_SPRITE_SIZE, PROFILE_SPRITE_SIZE)
        self.sprite_label.setAlignment(Qt.AlignCenter)
        self.name_label = QLabel()
        header_row.addWidget(self.sprite_label)
        header_row.addWidget(self.name_label, 1)
        right_layout.addLayout(header_row)

        self.status_label = QLabel()
        right_layout.addWidget(self.status_label)

        self.highlights_table = QTableWidget(0, 7)
        self.highlights_table.setHorizontalHeaderLabels(
            ["Format", "Curse", "Type", "Opponent", "Rnds", "Diff", ""]
        )
        self.highlights_table.horizontalHeaderItem(1).setToolTip("Curse variant")
        self.highlights_table.horizontalHeaderItem(4).setToolTip("Number of rounds the battle lasted")
        self.highlights_table.horizontalHeaderItem(5).setToolTip(
            "Rating difference between this trainer and the opponent shown"
        )
        self.highlights_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        # Narrow, explicit widths for everything but Opponent -- matches the
        # thin-numeric-column look Browse tab's table and the website's own
        # notable-matches table both settled on.
        for col, width in {0: 60, 1: 70, 2: 110, 4: 55, 5: 55, 6: 80}.items():
            self.highlights_table.setColumnWidth(col, width)
        install_header_tooltips(self.highlights_table)
        self.highlights_table.setItemDelegateForColumn(3, ElidedTooltipDelegate(self.highlights_table))
        self.highlights_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.highlights_table.setSelectionMode(QTableWidget.NoSelection)
        self.highlights_table.verticalHeader().setVisible(False)
        self.highlights_table.setSortingEnabled(True)
        # setCellWidget's Generate/Watch button is tied to a (row, col)
        # position, not to the row's items -- Qt's own sort only moves the
        # QTableWidgetItems, so a resort silently strands each button on its
        # old row. Re-run the (row -> button) reattachment every time the
        # sort indicator actually changes to keep them in sync.
        self.highlights_table.horizontalHeader().sortIndicatorChanged.connect(
            lambda *_: self._reattach_highlight_row_widgets()
        )
        right_layout.addWidget(self.highlights_table)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.search_box.textChanged.connect(self._apply_filter)
        self.trainer_table.currentItemChanged.connect(self._on_trainer_changed)
        self.rating_battle_type_combo.currentIndexChanged.connect(self._populate_trainer_list)
        self.rating_curse_variant_combo.currentIndexChanged.connect(self._populate_trainer_list)

        settings = QSettings()
        ui_settings.bind_combo(settings, "trainers/rating_battle_type", self.rating_battle_type_combo)
        ui_settings.bind_combo(settings, "trainers/rating_curse_variant", self.rating_curse_variant_combo)

        self.refresh()

    # -- trainer data / naming (mirrors BracketTab's own small helpers of
    # the same name -- not worth sharing a module over, unlike sprite
    # loading, which was a much larger chunk of logic) ----------------------

    def _trainer_data(self):
        if self._trainer_data_cache is None:
            results_lib = load_results_lib(self.config.analysis_dir)
            try:
                self._trainer_data_cache = results_lib.load_trainer_data(results_dir=self.config.results_dir)
            except OSError:
                self._trainer_data_cache = {}
        return self._trainer_data_cache

    def _naming(self):
        if self._naming_cache is None:
            self._naming_cache = load_trainer_naming(self.config.analysis_dir)
        return self._naming_cache

    def _is_cursed(self, label):
        if not label:
            return False
        row = self._trainer_data().get(label)
        if row is None:
            return False
        return self._naming().is_curse_variant(row, self._trainer_data())

    def _ensure_best_worst_lib(self):
        if self._best_worst_lib is None:
            load_results_lib(self.config.analysis_dir)  # side effect: puts analysis_dir on sys.path
            import best_worst

            self._best_worst_lib = best_worst
        return self._best_worst_lib

    def _ensure_notable_matches_lib(self):
        if self._notable_matches_lib is None:
            load_results_lib(self.config.analysis_dir)
            import notable_matches

            self._notable_matches_lib = notable_matches
        return self._notable_matches_lib

    # -- data loading ---------------------------------------------------

    def refresh(self):
        self._trainer_data_cache = None
        self._format_data = {}
        results_lib = load_results_lib(self.config.analysis_dir)
        best_worst_lib = self._ensure_best_worst_lib()
        notable_lib = self._ensure_notable_matches_lib()
        trainer_data = self._trainer_data()

        for battle_type, _ in format_selector.BATTLE_TYPES:
            for curse_variant, _ in format_selector.CURSE_VARIANTS:
                fmt = format_selector.format_key(battle_type, curse_variant)
                try:
                    ratings = results_lib.load_ratings(fmt)
                except (OSError, FileNotFoundError):
                    continue  # no ratings for this format yet -- skip it, not an error

                try:
                    rows = results_lib.load_results(fmt, results_dir=self.config.results_dir)
                except (OSError, FileNotFoundError):
                    rows = []
                # rows is passed in so compute_best_worst doesn't have to do
                # its own second full load_results() disk read + JSON parse
                # of the same format.
                best_win, worst_loss = best_worst_lib.compute_best_worst(fmt, ratings, rows=rows)
                self_mirror = notable_lib.find_self_mirror_losses(rows, trainer_data, ratings)
                self_mirror_by_loser = {entry["loser"]: entry for entry in self_mirror}

                # best_win/worst_loss entries don't carry rounds (see
                # best_worst.compute_best_worst) -- looked up separately here
                # instead of changing that tuple's shape, which would also
                # touch the website's best_worst_<fmt>.json schema. Keyed by
                # an order-independent trainer pair since best_win/worst_loss
                # only tell us the two trainers and seed, not which was
                # trainer1/trainer2 in the original row.
                rounds_index = {
                    (frozenset((row.get("trainer1"), row.get("trainer2"))), row.get("seed")): row.get("rounds")
                    for row in rows
                }

                self._format_data[fmt] = {
                    "battle_type": battle_type,
                    "curse_variant": curse_variant,
                    "ratings": ratings,
                    "best_win": best_win,
                    "worst_loss": worst_loss,
                    "self_mirror_by_loser": self_mirror_by_loser,
                    "rounds_index": rounds_index,
                }

        self._populate_trainer_list()
        self._render_profile()

    def _highlight_count(self, label):
        """Number of notable-match rows this trainer has across every
        format -- the usual baseline is best_win + worst_loss x 4 formats =
        8; a self-mirror upset in any format pushes it above 8, which is
        otherwise easy to miss without already knowing it's there."""
        count = 0
        for data in self._format_data.values():
            if data["best_win"].get(label) is not None:
                count += 1
            if data["worst_loss"].get(label) is not None:
                count += 1
            if data["self_mirror_by_loser"].get(label) is not None:
                count += 1
        return count

    def _reference_format(self):
        """Format the trainer list's Rating column currently reads from --
        user-selectable via the combos above the list, since ratings differ
        per format and there's no single natural default."""
        return format_selector.format_key(
            self.rating_battle_type_combo.currentData(), self.rating_curse_variant_combo.currentData()
        )

    def _populate_trainer_list(self):
        previous = self._selected_label
        self.trainer_table.setSortingEnabled(False)
        self.trainer_table.blockSignals(True)
        self.trainer_table.setRowCount(0)
        labels = sorted(self._trainer_data().keys(), key=lambda l: self._names.display_name(l).lower())
        reference_ratings = self._format_data.get(self._reference_format(), {}).get("ratings", {})
        for label in labels:
            row_idx = self.trainer_table.rowCount()
            self.trainer_table.insertRow(row_idx)

            name_item = QTableWidgetItem(self._names.display_name(label))
            name_item.setData(Qt.UserRole, label)
            self.trainer_table.setItem(row_idx, 0, name_item)

            rating = reference_ratings.get(label, {}).get("rating")
            rating_text = f"{rating:.0f}" if rating is not None else ""
            self.trainer_table.setItem(row_idx, 1, _NumericItem(rating_text, rating))

            highlights = self._highlight_count(label)
            self.trainer_table.setItem(row_idx, 2, _NumericItem(str(highlights), highlights))

        self.trainer_table.blockSignals(False)
        self.trainer_table.setSortingEnabled(True)
        self._apply_filter()

        if previous and self._select_label(previous):
            return
        if self.trainer_table.rowCount():
            self.trainer_table.setCurrentCell(0, 0)
        else:
            self._selected_label = None

    def _select_label(self, label):
        for row in range(self.trainer_table.rowCount()):
            item = self.trainer_table.item(row, 0)
            if item.data(Qt.UserRole) == label:
                self.trainer_table.setCurrentCell(row, 0)
                return True
        return False

    def _apply_filter(self):
        query = self.search_box.text().strip().lower()
        for row in range(self.trainer_table.rowCount()):
            item = self.trainer_table.item(row, 0)
            self.trainer_table.setRowHidden(row, bool(query) and query not in item.text().lower())

    def _on_trainer_changed(self, current, _previous):
        if current is None:
            self._selected_label = None
        else:
            name_item = self.trainer_table.item(current.row(), 0)
            self._selected_label = name_item.data(Qt.UserRole) if name_item else None
        self._render_profile()

    # -- profile rendering ------------------------------------------------

    def _render_profile(self):
        label = self._selected_label
        # Sorting off while rebuilding -- otherwise each insertRow() can
        # trigger an intermediate resort mid-population, same pattern as
        # _populate_trainer_list uses for trainer_table.
        self.highlights_table.setSortingEnabled(False)
        self.highlights_table.setRowCount(0)
        self._row_buttons = []

        if not label:
            self.sprite_label.clear()
            self.name_label.setText("")
            self.status_label.setText("")
            self.highlights_table.setSortingEnabled(True)
            return

        self.name_label.setText(self._names.display_name(label))
        pixmap = self._sprites.sprite_pixmap(label, PROFILE_SPRITE_SIZE, PROFILE_BADGE_SIZE)
        self.sprite_label.setPixmap(pixmap) if pixmap is not None else self.sprite_label.clear()

        for fmt, data in self._format_data.items():
            for highlight, source in ((HIGHLIGHT_BEST_WIN, data["best_win"]), (HIGHLIGHT_WORST_LOSS, data["worst_loss"])):
                entry = source.get(label)
                if entry is None:
                    continue
                opponent_rating, opponent_label, seed = entry
                own_rating = data["ratings"].get(label, {}).get("rating")
                diff = None if own_rating is None else own_rating - opponent_rating
                rounds = data["rounds_index"].get((frozenset((label, opponent_label)), seed))
                self._add_highlight_row(
                    fmt, data, highlight, label, opponent_label, diff, rounds, label, opponent_label, seed
                )

            mirror_entry = data["self_mirror_by_loser"].get(label)
            if mirror_entry is not None:
                row = mirror_entry["row"]
                wr, lr = mirror_entry["wr"], mirror_entry["lr"]
                diff = None if (wr is None or lr is None) else lr["rating"] - wr["rating"]
                self._add_highlight_row(
                    fmt, data, HIGHLIGHT_SELF_MIRROR, label, mirror_entry["winner"], diff, row.get("rounds"),
                    row["trainer1"], row["trainer2"], row["seed"],
                )

        self.status_label.setText("" if self._row_buttons else "No notable matches found for this trainer yet.")
        # Re-enabling applies whatever sort indicator was already showing
        # (last user click, or the default) via a direct sortByColumn() call
        # rather than the sortIndicatorChanged signal, so it won't reach the
        # handler connected to that signal -- reattach explicitly here too.
        self.highlights_table.setSortingEnabled(True)
        self._reattach_highlight_row_widgets()

    def _reattach_highlight_row_widgets(self):
        for row in range(self.highlights_table.rowCount()):
            item = self.highlights_table.item(row, 0)
            button = item.data(Qt.UserRole) if item is not None else None
            if button is not None:
                self.highlights_table.setCellWidget(row, 6, button)

    def _add_highlight_row(
        self, fmt, data, highlight, subject_label, opponent_label, diff, rounds, trainer1, trainer2, seed
    ):
        row_idx = self.highlights_table.rowCount()
        self.highlights_table.insertRow(row_idx)

        battle_type_label = dict(format_selector.BATTLE_TYPES)[data["battle_type"]]
        curse_variant_label = dict(format_selector.CURSE_VARIANTS)[data["curse_variant"]]
        # +1 for display: the engine's stored round count is 0-indexed (see
        # results_lib.display_rounds), matching Browse tab's own Rnds column.
        rounds = load_results_lib(self.config.analysis_dir).display_rounds(rounds)
        rounds_text = str(rounds) if rounds is not None else ""
        diff_text = f"{diff:+.0f}" if diff is not None else ""

        name_item = QTableWidgetItem(battle_type_label)
        self.highlights_table.setItem(row_idx, 0, name_item)
        self.highlights_table.setItem(row_idx, 1, QTableWidgetItem(curse_variant_label))
        self.highlights_table.setItem(row_idx, 2, QTableWidgetItem(HIGHLIGHT_LABELS[highlight]))
        self.highlights_table.setItem(row_idx, 3, QTableWidgetItem(self._names.display_name(opponent_label)))
        self.highlights_table.setItem(row_idx, 4, _NumericItem(rounds_text, rounds))
        self.highlights_table.setItem(row_idx, 5, _NumericItem(diff_text, diff))

        slug = self._highlight_slug(fmt, subject_label, highlight)
        button = ReplayActionButton(self.config.replay_dir)
        button.set_vendor_blocked(self._vendor_blocked)
        button.refresh(slug, {
            "trainer1": trainer1,
            "trainer2": trainer2,
            "seed": seed,
            "format": fmt,
            "output_name": slug,
        })
        button.generate_requested.connect(self.generate_requested.emit)
        button.watch_requested.connect(self.watch_requested.emit)
        # Stashed on column 0's item (not indexed by row) so the button can
        # be found again and reattached to wherever this row ends up after
        # a sort -- setCellWidget itself doesn't follow the item.
        name_item.setData(Qt.UserRole, button)
        self.highlights_table.setCellWidget(row_idx, 6, button)
        self._row_buttons.append(button)

    @staticmethod
    def _highlight_slug(fmt, label, highlight):
        """Deterministic filename-safe id for exactly this
        (format, trainer, highlight) -- simpler than bracket_lib's
        bracket_replay_slug since there's no round/match/attempt to encode,
        just enough to tell each of a trainer's highlight rows apart and to
        recognize the resulting .dat/sidecar again on a later refresh."""
        safe_label = "".join(ch if ch.isalnum() else "-" for ch in label)
        return f"trainer_{fmt}_{safe_label}_{highlight}"

    def set_actions_blocked(self, blocked):
        self._vendor_blocked = blocked
        for button in self._row_buttons:
            button.set_vendor_blocked(blocked)

    # -- hand-off refresh hooks (mirrors BracketTab's of the same name) -----

    def handle_generation_finished(self, dat_path, _result):
        self._recheck_matching_row(dat_path)

    def handle_replay_finished(self, dat_path, _result):
        self._recheck_matching_row(dat_path)

    def _recheck_matching_row(self, dat_path):
        name = os.path.splitext(os.path.basename(dat_path))[0]
        for button in self._row_buttons:
            if button.matches_slug(name):
                button.recheck()
