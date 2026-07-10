import json
import os

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import asset_names, config as config_module, format_selector, game_assets, replay_env, replay_runner, ui_settings
from app.replay_runner import ReplayRunner
from app.results_source import load_results_lib
from app.sprite_loader import SpriteLoader
from app.trainer_names import TrainerNameResolver, load_trainer_naming
from app.trainer_picker_dialog import TrainerPickerDialog

# Bigger than the bracket's small match-card sprites (see bracket_tab.py) --
# this tab only ever shows two at a time, side by side, so there's room to
# go larger. 48 is native curse-badge resolution exactly (80 * 0.6), a clean
# 1x scale rather than an arbitrary resize.
SPRITE_SIZE = 80
CURSE_BADGE_SIZE = 48


class GenerateTab(QWidget):
    """Always-headless replay generation. Watching the resulting .dat is
    handed off to the Watch tab (see watch_requested), built on the
    engine's playRecordedBattle rather than live in-process rendering."""

    watch_requested = Signal(str, dict)
    # (dat_path, result) whenever a generation actually produces a replay --
    # lets a caller (the Bracket tab) notice a match it handed off to this
    # tab got resolved, even if the user tabbed away before it finished.
    generation_finished = Signal(str, dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._names = TrainerNameResolver(config)
        self._trainer_data_cache = None
        self._naming_cache = None
        self._sprites = SpriteLoader(config, self._trainer_data, self._is_cursed)
        self._suppress_winner = False
        self.runner = ReplayRunner(self)
        self.runner.started.connect(self._on_started)
        self.runner.finished.connect(self._on_finished)
        self.runner.heartbeat.connect(self._on_heartbeat)
        self._last_result = None

        layout = QVBoxLayout(self)

        trainer1_form = QFormLayout()
        trainer1_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        trainer2_form = QFormLayout()
        trainer2_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.trainer1_edit = QLineEdit()
        self.trainer1_edit.setPlaceholderText("TYPE:Name or TYPE:Name#version")
        self.trainer1_name_label = QLabel()
        self.trainer1_name_label.setStyleSheet("color: gray;")
        self.trainer1_sprite_label = QLabel()
        self.trainer1_sprite_label.setFixedSize(SPRITE_SIZE, SPRITE_SIZE)
        self.trainer2_edit = QLineEdit()
        self.trainer2_edit.setPlaceholderText("TYPE:Name or TYPE:Name#version")
        self.trainer2_name_label = QLabel()
        self.trainer2_name_label.setStyleSheet("color: gray;")
        self.trainer2_sprite_label = QLabel()
        self.trainer2_sprite_label.setFixedSize(SPRITE_SIZE, SPRITE_SIZE)
        self.seed_edit = QLineEdit()
        self.battle_type_combo = QComboBox()
        for value, label in format_selector.BATTLE_TYPES:
            self.battle_type_combo.addItem(label, value)
        self.curse_variant_combo = QComboBox()
        for value, label in format_selector.CURSE_VARIANTS:
            self.curse_variant_combo.addItem(label, value)
        self.output_name_edit = QLineEdit()
        self.output_name_edit.setPlaceholderText("(optional, auto-generated if blank)")
        self.backdrop_combo = QComboBox()
        default_backdrop_display = asset_names.BACKDROP_NAMES.get("indoor1", "indoor1")
        self.backdrop_combo.addItem(f"(default: {default_backdrop_display})", None)
        for raw, display in game_assets.list_backdrop_environments(config.vendor_dir):
            self.backdrop_combo.addItem(display, raw)
        self.backdrop_time_combo = QComboBox()
        for value, label in game_assets.TIME_VARIANTS:
            self.backdrop_time_combo.addItem(label, value)
        self.debug_check = QCheckBox("Debug mode (shows the engine's console window)")
        self._is_dev_build = config_module.is_dev_build()

        self.trainer1_choose_button = QPushButton("Choose...")
        self.trainer2_choose_button = QPushButton("Choose...")

        trainer1_row = QHBoxLayout()
        trainer1_row.addWidget(self.trainer1_edit, 2)
        trainer1_row.addWidget(self.trainer1_choose_button)
        trainer1_row.addWidget(self.trainer1_name_label, 3)
        trainer2_row = QHBoxLayout()
        trainer2_row.addWidget(self.trainer2_edit, 2)
        trainer2_row.addWidget(self.trainer2_choose_button)
        trainer2_row.addWidget(self.trainer2_name_label, 3)
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("Battle type:"))
        format_row.addWidget(self.battle_type_combo, 1)
        format_row.addWidget(QLabel("Curse variant:"))
        format_row.addWidget(self.curse_variant_combo, 1)
        backdrop_row = QHBoxLayout()
        backdrop_row.addWidget(self.backdrop_combo, 2)
        backdrop_row.addWidget(QLabel("Time:"))
        backdrop_row.addWidget(self.backdrop_time_combo, 1)

        trainer1_form.addRow("Trainer 1", trainer1_row)
        trainer2_form.addRow("Trainer 2", trainer2_row)

        # Two single-row forms with a stretch between them, rather than one
        # two-row form -- spreads the rows across the 80px of vertical space
        # the sprites need instead of clumping them together at the top of
        # it.
        trainer_rows = QVBoxLayout()
        trainer_rows.addLayout(trainer1_form)
        trainer_rows.addStretch(1)
        trainer_rows.addLayout(trainer2_form)

        sprites_row = QHBoxLayout()
        sprites_row.addWidget(self.trainer1_sprite_label)
        sprites_row.addWidget(QLabel("vs"))
        sprites_row.addWidget(self.trainer2_sprite_label)

        trainer_section = QHBoxLayout()
        trainer_section.addLayout(trainer_rows, 1)
        trainer_section.addLayout(sprites_row)

        # Without a hard cap, this row has nothing stopping the outer
        # QVBoxLayout from handing it leftover window space on resize (it
        # blows up to 200px+ tall instead of the ~80px the sprites actually
        # need) -- confirmed empirically with a standalone layout script.
        trainer_section_widget = QWidget()
        trainer_section_widget.setLayout(trainer_section)
        trainer_section_widget.setMaximumHeight(SPRITE_SIZE + 16)
        layout.addWidget(trainer_section_widget)

        form.addRow("Seed", self.seed_edit)
        form.addRow("Format", format_row)
        form.addRow("Output name", self.output_name_edit)
        form.addRow("Backdrop", backdrop_row)
        if self._is_dev_build:
            form.addRow("", self.debug_check)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.generate_button = QPushButton("Generate")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.export_button = QPushButton("Export .dat...")
        self.export_button.setEnabled(False)
        self.watch_button = QPushButton("Watch this replay")
        self.watch_button.setEnabled(False)
        buttons.addWidget(self.generate_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.watch_button)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("Status"))
        self.status_view = QPlainTextEdit()
        self.status_view.setReadOnly(True)
        layout.addWidget(self.status_view)

        self.generate_button.clicked.connect(self._on_generate_clicked)
        self.cancel_button.clicked.connect(self.runner.cancel)
        self.export_button.clicked.connect(self._on_export_clicked)
        self.watch_button.clicked.connect(self._on_watch_clicked)
        self.trainer1_edit.textChanged.connect(
            lambda text: self._update_trainer_display(self.trainer1_name_label, self.trainer1_sprite_label, text)
        )
        self.trainer2_edit.textChanged.connect(
            lambda text: self._update_trainer_display(self.trainer2_name_label, self.trainer2_sprite_label, text)
        )
        self.trainer1_choose_button.clicked.connect(lambda: self._on_choose_trainer(self.trainer1_edit))
        self.trainer2_choose_button.clicked.connect(lambda: self._on_choose_trainer(self.trainer2_edit))
        self._update_trainer_display(self.trainer1_name_label, self.trainer1_sprite_label, self.trainer1_edit.text())
        self._update_trainer_display(self.trainer2_name_label, self.trainer2_sprite_label, self.trainer2_edit.text())

        settings = QSettings()
        ui_settings.bind_combo(settings, "generate/battle_type", self.battle_type_combo)
        ui_settings.bind_combo(settings, "generate/curse_variant", self.curse_variant_combo)
        ui_settings.bind_combo(settings, "generate/backdrop", self.backdrop_combo)
        ui_settings.bind_combo(settings, "generate/backdrop_time", self.backdrop_time_combo)
        ui_settings.bind_checkbox(settings, "generate/debug", self.debug_check)

    def _on_choose_trainer(self, target_edit):
        dialog = TrainerPickerDialog(self.config, self)
        if dialog.exec() == QDialog.Accepted:
            target_edit.setText(dialog.selected_label())

    def _update_trainer_display(self, label_widget, sprite_widget, raw_label):
        raw_label = raw_label.strip()
        if not raw_label:
            label_widget.setText("")
            sprite_widget.clear()
            return
        resolved = self._names.display_name(raw_label)
        label_widget.setText(resolved if resolved != raw_label else "(unknown trainer label)")
        pixmap = self._sprites.sprite_pixmap(raw_label, SPRITE_SIZE, CURSE_BADGE_SIZE)
        if pixmap is not None:
            sprite_widget.setPixmap(pixmap)
        else:
            sprite_widget.clear()

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

    def set_match(self, payload):
        self.trainer1_edit.setText(payload.get("trainer1", ""))
        self.trainer2_edit.setText(payload.get("trainer2", ""))
        self.seed_edit.setText(str(payload.get("seed", "")))
        fmt = payload.get("format") or ""
        battle_type, curse_variant = format_selector.parse_format_key(fmt)
        self.battle_type_combo.setCurrentIndex(self.battle_type_combo.findData(battle_type))
        self.curse_variant_combo.setCurrentIndex(self.curse_variant_combo.findData(curse_variant))
        self.output_name_edit.setText(payload.get("output_name", ""))
        self._suppress_winner = payload.get("suppress_winner", False)

    def _on_generate_clicked(self):
        if not self.config.is_valid():
            QMessageBox.warning(
                self,
                "Game not found",
                f"Game.exe wasn't found at {self.config.game_exe_path!r}. "
                "Check the configured vendor/tectonic-content path.",
            )
            return

        try:
            seed = int(self.seed_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid seed", "Seed must be an integer.")
            return

        fmt = format_selector.format_key(self.battle_type_combo.currentData(), self.curse_variant_combo.currentData())
        environment = self.backdrop_combo.currentData()
        backdrop = (
            game_assets.resolve_backdrop(self.config.vendor_dir, environment, self.backdrop_time_combo.currentData())
            if environment
            else None
        )

        try:
            env_vars = replay_env.build_env(
                self.trainer1_edit.text().strip(),
                self.trainer2_edit.text().strip(),
                seed,
                battle_format=fmt,
                output_name=self.output_name_edit.text().strip() or None,
                backdrop=backdrop,
            )
        except replay_env.InvalidTrainerLabel as exc:
            QMessageBox.warning(self, "Invalid trainer label", str(exc))
            return

        estimated_rounds = self._estimate_rounds(
            self.trainer1_edit.text().strip(), self.trainer2_edit.text().strip(), seed, fmt
        )
        if not replay_runner.confirm_long_replay(self, estimated_rounds, "generate", estimated=True):
            return

        self._last_result = None
        self._last_request = {
            "trainer1": self.trainer1_edit.text().strip(),
            "trainer2": self.trainer2_edit.text().strip(),
            "seed": seed,
            "format": fmt,
        }
        self.export_button.setEnabled(False)
        self.watch_button.setEnabled(False)
        debug = self._is_dev_build and self.debug_check.isChecked()
        self.status_view.setPlainText("Launching Game.exe (headless)...")
        self.runner.start(
            self.config.vendor_dir,
            env_vars,
            self.config.timeout_seconds,
            suppress_window=not debug,
            heartbeat_filename=replay_runner.DEFAULT_HEARTBEAT_FILE_RELATIVE,
            extra_args=["debug"] if debug else None,
        )

    def _estimate_rounds(self, t1_label, t2_label, seed, fmt):
        """A round-count guess for a not-yet-run matchup, drawn from
        existing round-robin results for the same pairing -- exact if this
        seed was already played, otherwise any other known result for the
        same two trainers (best guess available, not exact). None if
        there's simply no prior data for this pairing."""
        if not t1_label or not t2_label:
            return None
        try:
            results_lib = load_results_lib(self.config.analysis_dir)
            rows = results_lib.load_results(fmt, results_dir=self.config.results_dir)
        except OSError:
            return None
        from app import bracket_lib

        index = bracket_lib.build_results_index(rows)
        row = bracket_lib.find_row_for_seed(index, t1_label, t2_label, seed)
        if row is None:
            row = bracket_lib.pick_default_row(index, t1_label, t2_label)
        return row.get("rounds") if row else None

    def _on_started(self):
        self.generate_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

    def _on_heartbeat(self, data):
        turn = data.get("turn")
        updated_at = data.get("updated_at")
        if turn is None:
            return
        text = f"Battle in progress -- turn {turn + 1}"
        if updated_at:
            text += f" (as of {updated_at})"
        self.status_view.setPlainText(text)

    def _on_finished(self, result):
        self.generate_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self._last_result = result
        t1_name = self._names.display_name(self._last_request["trainer1"])
        t2_name = self._names.display_name(self._last_request["trainer2"])
        self.status_view.setPlainText(
            replay_runner.describe_result(result, t1_name, t2_name, hide_outcome=self._suppress_winner)
        )
        can_watch_or_export = bool(result.get("ok")) and bool(result.get("saved_to"))
        self.export_button.setEnabled(can_watch_or_export)
        self.watch_button.setEnabled(can_watch_or_export)
        if can_watch_or_export:
            self._write_sidecar()
            src = os.path.normpath(os.path.join(self.config.vendor_dir, result["saved_to"]))
            self.generation_finished.emit(src, result)

    def _write_sidecar(self):
        """Writes sidecar metadata for the freshly generated .dat into
        config.replay_metadata_dir (not just on Export), so the Watch tab's
        trainer columns survive a refresh even for a replay that was watched
        straight from Generate and never exported."""
        name = os.path.splitext(os.path.basename(self._last_result["saved_to"]))[0]
        metadata_dir = self.config.replay_metadata_dir
        try:
            os.makedirs(metadata_dir, exist_ok=True)
            with open(os.path.join(metadata_dir, name + ".json"), "w", encoding="utf-8") as f:
                json.dump(self._sidecar_metadata(), f, indent=2)
        except OSError:
            pass

    def _sidecar_metadata(self):
        return {
            **self._last_request,
            "result": self._last_result.get("result"),
            "rounds": self._last_result.get("rounds"),
        }

    def _on_export_clicked(self):
        if not self._last_result or not self._last_result.get("saved_to"):
            return
        src = os.path.normpath(os.path.join(self.config.vendor_dir, self._last_result["saved_to"]))
        default_name = os.path.basename(src)
        dest, _ = QFileDialog.getSaveFileName(self, "Export replay", default_name, "Replay files (*.dat)")
        if not dest:
            return
        try:
            with open(src, "rb") as f_in, open(dest, "wb") as f_out:
                f_out.write(f_in.read())
            with open(dest + ".json", "w", encoding="utf-8") as f:
                json.dump(self._sidecar_metadata(), f, indent=2)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def _on_watch_clicked(self):
        if not self._last_result or not self._last_result.get("saved_to"):
            return
        src = os.path.normpath(os.path.join(self.config.vendor_dir, self._last_result["saved_to"]))
        self.watch_requested.emit(src, self._sidecar_metadata())
