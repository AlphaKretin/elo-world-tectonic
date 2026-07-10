"""Bracket tab: a hand-curated top-16 single-elimination bracket, resolved
match-by-match either instantly (looked up from existing round-robin results
or a previously-generated bracket sidecar) or by generating a fresh battle
via the Generate tab, so a curated bracket can be watched progressively
round-by-round rather than dumped all at once. See app/bracket_lib.py
for the tree/lookup/seed logic this tab drives.

This tab never launches Game.exe itself -- that's already the Generate/Watch
tabs' job. "Generate" here just hands off a prefilled request to the Generate
tab (same as Browse's match_selected handoff); "Watch" only ever opens a
replay that's already on disk. A match's bracket-level outcome is only ever
revealed by an explicit Skip or Watch click, never by generation finishing in
the background, so watching a replay is never spoiled ahead of time."""
import glob
import json
import os
import random

from PySide6.QtCore import QRegularExpression, QSettings, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app import bracket_seeds, custom_brackets, replay_env, ui_settings
from app.bracket_canvas import BracketCanvas
from app.bracket_manager_dialog import BracketManagerDialog
from app.results_source import load_results_lib
from app.sprite_loader import SpriteLoader
from app.trainer_names import TrainerNameResolver, load_trainer_naming

SPRITE_SIZE = 40  # trainer sprites are 160x160 pixel art; 40 is a clean 4x nearest-neighbor downscale
CURSE_BADGE_SIZE = 24  # the amulet badge is 48x48 pixel art; 24 is a clean 2x nearest-neighbor downscale
CURSED_TEXT_SUFFIX = " (Cursed)"  # trainer_naming.resolve_display_name's text marker, for text-only contexts;
# the bracket is graphical, so it shows the same Tarot Amulet badge trainer_cards.py/the website use instead.


