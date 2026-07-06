import datetime
import json
import os

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import game_assets, replay_env
from app.replay_runner import ReplayRunner
from app.trainer_names import TrainerNameResolver

COLUMNS = ["Name", "Trainer 1", "Trainer 2", "Modified"]
WATCH_RESULT_FILE = os.path.join("Analysis", "watch_result.txt")
STAGING_NAME = "_WatchStaging"

BATTLESCENE_OPTIONS = [("On", 0), ("Fast", 1), ("Off", 2)]
TEXTSPEED_OPTIONS = [("Slow", 0), ("Normal", 1), ("Fast", 2), ("Rapid", 3), ("Instant", 4)]
TRANSITIONS_OPTIONS = [("Standard", 0), ("Fast", 1)]


def _option_index(options, label):
    return next(i for i, (opt_label, _value) in enumerate(options) if opt_label == label)


class WatchTab(QWidget):
    """Watches a .dat from vendor_dir/VSRecorder/ELOReplay/ through the
    engine's own playRecordedBattle, same mechanism as the in-game VS
    Recorder's "Watch battle" menu item. Display-setting overrides are
    applied in-memory only by the engine, never persisted to Options.dat."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._names = TrainerNameResolver(config)
        self.runner = ReplayRunner(self)
        self.runner.started.connect(self._on_started)
        self.runner.finished.connect(self._on_finished)
        self._expected_result = None

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.import_button = QPushButton("Import .dat...")
        top.addWidget(self.refresh_button)
        top.addWidget(self.import_button)
        top.addStretch(1)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)

        form = QFormLayout()
        self.battlescene_combo = QComboBox()
        for label, _value in BATTLESCENE_OPTIONS:
            self.battlescene_combo.addItem(label)
        self.battlescene_combo.setCurrentIndex(_option_index(BATTLESCENE_OPTIONS, "Fast"))
        self.textspeed_combo = QComboBox()
        for label, _value in TEXTSPEED_OPTIONS:
            self.textspeed_combo.addItem(label)
        self.textspeed_combo.setCurrentIndex(_option_index(TEXTSPEED_OPTIONS, "Instant"))
        self.transitions_combo = QComboBox()
        for label, _value in TRANSITIONS_OPTIONS:
            self.transitions_combo.addItem(label)
        self.transitions_combo.setCurrentIndex(_option_index(TRANSITIONS_OPTIONS, "Standard"))
        self.mute_check = QCheckBox("Mute (music/sound effects)")
        self.bgm_combo = QComboBox()
        self.bgm_combo.addItem("(default: derived from opponent)", None)
        for raw, display in game_assets.list_bgm_tracks(config.vendor_dir):
            self.bgm_combo.addItem(display, raw)
        form.addRow("Battle animations", self.battlescene_combo)
        form.addRow("Text speed", self.textspeed_combo)
        form.addRow("Battle transitions", self.transitions_combo)
        form.addRow("", self.mute_check)
        form.addRow("BGM override", self.bgm_combo)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.watch_button = QPushButton("Watch")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        buttons.addWidget(self.watch_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("Status"))
        self.status_view = QPlainTextEdit()
        self.status_view.setReadOnly(True)
        layout.addWidget(self.status_view)

        self.refresh_button.clicked.connect(self.refresh)
        self.import_button.clicked.connect(self._on_import_clicked)
        self.watch_button.clicked.connect(self._on_watch_clicked)
        self.cancel_button.clicked.connect(self.runner.cancel)

        self.refresh()

    def refresh(self):
        self.table.setRowCount(0)
        replay_dir = self.config.replay_dir
        if not os.path.isdir(replay_dir):
            return
        names = sorted(
            f for f in os.listdir(replay_dir) if f.lower().endswith(".dat") and f != f"{STAGING_NAME}.dat"
        )
        self.table.setRowCount(len(names))
        for i, name in enumerate(names):
            full_path = os.path.join(replay_dir, name)
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(full_path)).strftime("%Y-%m-%d %H:%M:%S")
            self.table.setItem(i, 0, QTableWidgetItem(os.path.splitext(name)[0]))
            self._set_trainer_columns(i, *self._sidecar_trainers(full_path))
            self.table.setItem(i, 3, QTableWidgetItem(mtime))

    def _sidecar_trainers(self, full_path):
        """(trainer1, trainer2) raw labels from full_path's ".dat.json"
        sidecar, or ("", "") if there isn't one -- a replay imported/exported
        through the file dialog carries its sidecar alongside it on disk,
        see _on_import_clicked/GenerateTab._on_export_clicked."""
        sidecar_path = full_path + ".json"
        if not os.path.exists(sidecar_path):
            return "", ""
        try:
            with open(sidecar_path, "r", encoding="utf-8") as f:
                sidecar = json.load(f)
        except (OSError, json.JSONDecodeError):
            return "", ""
        return sidecar.get("trainer1", ""), sidecar.get("trainer2", "")

    def _set_trainer_columns(self, row, t1_label, t2_label):
        for col, label in ((1, t1_label), (2, t2_label)):
            item = QTableWidgetItem(self._names.display_name(label) if label else "")
            item.setToolTip(label)
            self.table.setItem(row, col, item)

    def select_replay(self, dat_path, expected_result=None):
        """Called from Generate's "Watch this replay" hand-off. The file is
        already sitting in replay_dir (generation wrote it there), so this
        just selects/highlights its row instead of copying anything -- and
        since a freshly-generated replay has no ".dat.json" sidecar on disk
        yet (only Export writes one), the trainer columns are filled in
        directly from expected_result here rather than through refresh()'s
        own disk-sidecar lookup, which would otherwise leave them blank."""
        self.refresh()
        name = os.path.splitext(os.path.basename(dat_path))[0]
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == name:
                self.table.selectRow(row)
                if expected_result:
                    self._set_trainer_columns(
                        row, expected_result.get("trainer1", ""), expected_result.get("trainer2", "")
                    )
                break
        self._expected_result = expected_result

    def _selected_dat_path(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        name = self.table.item(selected_rows[0].row(), 0).text()
        return os.path.join(self.config.replay_dir, f"{name}.dat")

    def _on_import_clicked(self):
        src, _ = QFileDialog.getOpenFileName(self, "Import replay", "", "Replay files (*.dat)")
        if not src:
            return
        replay_dir = self.config.replay_dir
        os.makedirs(replay_dir, exist_ok=True)
        dest = os.path.join(replay_dir, os.path.basename(src))
        try:
            with open(src, "rb") as f_in, open(dest, "wb") as f_out:
                f_out.write(f_in.read())
            sidecar_src = src + ".json"
            if os.path.exists(sidecar_src):
                with open(sidecar_src, "rb") as f_in, open(dest + ".json", "wb") as f_out:
                    f_out.write(f_in.read())
        except OSError as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.refresh()

    def _on_watch_clicked(self):
        if not self.config.is_valid():
            QMessageBox.warning(
                self,
                "Game not found",
                f"Game.exe wasn't found at {self.config.game_exe_path!r}. "
                "Check the configured vendor/tectonic-content path.",
            )
            return

        dat_path = self._selected_dat_path()
        if not dat_path or not os.path.exists(dat_path):
            QMessageBox.warning(self, "No replay selected", "Select a replay from the table first.")
            return

        replay_dir = self.config.replay_dir
        staging_path = os.path.join(replay_dir, f"{STAGING_NAME}.dat")
        with open(dat_path, "rb") as f_in, open(staging_path, "wb") as f_out:
            f_out.write(f_in.read())

        sidecar_path = dat_path + ".json"
        if os.path.exists(sidecar_path) and self._expected_result is None:
            try:
                with open(sidecar_path, "r", encoding="utf-8") as f:
                    self._expected_result = json.load(f)
            except (OSError, json.JSONDecodeError):
                self._expected_result = None

        mute = self.mute_check.isChecked()
        env_vars = replay_env.build_watch_env(
            STAGING_NAME,
            battlescene=BATTLESCENE_OPTIONS[self.battlescene_combo.currentIndex()][1],
            textspeed=TEXTSPEED_OPTIONS[self.textspeed_combo.currentIndex()][1],
            transitions=TRANSITIONS_OPTIONS[self.transitions_combo.currentIndex()][1],
            bgmvolume=0 if mute else None,
            mevolume=0 if mute else None,
            sevolume=0 if mute else None,
            bgm=self.bgm_combo.currentData(),
        )
        self.status_view.setPlainText("Launching Game.exe (watch)...")
        # No timeout: Watch is interactive, not headless -- a human is present
        # and slow text speed/full battle animations can legitimately run well
        # past any fixed bound. Only Generate (unattended) needs a stuck-process
        # safety net.
        self.runner.start(self.config.vendor_dir, env_vars, None, result_filename=WATCH_RESULT_FILE)

    def _on_started(self):
        self.watch_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

    def _on_finished(self, result):
        self.watch_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

        text = json.dumps(result, indent=2)
        if result.get("ok") and result.get("had_error"):
            text += (
                "\n\n[error during battle] the engine's own error recovery caught and "
                "logged something mid-battle, then let the battle continue/end normally -- "
                "see error_log_entry above for the actual exception."
            )
        expected = self._expected_result
        self._expected_result = None
        if expected and result.get("ok") and expected.get("result") is not None:
            if result.get("result") != expected.get("result"):
                text += (
                    f"\n\n[unexpected outcome] expected result={expected.get('result')!r}, "
                    f"got {result.get('result')!r}"
                )
        self.status_view.setPlainText(text)
