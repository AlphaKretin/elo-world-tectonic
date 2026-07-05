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

from app import game_assets, replay_env
from app.replay_runner import ReplayRunner


class GenerateTab(QWidget):
    """Always-headless replay generation. Watching the resulting .dat is
    handed off to the Watch tab (see watch_requested), built on the
    engine's playRecordedBattle rather than live in-process rendering."""

    watch_requested = Signal(str, dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.runner = ReplayRunner(self)
        self.runner.started.connect(self._on_started)
        self.runner.finished.connect(self._on_finished)
        self._last_result = None

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.trainer1_edit = QLineEdit()
        self.trainer1_edit.setPlaceholderText("TYPE:Name or TYPE:Name#version")
        self.trainer2_edit = QLineEdit()
        self.trainer2_edit.setPlaceholderText("TYPE:Name or TYPE:Name#version")
        self.seed_edit = QLineEdit()
        self.format_combo = QComboBox()
        self.format_combo.addItems(["singles", "doubles"])
        self.output_name_edit = QLineEdit()
        self.output_name_edit.setPlaceholderText("(optional, auto-generated if blank)")
        self.backdrop_combo = QComboBox()
        self.backdrop_combo.addItem("(default: indoor1)", None)
        for name in game_assets.list_backdrops(config.vendor_dir):
            self.backdrop_combo.addItem(name, name)
        self.swap_sides_button = QPushButton("⇄ Swap trainers")

        trainer1_row = QHBoxLayout()
        trainer1_row.addWidget(self.trainer1_edit)
        trainer1_row.addWidget(self.swap_sides_button)

        form.addRow("Trainer 1", trainer1_row)
        form.addRow("Trainer 2", self.trainer2_edit)
        form.addRow("Seed", self.seed_edit)
        form.addRow("Format", self.format_combo)
        form.addRow("Output name", self.output_name_edit)
        form.addRow("Backdrop", self.backdrop_combo)
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

    def set_match(self, payload):
        self.trainer1_edit.setText(payload.get("trainer1", ""))
        self.trainer2_edit.setText(payload.get("trainer2", ""))
        self.seed_edit.setText(str(payload.get("seed", "")))
        fmt = payload.get("format") or ""
        index = self.format_combo.findText("doubles" if "double" in fmt else "singles")
        if index >= 0:
            self.format_combo.setCurrentIndex(index)

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

        try:
            env_vars = replay_env.build_env(
                self.trainer1_edit.text().strip(),
                self.trainer2_edit.text().strip(),
                seed,
                battle_format=self.format_combo.currentText(),
                output_name=self.output_name_edit.text().strip() or None,
                backdrop=self.backdrop_combo.currentData(),
            )
        except replay_env.InvalidTrainerLabel as exc:
            QMessageBox.warning(self, "Invalid trainer label", str(exc))
            return

        self._last_result = None
        self._last_request = {
            "trainer1": self.trainer1_edit.text().strip(),
            "trainer2": self.trainer2_edit.text().strip(),
            "seed": seed,
            "format": self.format_combo.currentText(),
        }
        self.export_button.setEnabled(False)
        self.watch_button.setEnabled(False)
        self.status_view.setPlainText("Launching Game.exe (headless)...")
        self.runner.start(self.config.vendor_dir, env_vars, self.config.timeout_seconds)

    def _on_started(self):
        self.generate_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

    def _on_finished(self, result):
        self.generate_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self._last_result = result
        self.status_view.setPlainText(json.dumps(result, indent=2))
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