class BracketTab(QWidget):
    watch_requested = Signal(str, dict)
    generate_requested = Signal(dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._names = TrainerNameResolver(config)
        self._bracket_lib = None  # lazily imported, see _ensure_bracket_lib

        self.fmt = None
        self.rounds = None
        self.results_index = {}
        self._results_index_cache = {}  # fmt -> base index (round-robin rows only, no sidecars) -- see _load_results_index
        self._trainer_data_cache = None
        self._naming_cache = None
        self._vendor_blocked = False
        self._sprites = SpriteLoader(config, self._trainer_data, self._is_cursed)

        layout = QVBoxLayout(self)

        format_row = QHBoxLayout()
        self.bracket_combo = QComboBox()
        for entry in self._all_brackets():
            self.bracket_combo.addItem(entry["name"], entry)
        self.wins_needed_spin = QSpinBox()
        self.wins_needed_spin.setRange(1, 9)
        self.wins_needed_spin.setValue(2)
        format_row.addWidget(QLabel("Bracket:"))
        format_row.addWidget(self.bracket_combo, 1)
        format_row.addWidget(QLabel("Games to win:"))
        format_row.addWidget(self.wins_needed_spin)
        self.manage_brackets_button = QPushButton("Custom Brackets...")
        format_row.addWidget(self.manage_brackets_button)
        self.show_seeds_checkbox = QCheckBox("Show seeds")
        format_row.addWidget(self.show_seeds_checkbox)
        self.reveal_button = QPushButton("Reveal remaining")
        format_row.addWidget(self.reveal_button)
        layout.addLayout(format_row)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.canvas = BracketCanvas()
        self.scroll_area.setWidget(self.canvas)
        layout.addWidget(self.scroll_area)

        self.bracket_combo.currentIndexChanged.connect(self._on_bracket_changed)
        self.wins_needed_spin.valueChanged.connect(self._on_bracket_changed)
        self.manage_brackets_button.clicked.connect(self._on_manage_brackets_clicked)
        self.show_seeds_checkbox.toggled.connect(self._render)
        self.reveal_button.clicked.connect(self._on_reveal_remaining_clicked)

        settings = QSettings()
        ui_settings.bind_combo(settings, "bracket/name", self.bracket_combo)
        ui_settings.bind_spinbox(settings, "bracket/wins_needed", self.wins_needed_spin)
        ui_settings.bind_checkbox(settings, "bracket/show_seeds", self.show_seeds_checkbox)

        self._on_bracket_changed()
        self._precompute_other_formats()

    # -- setup / teardown --------------------------------------------------

    def set_actions_blocked(self, blocked):
        self._vendor_blocked = blocked
        if self.rounds is not None:
            self._render()

    def _ensure_bracket_lib(self):
        if self._bracket_lib is None:
            load_results_lib(self.config.analysis_dir)  # side effect: puts analysis_dir on sys.path, needed by bracket_lib's own `import results_lib`
            from app import bracket_lib

            self._bracket_lib = bracket_lib
        return self._bracket_lib

    def _all_brackets(self):
        """Curated brackets (bracket_seeds.py, source-controlled) followed by
        custom ones (custom_brackets.json, local user data) -- combo entries
        are treated identically regardless of which list they came from, see
        bracket_tab.py module docstring / project plan discussion."""
        return bracket_seeds.BRACKETS + custom_brackets.load_custom_brackets(self.config)

    def _on_manage_brackets_clicked(self):
        dialog = BracketManagerDialog(self.config, bracket_seeds.BRACKETS, parent=self)
        dialog.exec()
        if dialog.changed:
            self._reload_bracket_combo()

    def _reload_bracket_combo(self):
        previous_entry = self.bracket_combo.currentData()
        previous_name = previous_entry["name"] if previous_entry else None
        self.bracket_combo.blockSignals(True)
        self.bracket_combo.clear()
        for entry in self._all_brackets():
            self.bracket_combo.addItem(entry["name"], entry)
        idx = self.bracket_combo.findText(previous_name) if previous_name else -1
        if idx >= 0:
            self.bracket_combo.setCurrentIndex(idx)
        self.bracket_combo.blockSignals(False)
        self._on_bracket_changed()

    def _on_bracket_changed(self):
        entry = self.bracket_combo.currentData()
        if entry is None:
            self.fmt = None
            self.rounds = None
            self.status_label.setText("No curated brackets defined yet.")
            self.canvas.set_rounds([], [])
            self.reveal_button.setEnabled(False)
            return

        self.fmt = entry["format"]
        labels = entry["seeds"]

        bracket_lib = self._ensure_bracket_lib()
        try:
            self.rounds = bracket_lib.build_bracket_tree(labels, wins_needed=self.wins_needed_spin.value())
        except ValueError as exc:
            self.rounds = None
            self.status_label.setText(str(exc))
            self.canvas.set_rounds([], [])
            self.reveal_button.setEnabled(False)
            return

        self.status_label.setText("")
        self.reveal_button.setEnabled(True)
        self._load_results_index()
        for match in self.rounds[0]:
            self._ensure_match_seed(match)
        self._render()

    # -- results index (round-robin rows + cached bracket sidecars) --------

    def _load_results_index(self):
        base_index = self._build_base_index(self.fmt)
        # Copied so the sidecar merge below (which mutates self.results_index
        # in place) never corrupts the cached base index -- otherwise
        # switching back to this format later would re-append the same
        # sidecar rows on top of ones already merged in last time.
        self.results_index = {key: list(rows) for key, rows in base_index.items()}
        self._merge_cached_sidecars()

    def _build_base_index(self, fmt):
        base_index = self._results_index_cache.get(fmt)
        if base_index is None:
            results_lib = load_results_lib(self.config.analysis_dir)
            bracket_lib = self._ensure_bracket_lib()
            rows = results_lib.load_results(fmt, results_dir=self.config.results_dir)
            base_index = bracket_lib.build_results_index(rows)
            self._results_index_cache[fmt] = base_index
        return base_index

    def _precompute_other_formats(self):
        """Mirrors BrowseTab's _precompute_other_formats: builds the
        (sidecar-free) results index for every other bracket format right
        after construction, while the boot splash is already up, so later
        switching to a bracket that uses one of them hits the cache in
        _build_base_index instead of paying build_results_index's full O(n)
        frozenset-index rebuild as a mid-session hitch. Silently skips a
        format that fails to load, same tolerance as Browse's version."""
        seen_formats = {entry["format"] for entry in self._all_brackets()}
        for fmt in seen_formats:
            if fmt == self.fmt or fmt in self._results_index_cache:
                continue
            try:
                self._build_base_index(fmt)
            except (OSError, FileNotFoundError, ValueError):
                continue

    def _merge_cached_sidecars(self):
        bracket_lib = self._ensure_bracket_lib()
        prefix = f"bracket_{self.fmt}_"
        pattern = os.path.join(self.config.replay_metadata_dir, prefix + "*.json")
        for path in glob.glob(pattern):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    sidecar = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            row = self._sidecar_as_row(sidecar)
            if row is None:
                continue
            key = frozenset({row["trainer1"], row["trainer2"]})
            self.results_index.setdefault(key, []).append(row)

    def _sidecar_as_row(self, sidecar):
        """Bracket sidecars store the engine's raw per-battle result, which
        is already the same 1=trainer1 wins/2=trainer2 wins/5=draw scale as
        results_lib.WIN/LOSS/DRAW (see replay_runner.outcome_label), so no
        rescaling is needed here. 0 is not a real outcome though -- it's the
        engine's pre-battle sentinel, left in place if a watched recording
        was cancelled in-game before a decision was ever reached -- so it
        must be rejected rather than misread as a draw."""
        results_lib = load_results_lib(self.config.analysis_dir)
        raw = sidecar.get("result")
        valid = (results_lib.WIN, results_lib.LOSS, results_lib.DRAW)
        if raw not in valid or "trainer1" not in sidecar or "trainer2" not in sidecar:
            return None
        return {
            "trainer1": sidecar["trainer1"],
            "trainer2": sidecar["trainer2"],
            "result": raw,
            "seed": sidecar.get("seed"),
        }

    def _read_sidecar_for_replay(self, dat_path):
        name = os.path.splitext(os.path.basename(dat_path))[0]
        sidecar_path = os.path.join(self.config.replay_metadata_dir, name + ".json")
        try:
            with open(sidecar_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    # -- seed bookkeeping ----------------------------------------------------

    def _ensure_match_seed(self, match):
        """Assigns match.seed the first time both entrants are known -- the
        round-robin seed for this pairing if one exists (so the bracket
        reproduces the known result by default), else a deterministic
        fresh-generation seed. A no-op once seed is set (including after a
        user reroll/edit), and a no-op while either entrant is still
        unknown (a later round's match, before both its parent matches have
        resolved)."""
        if match.seed is not None or match.label_a is None or match.label_b is None:
            return
        bracket_lib = self._ensure_bracket_lib()
        row = bracket_lib.pick_default_row(self.results_index, match.label_a, match.label_b)
        if row is not None:
            match.seed = row["seed"]
        else:
            match.seed = bracket_lib.derive_fresh_seed(
                self.fmt, match.round_idx, match.match_idx, match.label_a, match.label_b
            )

    def _current_row(self, match):
        """The row (round-robin, or a locally generated replay) whose seed
        matches match.seed, or None if that seed hasn't been played yet.
        Checks self.results_index first (round-robin plus any sidecar
        already merged in by a past Refresh), then falls back to reading the
        matching replay's sidecar directly off disk -- so a replay just
        generated this session is picked up immediately, without needing an
        explicit Refresh first (mirrors the old dual-source lookup this
        replaces). A drawn row can never decide the match, so it's silently
        consumed here -- recorded into match.attempts and match.seed
        advanced to the next seed in the chain -- and lookup retried,
        cascading through any number of consecutive draws. Only ever
        returns None or a decisive (WIN/LOSS) row."""
        bracket_lib = self._ensure_bracket_lib()
        results_lib = load_results_lib(self.config.analysis_dir)
        while True:
            row = bracket_lib.find_row_for_seed(self.results_index, match.label_a, match.label_b, match.seed)
            if row is None:
                row = self._local_row_for_seed(match)
            if row is None or row["result"] != results_lib.DRAW:
                return row
            bracket_lib.record_attempt(match, None, None, match.seed)
            match.seed = bracket_lib.next_attempt_seed(match.seed)

    def _local_row_for_seed(self, match):
        dat_path = self._find_existing_replay(match)
        if dat_path is None:
            return None
        sidecar = self._read_sidecar_for_replay(dat_path)
        return self._sidecar_as_row(sidecar) if sidecar else None

    # -- sprites / curse marker --------------------------------------------

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

    # -- rendering -----------------------------------------------------------

    def _render(self):
        if not self.rounds:
            self.canvas.set_rounds([], [])
            return
        bracket_lib = self._ensure_bracket_lib()

        round_names = [
            bracket_lib.ROUND_NAMES[i] if i < len(bracket_lib.ROUND_NAMES) else f"Round {i + 1}"
            for i in range(len(self.rounds))
        ]
        card_rows = []
        any_generation_needed = False
        for matches in self.rounds:
            cards = []
            for match in matches:
                card, needs_generation = self._build_match_card(match)
                cards.append(card)
                any_generation_needed = any_generation_needed or needs_generation
            card_rows.append(cards)

        final_match = self.rounds[-1][0] if self.rounds[-1] else None
        champion_text = None
        if final_match and final_match.resolved:
            champion_text = f"Champion: {self._strip_cursed_suffix(self._names.display_name(final_match.winner_label))}"

        # Height still comes from the whole card's natural size (sprite
        # rows + footer). Width deliberately ignores the entrant/name rows
        # and is pinned to the footer's widest *intended* layout (see
        # _reference_card_width) rather than measured off whatever's
        # actually on screen right now -- a match losing its Skip button or
        # shrinking to "Winner (1-0)" once resolved must not make every
        # card (and the whole bracket) visibly narrower over the course of
        # a session. An unusually long name still clips instead of widening
        # every card and column.
        all_cards = [card for cards in card_rows for card in cards if card is not None]
        card_height = max((card.sizeHint().height() for card in all_cards), default=None)
        card_width = self._reference_card_width()

        self.canvas.set_rounds(
            round_names, card_rows, champion_text=champion_text, card_height=card_height, card_width=card_width
        )
        self._any_generation_needed = any_generation_needed

    def _reference_card_width(self):
        """Footer width under the widest *intended* layout -- both Skip and
        Watch buttons present, alongside a full score prefix and "Replay
        ready" -- measured on a throwaway, never-shown footer rather than
        derived from whichever cards happen to be on screen right now. See
        _render's card_width comment for why this needs to be pinned."""
        max_score_digit = max(self.wins_needed_spin.value() - 1, 0)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        skip_button = QPushButton("Skip")
        watch_button = QPushButton("Watch")
        # Includes a worst-case "-draws" suffix (see Match.score_text) so a
        # match that picks one up mid-series doesn't outgrow this pinned
        # width.
        status_label = QLabel(f"{max_score_digit}-{max_score_digit}-{max_score_digit} — Replay ready")
        footer.addWidget(skip_button)
        footer.addWidget(watch_button)
        footer.addWidget(status_label, 1)
        width = footer.sizeHint().width()
        for widget in (skip_button, watch_button, status_label):
            widget.deleteLater()
        return width

    def _entrant_row(self, rank, label, bold=False):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        sprite_label = QLabel()
        sprite_label.setFixedSize(SPRITE_SIZE, SPRITE_SIZE)
        pixmap = self._sprites.sprite_pixmap(label, SPRITE_SIZE, CURSE_BADGE_SIZE)
        if pixmap is not None:
            sprite_label.setPixmap(pixmap)
        row.addWidget(sprite_label)

        text_label = QLabel(self._entrant_text(rank, label))
        if bold:
            font = text_label.font()
            font.setBold(True)
            text_label.setFont(font)
        row.addWidget(text_label, 1)
        return row

    def _build_match_card(self, match):
        card = QFrame(self.canvas)
        card.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignTop)

        winner_is_a = match.resolved and match.winner_label == match.label_a
        winner_is_b = match.resolved and match.winner_label == match.label_b
        layout.addLayout(self._entrant_row(match.rank_a, match.label_a, bold=winner_is_a))
        layout.addLayout(self._entrant_row(match.rank_b, match.label_b, bold=winner_is_b))

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        status_label = QLabel()
        needs_generation = False

        if not (match.ready or match.resolved):
            status_label.setText("Waiting")
            footer.addWidget(status_label, 1)
            layout.addLayout(footer)
            return card, needs_generation

        if match.resolved:
            # The tournament isn't trying to progress this match anymore --
            # no Skip/Watch/Generate once it's decided. Bumping "Games to
            # win" (even briefly) is how to see further games of an already-
            # decided match, rather than leaving a dangling Generate button
            # here that can't actually change the outcome.
            status_label.setText(f"Winner ({match.score_text})")
            footer.addWidget(status_label, 1)
            layout.addLayout(footer)
            return card, needs_generation

        # The winner of each attempt is only ever revealed by an explicit
        # Skip, or once a watched replay actually finishes (see
        # _on_skip_clicked / handle_replay_finished) -- never just because a
        # replay happens to exist -- so generating one in the background
        # never spoils a match before the user actually looks at it. Skip
        # and Watch are both equally explicit reveal actions though, so a
        # decisive replay already sitting on disk (this session or a past
        # one) is just as skippable as an RR result. _current_row is keyed
        # to match.seed specifically -- not "any known result for this
        # pairing" -- so a rerolled seed with no result yet correctly shows
        # Generate even though a different seed's result already exists.
        row = self._current_row(match)
        can_skip = row is not None
        has_local_replay = can_skip and self._find_existing_replay(match) is not None

        # Score prefix only appears once the series is actually underway --
        # the common instant-Skip case (and any best-of-1 bracket) looks
        # exactly like it always has.
        score_prefix = f"{match.score_text} — " if (match.wins_a or match.wins_b or match.draws) else ""

        if has_local_replay:
            status_label.setText(f"{score_prefix}Replay ready")
        else:
            status_label.setText(f"{score_prefix}Ready" if can_skip else f"{score_prefix}Needs generation")

        # Watch/Generate both actually launch Game.exe, and Skip applies a
        # result that a background Generate/Watch may itself still be in
        # the middle of producing -- so all three are refused outright
        # while the vendor download/compile could have Game.exe open
        # concurrently, same as ReplayActionButton's vendor_blocked (see
        # its docstring), not just left to the destination tab's own
        # is_valid() check.
        blocked_tooltip = "Waiting for the game files to finish downloading/compiling..." if self._vendor_blocked else ""

        # Hidden by default -- the seed row makes every ready card taller
        # than it needs to be for the common case of just clicking through
        # a bracket, so it's opt-in via the toolbar's "Show seeds" checkbox
        # rather than always shown.
        if self.show_seeds_checkbox.isChecked():
            seed_row = QHBoxLayout()
            seed_row.setContentsMargins(0, 0, 0, 0)
            seed_row.addWidget(QLabel("Seed:"))
            seed_edit = QLineEdit(str(match.seed))
            # QIntValidator caps out at a signed 32-bit int, but seeds here are
            # unsigned 32-bit (derive_fresh_seed/next_attempt_seed's hash-based
            # range, random.getrandbits(32) for reroll) -- a digits-only regex
            # validator has no such ceiling.
            seed_edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d+$"), seed_edit))
            seed_edit.editingFinished.connect(lambda m=match, e=seed_edit: self._on_seed_edited(m, e))
            seed_row.addWidget(seed_edit, 1)
            reroll_button = QPushButton("🎲")
            reroll_button.setFixedWidth(28)
            reroll_button.setToolTip("Reroll to a random seed")
            reroll_button.clicked.connect(lambda: self._on_reroll_clicked(match))
            seed_row.addWidget(reroll_button)
            layout.addLayout(seed_row)

        if can_skip:
            skip_button = QPushButton("Skip")
            skip_button.setEnabled(not self._vendor_blocked)
            skip_button.setToolTip(blocked_tooltip)
            skip_button.clicked.connect(lambda: self._on_skip_clicked(match))
            footer.addWidget(skip_button)

        if has_local_replay:
            watch_button = QPushButton("Watch")
            watch_button.setEnabled(not self._vendor_blocked)
            watch_button.setToolTip(blocked_tooltip)
            watch_button.clicked.connect(lambda: self._on_watch_clicked(match))
            footer.addWidget(watch_button)

        if not can_skip:
            needs_generation = True
            generate_button = QPushButton("Generate")
            generate_button.setEnabled(not self._vendor_blocked)
            generate_button.setToolTip(blocked_tooltip)
            generate_button.clicked.connect(lambda: self._on_generate_clicked(match))
            footer.addWidget(generate_button)

        footer.addWidget(status_label, 1)
        layout.addLayout(footer)
        return card, needs_generation

    def _strip_cursed_suffix(self, name):
        if name.endswith(CURSED_TEXT_SUFFIX):
            return name[: -len(CURSED_TEXT_SUFFIX)]
        return name

    def _entrant_text(self, rank, label):
        if label is None:
            return "TBD"
        return f"#{rank} {self._strip_cursed_suffix(self._names.display_name(label))}"

    # -- match resolution ----------------------------------------------------

    def _winner_from_row(self, match, row):
        """(winner_label, winner_rank) for a decisive row -- never called on
        a drawn row, callers branch on results_lib.DRAW before reaching here."""
        results_lib = load_results_lib(self.config.analysis_dir)
        if row["trainer1"] == match.label_a:
            winner_is_a = row["result"] == results_lib.WIN
        else:
            winner_is_a = row["result"] == results_lib.LOSS
        winner_label = match.label_a if winner_is_a else match.label_b
        winner_rank = match.rank_a if winner_is_a else match.rank_b
        return winner_label, winner_rank

    def _apply_known_pending_attempt(self, match):
        """If match.seed's outcome is already known (RR or a local replay,
        via _current_row -- which itself already consumes any draws found
        along the way), records the decisive result via
        bracket_lib.record_attempt -- advancing the bracket tree (and
        seeding the newly-completed parent match) if that decides the
        match, else advancing match.seed to the next seed in the chain for
        the next game of the series -- and returns True. Otherwise leaves
        the match untouched and returns False. Used by both an explicit
        Skip and "Reveal remaining"'s cascade; Skip/Watch are the only
        things that ever reveal a winner, but once something's already
        known, applying it isn't itself a new reveal."""
        row = self._current_row(match)
        if row is None:
            return False
        bracket_lib = self._ensure_bracket_lib()
        winner_label, winner_rank = self._winner_from_row(match, row)
        resolved = bracket_lib.record_attempt(match, winner_label, winner_rank, match.seed)
        if resolved:
            bracket_lib.advance_winner(self.rounds, match.round_idx, match.match_idx, winner_label, winner_rank)
            if match.round_idx + 1 < len(self.rounds):
                parent = self.rounds[match.round_idx + 1][match.match_idx // 2]
                self._ensure_match_seed(parent)
        else:
            match.seed = bracket_lib.next_attempt_seed(match.seed)
        return True

    def _on_skip_clicked(self, match):
        if not self._apply_known_pending_attempt(match):
            QMessageBox.information(
                self, "No result yet", "No result available yet for this seed -- use Generate."
            )
            return
        self._render()

    def _on_seed_edited(self, match, seed_edit):
        text = seed_edit.text().strip()
        try:
            seed = int(text)
        except ValueError:
            self._render()  # revert the field to match.seed's last valid value
            return
        if seed != match.seed:
            match.seed = seed
            self._render()

    def _on_reroll_clicked(self, match):
        match.seed = random.getrandbits(32)
        self._render()

    def _on_watch_clicked(self, match):
        # Only ever offered when _current_row found a decisive local replay
        # (see _build_match_card), so this just hands off -- winning doesn't
        # get revealed here. It's revealed by handle_replay_finished, once
        # the replay has actually finished playing, not the moment it's
        # opened.
        existing = self._find_existing_replay(match)
        if existing is None:
            QMessageBox.warning(self, "Replay not found", "No replay file was found for this match -- use Generate first.")
            return
        self.watch_requested.emit(existing, {})

    def handle_replay_finished(self, dat_path, result):
        """Connected to WatchTab.replay_finished. A crashed/cancelled Watch
        (ok=False) never applies, and neither does an in-game cancel (ok=True
        but result 0 -- the engine's pre-battle sentinel, never cleared
        because no decision was reached). A genuine draw (result 5) now does
        apply, same as a decisive result -- a draw is itself a played attempt
        that must be recorded to keep the next attempt's seed chain correct,
        unlike the old single-game bracket where a draw never needed any
        bookkeeping."""
        results_lib = load_results_lib(self.config.analysis_dir)
        valid = (results_lib.WIN, results_lib.LOSS, results_lib.DRAW)
        if not result.get("ok") or result.get("result") not in valid:
            return

        bracket_lib = self._ensure_bracket_lib()
        name = os.path.splitext(os.path.basename(dat_path))[0]
        parsed = bracket_lib.parse_bracket_slug(name)
        if parsed is None or parsed[0] != self.fmt or not self.rounds:
            return
        _, round_idx, match_idx = parsed
        if not (0 <= round_idx < len(self.rounds)) or not (0 <= match_idx < len(self.rounds[round_idx])):
            return
        match = self.rounds[round_idx][match_idx]
        if match.resolved:
            return
        # Guards against a stale/duplicate signal for a seed already applied
        # -- the finished file must be exactly the current pending seed, not
        # an earlier one.
        if name != self._match_slug_for_seed(match, match.seed):
            return

        if not self._apply_known_pending_attempt(match):
            return
        self._render()

    def _on_generate_clicked(self, match):
        # Hands off to the Generate tab instead of running anything here, so
        # the user can apply Generate's own customization (backdrop, debug
        # mode, etc.). The output name stays bracket-recognizable so the
        # sidecar Generate writes gets picked up as a cached result the next
        # time this tab is refreshed. Generate is only ever offered when
        # _current_row found nothing for match.seed (see _build_match_card),
        # so there's never a historical row to reproduce here -- trainer
        # order is always order_key's canonical order (see
        # project_trainer_order_dependence memory for why order isn't
        # cosmetic), never RR's order, since a fresh seed by definition has
        # no RR row backing it.
        bracket_lib = self._ensure_bracket_lib()
        trainer1_label, trainer2_label = bracket_lib.order_key.canonical_pair_order(match.label_a, match.label_b)
        slug = self._match_slug_for_seed(match, match.seed)
        self.generate_requested.emit({
            "trainer1": trainer1_label,
            "trainer2": trainer2_label,
            "seed": match.seed,
            "format": self.fmt,
            "output_name": slug,
            "suppress_winner": True,
        })
        self._render()

    def _on_reveal_remaining_clicked(self):
        changed = True
        while changed:
            changed = False
            for matches in self.rounds:
                for match in matches:
                    if match.resolved or not match.ready:
                        continue
                    if self._apply_known_pending_attempt(match):
                        changed = True
        self._render()
        if self._any_generation_needed:
            self.status_label.setText("Some matches still need generating -- use Generate on each.")
        else:
            self.status_label.setText("")

    def _refresh_results(self):
        # Picks up sidecars written by a hand-off to the Generate tab (which
        # doesn't report back to this tab directly) or by anything else
        # dropped into replay_metadata_dir since this format was last loaded.
        # Sidecars are always re-scanned fresh regardless of the cache below
        # (see _merge_cached_sidecars) -- busting this format's cached base
        # index too is what makes this also pick up newly-generated
        # round-robin results, not just sidecars. No manual trigger for this
        # anymore -- handle_generation_finished below is the only caller,
        # firing automatically whenever a bracket-handed-off Generate
        # finishes.
        self._results_index_cache.pop(self.fmt, None)
        self._load_results_index()
        self._render()

    def handle_generation_finished(self, dat_path, result):
        """Connected to GenerateTab.generation_finished, so a bracket-handed-off
        Generate that finishes while the user has since tabbed away (or is
        generating several matches in a row) still updates this tab's
        buttons/status on its own. Doesn't reveal any winner itself --
        that's still gated behind Skip/watching."""
        bracket_lib = self._ensure_bracket_lib()
        name = os.path.splitext(os.path.basename(dat_path))[0]
        parsed = bracket_lib.parse_bracket_slug(name)
        if parsed is None or parsed[0] != self.fmt:
            return
        self._refresh_results()

    # -- replay/seed bookkeeping ----------------------------------------------

    def _match_slug_for_seed(self, match, seed):
        bracket_lib = self._ensure_bracket_lib()
        return bracket_lib.bracket_replay_slug(
            self.fmt, match.round_idx, match.match_idx, match.rank_a, match.label_a, match.rank_b, match.label_b, seed
        )

    def _find_existing_replay(self, match):
        """.dat path for match.seed specifically -- not just "whatever's
        newest on disk" -- so a different seed's replay for this same match
        position is never mistaken for this one."""
        slug = self._match_slug_for_seed(match, match.seed)
        return replay_env.find_existing_replay(self.config.replay_dir, slug)

