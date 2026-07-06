import json
import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
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

from app import asset_names, format_selector, game_assets, replay_env, replay_runner
from app.replay_runner import ReplayRunner
from app.trainer_names import TrainerNameResolver


class GenerateTab(QWidget):
    """Always-headless replay generation. Watching the resulting .dat is
    handed off to the Watch tab (see watch_requested), built on the
    engine's playRecordedBattle rather than live in-process rendering."""

    watch_requested = Signal(str, dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._names = TrainerNameResolver(config)
        self.runner = ReplayRunner(self)
        self.runner.started.connect(self._on_started)
        self.runner.finished.connect(self._on_finished)
        self.runner.heartbeat.connect(self._on_heartbeat)
        self._last_result = None

        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.trainer1_edit = QLineEdit()
        self.trainer1_edit.setPlaceholderText("TYPE:Name or TYPE:Name#version")
        self.trainer1_name_label = QLabel()
        self.trainer1_name_label.setStyleSheet("color: gray;")
        self.trainer2_edit = QLineEdit()
        self.trainer2_edit.setPlaceholderText("TYPE:Name or TYPE:Name#version")
        self.trainer2_name_label = QLabel()
        self.trainer2_name_label.setStyleSheet("color: gray;")
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
        self.swap_sides_button = QPushButton("⇄ Swap trainers")

        trainer1_row = QHBoxLayout()
        trainer1_row.addWidget(self.trainer1_edit, 2)
        trainer1_row.addWidget(self.trainer1_name_label, 3)
        trainer2_row = QHBoxLayout()
        trainer2_row.addWidget(self.trainer2_edit, 2)
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

        form.addRow("Trainer 1", trainer1_row)
        form.addRow("Trainer 2", trainer2_row)
        form.addRow("", self.swap_sides_button)
        form.addRow("Seed", self.seed_edit)
        form.addRow("Format", format_row)
        form.addRow("Output name", self.output_name_edit)
        form.addRow("Backdrop", backdrop_row)
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
        self.swap_sides_button.clicked.connect(self._on_swap_sides_clicked)
        self.trainer1_edit.textChanged.connect(lambda text: self._update_name_label(self.trainer1_name_label, text))
        self.trainer2_edit.textChanged.connect(lambda text: self._update_name_label(self.trainer2_name_label, text))
        self._update_name_label(self.trainer1_name_label, self.trainer1_edit.text())
        self._update_name_label(self.trainer2_name_label, self.trainer2_edit.text())

    def _update_name_label(self, label_widget, raw_label):
        raw_label = raw_label.strip()
        if not raw_label:
            label_widget.setText("")
            return
        resolved = self._names.display_name(raw_label)
        label_widget.setText(resolved if resolved != raw_label else "(unknown trainer label)")

    def set_match(self, payload):
        self.trainer1_edit.setText(payload.get("trainer1", ""))
        self.trainer2_edit.setText(payload.get("trainer2", ""))
        self.seed_edit.setText(str(payload.get("seed", "")))
        fmt = payload.get("format") or ""
        battle_type, curse_variant = format_selector.parse_format_key(fmt)
        self.battle_type_combo.setCurrentIndex(self.battle_type_combo.findData(battle_type))
        self.curse_variant_combo.setCurrentIndex(self.curse_variant_combo.findData(curse_variant))

    def _on_swap_sides_clicked(self):
        t1, t2 = self.trainer1_edit.text(), self.trainer2_edit.text()
        self.trainer1_edit.setText(t2)
        self.trainer2_edit.setText(t1)

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

        self._last_result = None
        self._last_request = {
            "trainer1": self.trainer1_edit.text().strip(),
            "trainer2": self.trainer2_edit.text().strip(),
            "seed": seed,
            "format": fmt,
        }
        self.export_button.setEnabled(False)
        self.watch_button.setEnabled(False)
        self.status_view.setPlainText("Launching Game.exe (headless)...")
        self.runner.start(
            self.config.vendor_dir,
            env_vars,
            self.config.timeout_seconds,
            suppress_window=True,
            heartbeat_filename=replay_runner.DEFAULT_HEARTBEAT_FILE_RELATIVE,
        )

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
        self.status_view.setPlainText(replay_runner.describe_result(result, t1_name, t2_name))
        can_watch_or_export = bool(result.get("ok")) and bool(result.get("saved_to"))
        self.export_button.setEnabled(can_watch_or_export)
        self.watch_button.setEnabled(can_watch_or_export)

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
