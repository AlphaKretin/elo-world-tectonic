"""Bracket tab: a hand-curated top-16 single-elimination bracket, resolved
match-by-match either instantly (looked up from existing round-robin results
or a previously-generated bracket sidecar) or by generating a fresh battle
via the Generate tab, so a curated bracket can be watched progressively
round-by-round rather than dumped all at once. See analysis/bracket_lib.py
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

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import bracket_seeds, format_selector, ui_settings
from app.results_source import load_results_lib
from app.trainer_names import TrainerNameResolver

FILTER_CHOICES = [(None, "(none)"), ("cursed_excluded", "Cursed-excluded"), ("level70_only", "Level 70 only")]


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
        format_row.addWidget(QLabel("Battle type:"))
        format_row.addWidget(self.battle_type_combo, 1)
        format_row.addWidget(QLabel("Curse variant:"))
        format_row.addWidget(self.curse_variant_combo, 1)
        format_row.addWidget(QLabel("Filter:"))
        format_row.addWidget(self.filter_combo, 1)
        self.reveal_button = QPushButton("Reveal remaining")
        format_row.addWidget(self.reveal_button)
        self.refresh_button = QPushButton("Refresh")
        format_row.addWidget(self.refresh_button)
        layout.addLayout(format_row)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.rounds_container = QWidget()
        self.rounds_layout = QVBoxLayout(self.rounds_container)
        self.rounds_layout.addStretch(1)
        self.scroll_area.setWidget(self.rounds_container)
        layout.addWidget(self.scroll_area)

        self.battle_type_combo.currentIndexChanged.connect(self._on_format_changed)
        self.curse_variant_combo.currentIndexChanged.connect(self._on_format_changed)
        self.filter_combo.currentIndexChanged.connect(self._on_format_changed)
        self.reveal_button.clicked.connect(self._on_reveal_remaining_clicked)
        self.refresh_button.clicked.connect(self._on_refresh_clicked)

        settings = QSettings()
        ui_settings.bind_combo(settings, "bracket/battle_type", self.battle_type_combo)
        ui_settings.bind_combo(settings, "bracket/curse_variant", self.curse_variant_combo)
        ui_settings.bind_combo(settings, "bracket/filter", self.filter_combo)

        self._on_format_changed()

    # -- setup / teardown --------------------------------------------------

    def _ensure_bracket_lib(self):
        if self._bracket_lib is None:
            load_results_lib(self.config.analysis_dir)  # side effect: puts analysis_dir on sys.path
            import bracket_lib

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
            self._clear_rounds_ui()
            self.reveal_button.setEnabled(False)
            return

        bracket_lib = self._ensure_bracket_lib()
        try:
            self.rounds = bracket_lib.build_bracket_tree(labels)
        except ValueError as exc:
            self.rounds = None
            self.status_label.setText(str(exc))
            self._clear_rounds_ui()
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
        """"none" | "draw" | "decisive" for this match's latest locally
        generated attempt (not the RR/lookup index -- this is specifically
        about whether there's a local .dat safe to offer via Watch). A
        missing/unreadable sidecar is treated the same as no replay at all,
        rather than surfacing a replay we can't identify the outcome of."""
        dat_path = self._find_existing_replay(match)
        if dat_path is None:
            return "none"
        sidecar = self._read_sidecar_for_replay(dat_path)
        row = self._sidecar_as_row(sidecar) if sidecar else None
        if row is None:
            return "none"
        results_lib = load_results_lib(self.config.analysis_dir)
        return "decisive" if row["result"] in (results_lib.WIN, results_lib.LOSS) else "draw"

    # -- rendering -----------------------------------------------------------

    def _clear_rounds_ui(self):
        while self.rounds_layout.count() > 1:
            item = self.rounds_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _render(self):
        self._clear_rounds_ui()
        if not self.rounds:
            return
        bracket_lib = self._ensure_bracket_lib()

        any_generation_needed = False
        for round_idx, matches in enumerate(self.rounds):
            box = QGroupBox(bracket_lib.ROUND_NAMES[round_idx] if round_idx < len(bracket_lib.ROUND_NAMES) else f"Round {round_idx + 1}")
            box_layout = QVBoxLayout(box)
            for match in matches:
                row_widget, needs_generation = self._build_match_row(match)
                box_layout.addWidget(row_widget)
                any_generation_needed = any_generation_needed or needs_generation
            self.rounds_layout.insertWidget(self.rounds_layout.count() - 1, box)

        self._any_generation_needed = any_generation_needed

    def _build_match_row(self, match):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        name_a = self._entrant_text(match.rank_a, match.label_a)
        name_b = self._entrant_text(match.rank_b, match.label_b)
        row_layout.addWidget(QLabel(name_a), 2)
        row_layout.addWidget(QLabel("vs"))
        row_layout.addWidget(QLabel(name_b), 2)

        status_label = QLabel()
        needs_generation = False

        if not (match.ready or match.resolved):
            status_label.setText("Waiting")
            row_layout.addWidget(status_label, 1)
            return row, needs_generation

        # The winner is only ever revealed by an explicit Skip, or once a
        # watched replay actually finishes (see _on_skip_clicked /
        # handle_replay_finished) -- never just because a replay happens to
        # exist -- so generating one in the background never spoils a match
        # before the user actually looks at it.
        replay_state = self._match_replay_status(match)  # "none" | "draw" | "decisive"
        can_skip = False
        if not match.resolved:
            bracket_lib = self._ensure_bracket_lib()
            can_skip = bracket_lib.lookup_result(self.results_index, match.label_a, match.label_b) is not None

        if match.resolved:
            status_label.setText(f"Winner: {self._names.display_name(match.winner_label)}")
        elif replay_state == "draw":
            status_label.setText("Draw -- rematch!")
        elif replay_state == "decisive":
            status_label.setText("Replay ready")
        else:
            status_label.setText("Ready" if can_skip else "Needs generation")

        if can_skip:
            skip_button = QPushButton("Skip")
            skip_button.clicked.connect(lambda: self._on_skip_clicked(match))
            row_layout.addWidget(skip_button)

        if replay_state == "decisive":
            watch_button = QPushButton("Watch")
            watch_button.clicked.connect(lambda: self._on_watch_clicked(match))
            row_layout.addWidget(watch_button)
        else:
            needs_generation = True
            generate_button = QPushButton("Generate")
            generate_button.clicked.connect(lambda: self._on_generate_clicked(match))
            row_layout.addWidget(generate_button)

        row_layout.addWidget(status_label, 1)
        return row, needs_generation

    def _entrant_text(self, rank, label):
        if label is None:
            return "TBD"
        return f"#{rank} {self._names.display_name(label)}"

    # -- match resolution ----------------------------------------------------

    def _advance_from_row(self, match, row):
        bracket_lib = self._ensure_bracket_lib()
        results_lib = load_results_lib(self.config.analysis_dir)
        if row["trainer1"] == match.label_a:
            winner_is_a = row["result"] == results_lib.WIN
        else:
            winner_is_a = row["result"] == results_lib.LOSS
        winner_label = match.label_a if winner_is_a else match.label_b
        winner_rank = match.rank_a if winner_is_a else match.rank_b
        bracket_lib.advance_winner(self.rounds, match.round_idx, match.match_idx, winner_label, winner_rank)
        # Kept so a later Watch/Generate click can still reproduce this
        # match's replay even though resolving it here didn't need one.
        match.resolved_seed = row.get("seed")

    def _on_skip_clicked(self, match):
        bracket_lib = self._ensure_bracket_lib()
        row = bracket_lib.lookup_result(self.results_index, match.label_a, match.label_b)
        if row is None:
            QMessageBox.information(
                self, "No result yet", "No decisive round-robin result available for this pairing yet -- use Generate."
            )
            return
        self._advance_from_row(match, row)
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
        """Connected to WatchTab.replay_finished. A drawn/missing outcome
        (result["result"] == 0, or ok=False for a crash/timeout/viewer
        cancel) is never treated as resolving the match -- _match_replay_status
        never offers Watch for a replay whose own sidecar says draw, so a
        genuinely decisive bracket replay can only ever report 0 here because
        the user cancelled it in-game partway through."""
        if not result.get("ok") or result.get("result") not in (1, 2):
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

        sidecar = self._read_sidecar_for_replay(dat_path)
        row = self._sidecar_as_row(sidecar) if sidecar else None
        if row is None:
            return
        self._advance_from_row(match, row)
        self._render()

    def _on_generate_clicked(self, match):
        # Hands off to the Generate tab instead of running anything here, so
        # the user can apply Generate's own customization (backdrop, debug
        # mode, etc.). The output name stays bracket-recognizable so the
        # sidecar Generate writes gets picked up as a cached result the next
        # time this tab is refreshed.
        bracket_lib = self._ensure_bracket_lib()
        attempt = self._count_attempts(match)
        seed = self._seed_for_generate(match, attempt)
        slug = bracket_lib.bracket_replay_slug(
            self.fmt, match.round_idx, match.match_idx, match.rank_a, match.label_a, match.rank_b, match.label_b, attempt=attempt
        )
        trainer1_label, trainer2_label = self._perspective_order(match)
        self.generate_requested.emit({
            "trainer1": trainer1_label,
            "trainer2": trainer2_label,
            "seed": seed,
            "format": self.fmt,
            "output_name": slug,
        })

    def _seed_for_generate(self, match, attempt):
        """Reuses a known decisive seed (from an already-resolved match, or
        an RR/sidecar row this pairing already has) so Generate reproduces
        the exact historical battle whenever one is known, falling back to a
        freshly-derived or drawn-retry seed only when nothing is known yet."""
        if match.resolved and match.resolved_seed is not None:
            return match.resolved_seed
        if attempt == 0:
            bracket_lib = self._ensure_bracket_lib()
            row = bracket_lib.lookup_result(self.results_index, match.label_a, match.label_b)
            if row is not None:
                return row["seed"]
        return self._seed_for_attempt(match, attempt)

    def _on_reveal_remaining_clicked(self):
        bracket_lib = self._ensure_bracket_lib()
        changed = True
        while changed:
            changed = False
            for matches in self.rounds:
                for match in matches:
                    if match.resolved or not match.ready:
                        continue
                    row = bracket_lib.lookup_result(self.results_index, match.label_a, match.label_b)
                    if row is not None:
                        self._advance_from_row(match, row)
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

    def _match_slug_prefix(self, match):
        bracket_lib = self._ensure_bracket_lib()
        return bracket_lib.bracket_replay_slug(
            self.fmt, match.round_idx, match.match_idx, match.rank_a, match.label_a, match.rank_b, match.label_b
        )

    def _existing_attempt_paths(self, match):
        prefix = self._match_slug_prefix(match)
        pattern = os.path.join(self.config.replay_dir, prefix + "*.dat")
        return sorted(glob.glob(pattern))

    def _count_attempts(self, match):
        return len(self._existing_attempt_paths(match))

    def _find_existing_replay(self, match):
        paths = self._existing_attempt_paths(match)
        return paths[-1] if paths else None

    def _seed_for_attempt(self, match, attempt):
        bracket_lib = self._ensure_bracket_lib()
        if attempt == 0:
            return bracket_lib.derive_fresh_seed(self.fmt, match.round_idx, match.match_idx, match.label_a, match.label_b)
        previous_seed = self._last_used_seed(match, attempt - 1)
        return bracket_lib.next_retry_seed(previous_seed)

    def _last_used_seed(self, match, attempt):
        prefix = self._match_slug_prefix(match)
        slug = prefix if attempt == 0 else f"{prefix}_attempt{attempt}"
        sidecar_path = os.path.join(self.config.replay_metadata_dir, slug + ".json")
        try:
            with open(sidecar_path, "r", encoding="utf-8") as f:
                return json.load(f).get("seed")
        except (OSError, json.JSONDecodeError):
            return 0

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
