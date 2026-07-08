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

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app import bracket_seeds, format_selector, ui_settings
from app.bracket_canvas import BracketCanvas
from app.results_source import load_results_lib
from app.trainer_names import TrainerNameResolver, load_trainer_naming

FILTER_CHOICES = [(None, "(none)"), ("cursed_excluded", "Cursed-excluded"), ("level70_only", "Level 70 only")]
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
        self.bracket_key = None
        self.rounds = None
        self.results_index = {}
        self._sprite_cache = {}
        self._card_data_cache = None
        self._naming_cache = None
        self._curse_badge_pixmap = None
        self._curse_badge_loaded = False

        layout = QVBoxLayout(self)

        format_row = QHBoxLayout()
        self.battle_type_combo = QComboBox()
        for value, label in format_selector.BATTLE_TYPES:
            self.battle_type_combo.addItem(label, value)
        self.curse_variant_combo = QComboBox()
        for value, label in format_selector.CURSE_VARIANTS:
            self.curse_variant_combo.addItem(label, value)
        self.filter_combo = QComboBox()
        for value, label in FILTER_CHOICES:
            self.filter_combo.addItem(label, value)
        self.wins_needed_spin = QSpinBox()
        self.wins_needed_spin.setRange(1, 9)
        self.wins_needed_spin.setValue(2)
        format_row.addWidget(QLabel("Battle type:"))
        format_row.addWidget(self.battle_type_combo, 1)
        format_row.addWidget(QLabel("Curse variant:"))
        format_row.addWidget(self.curse_variant_combo, 1)
        format_row.addWidget(QLabel("Filter:"))
        format_row.addWidget(self.filter_combo, 1)
        format_row.addWidget(QLabel("Games to win:"))
        format_row.addWidget(self.wins_needed_spin)
        self.reveal_button = QPushButton("Reveal remaining")
        format_row.addWidget(self.reveal_button)
        self.refresh_button = QPushButton("Refresh")
        format_row.addWidget(self.refresh_button)
        layout.addLayout(format_row)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.canvas = BracketCanvas()
        self.scroll_area.setWidget(self.canvas)
        layout.addWidget(self.scroll_area)

        self.battle_type_combo.currentIndexChanged.connect(self._on_format_changed)
        self.curse_variant_combo.currentIndexChanged.connect(self._on_format_changed)
        self.filter_combo.currentIndexChanged.connect(self._on_format_changed)
        self.wins_needed_spin.valueChanged.connect(self._on_format_changed)
        self.reveal_button.clicked.connect(self._on_reveal_remaining_clicked)
        self.refresh_button.clicked.connect(self._on_refresh_clicked)

        settings = QSettings()
        ui_settings.bind_combo(settings, "bracket/battle_type", self.battle_type_combo)
        ui_settings.bind_combo(settings, "bracket/curse_variant", self.curse_variant_combo)
        ui_settings.bind_combo(settings, "bracket/filter", self.filter_combo)
        ui_settings.bind_spinbox(settings, "bracket/wins_needed", self.wins_needed_spin)

        self._on_format_changed()

    # -- setup / teardown --------------------------------------------------

    def _ensure_bracket_lib(self):
        if self._bracket_lib is None:
            load_results_lib(self.config.analysis_dir)  # side effect: puts analysis_dir on sys.path, needed by bracket_lib's own `import results_lib`
            from app import bracket_lib

            self._bracket_lib = bracket_lib
        return self._bracket_lib

    def _on_format_changed(self):
        battle_type = self.battle_type_combo.currentData()
        curse_variant = self.curse_variant_combo.currentData()
        filter_name = self.filter_combo.currentData()
        self.fmt = format_selector.format_key(battle_type, curse_variant)
        self.bracket_key = self.fmt + (f"_{filter_name}" if filter_name else "")

        labels = bracket_seeds.BRACKET_SEEDS.get(self.bracket_key)
        if not labels:
            self.rounds = None
            self.status_label.setText(f"No curated bracket for '{self.bracket_key}' yet.")
            self.canvas.set_rounds([], [])
            self.reveal_button.setEnabled(False)
            return

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
        self._render()

    # -- results index (round-robin rows + cached bracket sidecars) --------

    def _load_results_index(self):
        results_lib = load_results_lib(self.config.analysis_dir)
        bracket_lib = self._ensure_bracket_lib()
        rows = results_lib.load_results(self.fmt, results_dir=self.config.results_dir)
        self.results_index = bracket_lib.build_results_index(rows)
        self._merge_cached_sidecars()

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
        """Bracket sidecars store the engine's raw generation result (0=draw,
        1=trainer1 wins, 2=trainer2 wins, per replay_runner.outcome_label),
        a different scale than the round-robin jsonl's (1=win, 2=loss,
        5=draw, see results_lib.WIN/LOSS/DRAW). Normalize to the RR scale so
        bracket_lib.lookup_result can treat both sources identically."""
        results_lib = load_results_lib(self.config.analysis_dir)
        raw = sidecar.get("result")
        if raw not in (0, 1, 2) or "trainer1" not in sidecar or "trainer2" not in sidecar:
            return None
        normalized = {0: results_lib.DRAW, 1: results_lib.WIN, 2: results_lib.LOSS}[raw]
        return {
            "trainer1": sidecar["trainer1"],
            "trainer2": sidecar["trainer2"],
            "result": normalized,
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

    def _match_replay_status(self, match):
        """"none" | "draw" | "decisive" for this match's *current pending*
        attempt (match.current_attempt_idx) -- not just "whatever's newest
        on disk", so an attempt already applied into match.attempts is never
        re-surfaced as pending again. A missing/unreadable sidecar is
        treated the same as no replay at all, rather than surfacing a
        replay we can't identify the outcome of."""
        dat_path = self._find_existing_replay(match)
        if dat_path is None:
            return "none"
        sidecar = self._read_sidecar_for_replay(dat_path)
        row = self._sidecar_as_row(sidecar) if sidecar else None
        if row is None:
            return "none"
        results_lib = load_results_lib(self.config.analysis_dir)
        return "decisive" if row["result"] in (results_lib.WIN, results_lib.LOSS) else "draw"

    # -- sprites / curse marker --------------------------------------------

    def _card_data(self):
        if self._card_data_cache is None:
            results_lib = load_results_lib(self.config.analysis_dir)
            try:
                self._card_data_cache = results_lib.load_card_data()
            except OSError:
                self._card_data_cache = {}
        return self._card_data_cache

    def _naming(self):
        if self._naming_cache is None:
            self._naming_cache = load_trainer_naming(self.config.analysis_dir)
        return self._naming_cache

    def _is_cursed(self, label):
        if not label:
            return False
        row = self._card_data().get(label)
        if row is None:
            return False
        return self._naming().is_curse_variant(row, self._card_data())

    def _device_pixel_ratio(self):
        screen = QGuiApplication.primaryScreen()
        return screen.devicePixelRatio() if screen else 1.0

    def _scaled_pixel_art(self, raw, logical_size):
        """Nearest-neighbor downscale to logical_size x logical_size,
        rendered at the screen's actual device pixel ratio and tagged with
        that ratio via setDevicePixelRatio -- without this, a pixmap with
        no DPR set gets silently re-stretched a *second* time by Qt when
        painted on a HiDPI screen (to match the screen's real physical
        pixel density), and that implicit second pass isn't
        nearest-neighbor. That's what was making sprites still look
        soft/crunchy despite the source scale factor itself being a clean
        integer ratio (160/40 for trainer sprites, 48/16 for the curse
        badge) -- the corruption was happening one step later, at paint
        time, not in this scaling step."""
        dpr = self._device_pixel_ratio()
        physical = max(1, round(logical_size * dpr))
        scaled = raw.scaled(physical, physical, Qt.KeepAspectRatio, Qt.FastTransformation)
        scaled.setDevicePixelRatio(dpr)
        return scaled

    def _curse_badge(self):
        """Tarot Amulet badge (Graphics/Items/TAROTAMULET_ACTIVE.png), the
        same icon trainer_cards.py/the website use to mark a curse-rolled
        trainer -- loaded once and composited onto a cursed trainer's
        sprite corner (see _sprite_pixmap), instead of resolve_display_name's
        text-only "(Cursed)" suffix (see CURSED_TEXT_SUFFIX)."""
        if not self._curse_badge_loaded:
            self._curse_badge_loaded = True
            path = os.path.join(self.config.vendor_dir, "Graphics", "Items", "TAROTAMULET_ACTIVE.png")
            if os.path.isfile(path):
                raw = QPixmap(path)
                if not raw.isNull():
                    self._curse_badge_pixmap = self._scaled_pixel_art(raw, CURSE_BADGE_SIZE)
        return self._curse_badge_pixmap

    def _sprite_pixmap(self, label):
        """Trainer portrait sprite (Graphics/Trainers/{trainer_type}.png,
        the same one trainer_cards.py uses), scaled down for a bracket
        slot, with the curse badge composited onto its bottom-right corner
        for a curse-rolled trainer. Cached per label since the same trainer
        recurs across many matches/rounds. None if the label has no
        card-data row yet or the sprite file is missing (e.g. a hand-typed
        label)."""
        if not label:
            return None
        if label not in self._sprite_cache:
            pixmap = None
            row = self._card_data().get(label)
            trainer_type = row.get("trainer_type") if row else None
            if trainer_type:
                path = os.path.join(self.config.vendor_dir, "Graphics", "Trainers", f"{trainer_type}.png")
                if os.path.isfile(path):
                    raw = QPixmap(path)
                    if not raw.isNull():
                        pixmap = self._scaled_pixel_art(raw, SPRITE_SIZE)
            if pixmap is not None and self._is_cursed(label):
                badge = self._curse_badge()
                if badge is not None:
                    dpr = pixmap.devicePixelRatio()
                    composed = QPixmap(pixmap.size())
                    composed.setDevicePixelRatio(dpr)
                    composed.fill(Qt.transparent)
                    painter = QPainter(composed)
                    painter.drawPixmap(0, 0, pixmap)
                    # Positions are in the painter's logical coordinate
                    # space (the composed pixmap's tagged DPR), so the
                    # known logical sizes (not pixmap.width()/height(),
                    # which are physical pixel counts) are what to subtract.
                    painter.drawPixmap(SPRITE_SIZE - CURSE_BADGE_SIZE, SPRITE_SIZE - CURSE_BADGE_SIZE, badge)
                    painter.end()
                    pixmap = composed
            self._sprite_cache[label] = pixmap
        return self._sprite_cache[label]

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
        status_label = QLabel(f"{max_score_digit}-{max_score_digit} — Replay ready")
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
        pixmap = self._sprite_pixmap(label)
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
            status_label.setText(f"Winner ({match.wins_a}-{match.wins_b})")
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
        # one) is just as skippable as an RR result.
        replay_state = self._match_replay_status(match)  # "none" | "draw" | "decisive"
        bracket_lib = self._ensure_bracket_lib()
        rr_available = (
            match.current_attempt_idx == 0
            and bracket_lib.lookup_result(self.results_index, match.label_a, match.label_b) is not None
        )
        can_skip = rr_available or replay_state == "decisive"

        # Score prefix only appears once the series is actually underway --
        # the common instant-Skip case (and any best-of-1 bracket) looks
        # exactly like it always has.
        score_prefix = f"{match.wins_a}-{match.wins_b} — " if (match.wins_a or match.wins_b) else ""

        if replay_state == "draw":
            status_label.setText(f"{score_prefix}Draw, rematch!")
        elif replay_state == "decisive":
            status_label.setText(f"{score_prefix}Replay ready")
        else:
            status_label.setText(f"{score_prefix}Ready" if can_skip else f"{score_prefix}Needs generation")

        if can_skip:
            skip_button = QPushButton("Skip")
            skip_button.clicked.connect(lambda: self._on_skip_clicked(match))
            footer.addWidget(skip_button)

        if replay_state == "decisive":
            watch_button = QPushButton("Watch")
            watch_button.clicked.connect(lambda: self._on_watch_clicked(match))
            footer.addWidget(watch_button)
        else:
            needs_generation = True
            generate_button = QPushButton("Generate")
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

    def _known_pending_row(self, match):
        """The row describing match.current_attempt_idx's outcome, if
        already known -- RR (attempt 0 only; RR has just one battle per
        pairing) or a local replay sidecar for that exact pending attempt.
        None if nothing is known yet, meaning a fresh Generate is needed."""
        bracket_lib = self._ensure_bracket_lib()
        if match.current_attempt_idx == 0:
            row = bracket_lib.lookup_result(self.results_index, match.label_a, match.label_b)
            if row is not None:
                return row
        dat_path = self._find_existing_replay(match)
        if dat_path is None:
            return None
        sidecar = self._read_sidecar_for_replay(dat_path)
        return self._sidecar_as_row(sidecar) if sidecar else None

    def _apply_known_pending_attempt(self, match):
        """If match's current pending attempt is already known (RR or a
        local sidecar, decisive or drawn), records it via
        bracket_lib.record_attempt -- advancing the bracket tree too if that
        decides the match -- and returns True. Otherwise leaves the match
        untouched and returns False. Used by both an explicit Skip and
        "Reveal remaining"'s cascade; Skip/Watch are the only things that
        ever reveal a winner, but once something's already known, applying
        it isn't itself a new reveal."""
        row = self._known_pending_row(match)
        if row is None:
            return False
        bracket_lib = self._ensure_bracket_lib()
        results_lib = load_results_lib(self.config.analysis_dir)
        if row["result"] == results_lib.DRAW:
            bracket_lib.record_attempt(match, None, None, row.get("seed"))
            return True
        winner_label, winner_rank = self._winner_from_row(match, row)
        resolved = bracket_lib.record_attempt(match, winner_label, winner_rank, row.get("seed"))
        if resolved:
            bracket_lib.advance_winner(self.rounds, match.round_idx, match.match_idx, winner_label, winner_rank)
        return True

    def _apply_pending_draw(self, match):
        """If match's current pending attempt is an already-known *draw*
        (from a local replay sidecar), records it so the attempt counter and
        seed chain move on to the retry. Never auto-applies a decisive
        result (RR or otherwise) -- that's Skip's job alone, since Generate
        can be clicked even when RR/a decisive replay is already available
        (e.g. the user wants to actually watch it), and that click must not
        silently resolve the match instead."""
        if self._match_replay_status(match) != "draw":
            return
        row = self._known_pending_row(match)
        if row is None:
            return
        bracket_lib = self._ensure_bracket_lib()
        bracket_lib.record_attempt(match, None, None, row.get("seed"))

    def _on_skip_clicked(self, match):
        if not self._apply_known_pending_attempt(match):
            QMessageBox.information(
                self, "No result yet", "No decisive round-robin result available for this pairing yet -- use Generate."
            )
            return
        self._render()

    def _on_watch_clicked(self, match):
        # Only ever offered when _match_replay_status found a decisive local
        # replay (see _build_match_row), so this just hands off -- winning
        # doesn't get revealed here. It's revealed by handle_replay_finished,
        # once the replay has actually finished playing, not the moment it's
        # opened.
        existing = self._find_existing_replay(match)
        if existing is None:
            QMessageBox.warning(self, "Replay not found", "No replay file was found for this match -- use Generate first.")
            return
        self.watch_requested.emit(existing, {})

    def handle_replay_finished(self, dat_path, result):
        """Connected to WatchTab.replay_finished. A crashed/cancelled Watch
        (ok=False) never applies. A genuine draw (result 0) now does apply,
        same as a decisive result -- a draw is itself a played attempt that
        must be recorded to keep the next attempt's seed chain and slug
        numbering correct, unlike the old single-game bracket where a draw
        never needed any bookkeeping."""
        if not result.get("ok") or result.get("result") not in (0, 1, 2):
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
        # Guards against a stale/duplicate signal for an attempt already
        # applied -- the finished file must be exactly the current pending
        # attempt, not an earlier one.
        if name != self._match_slug_for_attempt(match, match.current_attempt_idx):
            return

        if not self._apply_known_pending_attempt(match):
            return
        self._render()

    def _on_generate_clicked(self, match):
        # Hands off to the Generate tab instead of running anything here, so
        # the user can apply Generate's own customization (backdrop, debug
        # mode, etc.). The output name stays bracket-recognizable so the
        # sidecar Generate writes gets picked up as a cached result the next
        # time this tab is refreshed. If the current pending attempt is
        # already a known draw, silently consume it first so this Generate
        # produces the *next* attempt rather than re-numbering the same one.
        self._apply_pending_draw(match)
        attempt = match.current_attempt_idx
        seed = self._seed_for_generate(match)
        slug = self._match_slug_for_attempt(match, attempt)
        trainer1_label, trainer2_label = self._perspective_order(match)
        self.generate_requested.emit({
            "trainer1": trainer1_label,
            "trainer2": trainer2_label,
            "seed": seed,
            "format": self.fmt,
            "output_name": slug,
        })
        self._render()

    def _seed_for_generate(self, match):
        """Seed for match.current_attempt_idx's fresh generation. The very
        first attempt reuses a known RR seed if this pairing already has a
        decisive RR result (so Generate reproduces the exact historical
        battle); every later attempt chains off the actual previous
        attempt's seed via next_attempt_seed, regardless of whether that
        previous attempt was a draw or a decisive-but-not-final game."""
        bracket_lib = self._ensure_bracket_lib()
        if not match.attempts:
            row = bracket_lib.lookup_result(self.results_index, match.label_a, match.label_b)
            if row is not None:
                return row["seed"]
            return bracket_lib.derive_fresh_seed(self.fmt, match.round_idx, match.match_idx, match.label_a, match.label_b)
        return bracket_lib.next_attempt_seed(match.attempts[-1]["seed"])

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

    def _on_refresh_clicked(self):
        # Picks up sidecars written by a hand-off to the Generate tab (which
        # doesn't report back to this tab directly) or by anything else
        # dropped into replay_metadata_dir since this format was last loaded.
        self._load_results_index()
        self._render()

    def handle_generation_finished(self, dat_path, result):
        """Connected to GenerateTab.generation_finished, so a bracket-handed-off
        Generate that finishes while the user has since tabbed away (or is
        generating several matches in a row) still updates this tab's
        buttons/status without waiting on a manual Refresh. Doesn't reveal
        any winner itself -- that's still gated behind Skip/watching, same as
        a manual Refresh would leave it."""
        bracket_lib = self._ensure_bracket_lib()
        name = os.path.splitext(os.path.basename(dat_path))[0]
        parsed = bracket_lib.parse_bracket_slug(name)
        if parsed is None or parsed[0] != self.fmt:
            return
        self._on_refresh_clicked()

    # -- replay/seed bookkeeping ----------------------------------------------

    def _match_slug_for_attempt(self, match, attempt):
        bracket_lib = self._ensure_bracket_lib()
        return bracket_lib.bracket_replay_slug(
            self.fmt, match.round_idx, match.match_idx, match.rank_a, match.label_a, match.rank_b, match.label_b,
            attempt=attempt,
        )

    def _find_existing_replay(self, match):
        """.dat path for match.current_attempt_idx specifically -- not just
        "whatever's newest on disk" -- so an attempt already applied into
        match.attempts is never re-surfaced as pending again."""
        slug = self._match_slug_for_attempt(match, match.current_attempt_idx)
        path = os.path.join(self.config.replay_dir, slug + ".dat")
        return path if os.path.isfile(path) else None

    def _perspective_order(self, match):
        """(trainer1_label, trainer2_label) for the actual battle env, with
        the underdog (numerically higher/worse rank) as trainer1 -- the
        engine's "player" side -- and the favorite as trainer2. Side-swapping
        doesn't affect the simulated battle or its outcome (confirmed in
        replay_env.build_env's own docs), only which side the spectator
        watches from, so this is presentation-only and safe to apply even
        when reproducing an exact historical seed. Display text elsewhere
        always lists by rank (favorite first) regardless of this."""
        if match.rank_a > match.rank_b:
            return match.label_a, match.label_b
        return match.label_b, match.label_a
