import datetime
import json
import os

from PySide6.QtCore import QSettings, Qt, Signal
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

from app import config as config_module, game_assets, replay_env, replay_runner, ui_settings
from app.elided_tooltip_delegate import ElidedTooltipDelegate
from app.replay_runner import ReplayRunner
from app.tooltip_header import install_header_tooltips
from app.trainer_names import TrainerNameResolver

COLUMNS = ["Name", "Trainer 1", "Trainer 2", "Rnds", "Modified"]
WATCH_RESULT_FILE = os.path.join("Analysis", "watch_result.txt")
STAGING_NAME = "_WatchStaging"

BATTLESCENE_OPTIONS = [("On", 0), ("Fast", 1), ("Off", 2)]
TEXTSPEED_OPTIONS = [("Slow", 0), ("Normal", 1), ("Fast", 2), ("Rapid", 3), ("Instant", 4)]
TRANSITIONS_OPTIONS = [("Standard", 0), ("Fast", 1)]


def _option_index(options, label):
    return next(i for i, (opt_label, _value) in enumerate(options) if opt_label == label)


class _CaseInsensitiveItem(QTableWidgetItem):
    """Sorts by lowercased text, matching Browse tab's sort keys (which
    lowercase Trainer 1/2 before comparing) instead of Qt's default
    case-sensitive text compare. Blank text (Trainer 1/2 with no sidecar,
    so no known label) always lands at the bottom regardless of which way
    the column is currently sorted -- same fixed-sentinel-flips-under-
    descending trap as _NumericItem below, see its docstring for why
    direction has to be read from the table rather than baked into the
    comparison. Never triggers on the Name column, whose text is never
    blank."""

    def __lt__(self, other):
        self_text = self.text().lower()
        other_text = other.text().lower() if hasattr(other, "text") else ""
        if not self_text and not other_text:
            return False
        table = self.tableWidget()
        descending = table is not None and table.horizontalHeader().sortIndicatorOrder() == Qt.DescendingOrder
        if not self_text:
            return descending
        if not other_text:
            return not descending
        return self_text < other_text


class _NumericItem(QTableWidgetItem):
    """Sorts by a stored numeric value instead of displayed text (so "9"
    sorts before "10"). value=None (no sidecar, or an older sidecar from
    before rounds was recorded) always lands at the bottom, regardless of
    which way the column is currently sorted -- a plain fixed sentinel
    (e.g. -1) sorts last under ascending but flips to *first* under
    descending, since Qt's descending sort is just the ascending order
    reversed (confirmed empirically: see ResultsTableModel's own
    _NONE_LAST_SORT_FIELDS in browse_tab.py for the same trap on a
    QAbstractTableModel). A QTableWidgetItem's __lt__ isn't handed the
    current sort order the way a model's sort(column, order) is, so this
    asks its owning table's header directly instead."""

    def __init__(self, text, value):
        super().__init__(text)
        self._value = value

    def __lt__(self, other):
        other_value = getattr(other, "_value", None)
        if self._value is None and other_value is None:
            return False
        table = self.tableWidget()
        descending = table is not None and table.horizontalHeader().sortIndicatorOrder() == Qt.DescendingOrder
        if self._value is None:
            return descending
        if other_value is None:
            return not descending
        return self._value < other_value


class WatchTab(QWidget):
    """Watches a .dat from vendor_dir/VSRecorder/ELOReplay/ through the
    engine's own playRecordedBattle, same mechanism as the in-game VS
    Recorder's "Watch battle" menu item. Display-setting overrides are
    applied in-memory only by the engine, never persisted to Options.dat."""

    # (dat_path, result) once a watch session ends, whatever the outcome --
    # crash/timeout/viewer-cancelled (result["ok"] is False), an in-game
    # cancel (ok True, result["result"] == 0), or an actual finish. Lets a
    # caller (the Bracket tab) defer revealing a match's winner until the
    # replay has actually been watched, rather than the moment it's handed
    # off, without needing to track "which match is this watch session for"
    # itself -- see bracket_lib.parse_bracket_slug.
    replay_finished = Signal(str, dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._names = TrainerNameResolver(config)
        self.runner = ReplayRunner(self)
        self.runner.started.connect(self._on_started)
        self.runner.finished.connect(self._on_finished)
        self._expected_result = None
        self._active_dat_path = None

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.import_button = QPushButton("Import .dat...")
        top.addWidget(self.import_button)
        top.addStretch(1)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeaderItem(3).setToolTip("Number of rounds the battle lasted")
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(3, 50)
        # A smidge past the default section size -- long enough to stop the
        # "YYYY-MM-DD HH:MM:SS" timestamp from just barely clipping.
        self.table.setColumnWidth(4, 150)
        install_header_tooltips(self.table)
        name_tooltip_delegate = ElidedTooltipDelegate(self.table)
        for col in (0, 1, 2):
            self.table.setItemDelegateForColumn(col, name_tooltip_delegate)
        self.table.setSortingEnabled(True)
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
        self.debug_check = QCheckBox("Debug mode (shows the engine's console window)")
        self._is_dev_build = config_module.is_dev_build()
        self.debug_check.setVisible(self._is_dev_build)
        mute_debug_row = QHBoxLayout()
        mute_debug_row.addWidget(self.mute_check)
        mute_debug_row.addWidget(self.debug_check)
        self.bgm_combo = QComboBox()
        self.bgm_combo.addItem("(default: derived from opponent)", None)
        for raw, display in game_assets.list_bgm_tracks(config.vendor_dir):
            self.bgm_combo.addItem(display, raw)
        form.addRow("Battle animations", self.battlescene_combo)
        form.addRow("Text speed", self.textspeed_combo)
        form.addRow("Battle transitions", self.transitions_combo)
        form.addRow("", mute_debug_row)
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

        self.import_button.clicked.connect(self._on_import_clicked)
        self.watch_button.clicked.connect(self._on_watch_clicked)
        self.cancel_button.clicked.connect(self.runner.cancel)

        settings = QSettings()
        ui_settings.bind_combo(settings, "watch/battlescene", self.battlescene_combo)
        ui_settings.bind_combo(settings, "watch/textspeed", self.textspeed_combo)
        ui_settings.bind_combo(settings, "watch/transitions", self.transitions_combo)
        ui_settings.bind_combo(settings, "watch/bgm", self.bgm_combo)
        ui_settings.bind_checkbox(settings, "watch/mute", self.mute_check)
        ui_settings.bind_checkbox(settings, "watch/debug", self.debug_check)

        self.refresh()

    def refresh(self):
        # Preserve the current selection across the rebuild below -- this
        # now also runs reactively (see MainWindow wiring generation_finished
        # here) while the user might be sitting on this tab with a row
        # already selected, not just from an explicit user action that
        # implies starting fresh.
        selected_rows = self.table.selectionModel().selectedRows()
        selected_name = self.table.item(selected_rows[0].row(), 0).text() if selected_rows else None

        # Sorting must be off while populating -- QTableWidget re-sorts after
        # every setItem() when enabled, so rows and their trainer columns
        # would scatter mid-population instead of landing together.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        replay_dir = self.config.replay_dir
        if not os.path.isdir(replay_dir):
            self.table.setSortingEnabled(True)
            return
        names = sorted(
            f for f in os.listdir(replay_dir) if f.lower().endswith(".dat") and f != f"{STAGING_NAME}.dat"
        )
        self.table.setRowCount(len(names))
        for i, name in enumerate(names):
            full_path = os.path.join(replay_dir, name)
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(full_path)).strftime("%Y-%m-%d %H:%M:%S")
            base_name = os.path.splitext(name)[0]
            sidecar = self._read_sidecar(base_name)
            self.table.setItem(i, 0, _CaseInsensitiveItem(base_name))
            self._set_trainer_columns(i, sidecar.get("trainer1", ""), sidecar.get("trainer2", ""))
            rounds = sidecar.get("rounds")
            self.table.setItem(i, 3, _NumericItem(str(rounds + 1) if rounds is not None else "", rounds))
            self.table.setItem(i, 4, QTableWidgetItem(mtime))
            if base_name == selected_name:
                self.table.selectRow(i)
        self.table.setSortingEnabled(True)

    def _read_sidecar(self, base_name):
        """base_name's sidecar dict from config.replay_metadata_dir, or {}
        if there isn't one/it's unreadable. Kept separate from replay_dir
        (inside the vendor/tectonic-content submodule) so this viewer-only
        metadata doesn't show up as untracked submodule content -- see
        GenerateTab._write_sidecar/_on_import_clicked for the writers."""
        sidecar_path = os.path.join(self.config.replay_metadata_dir, base_name + ".json")
        if not os.path.exists(sidecar_path):
            return {}
        try:
            with open(sidecar_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _set_trainer_columns(self, row, t1_label, t2_label):
        for col, label in ((1, t1_label), (2, t2_label)):
            item = _CaseInsensitiveItem(self._names.display_name(label) if label else "")
            item.setToolTip(label)
            self.table.setItem(row, col, item)

    def select_replay(self, dat_path, expected_result=None):
        """Called from Generate's "Watch this replay" hand-off. The file is
        already sitting in replay_dir (generation wrote it there), so this
        just selects/highlights its row instead of copying anything. The
        trainer columns are filled in directly from expected_result rather
        than through refresh()'s disk-sidecar lookup, just to avoid a
        redundant read of the sidecar GenerateTab already just wrote."""
        self.refresh()
        name = os.path.splitext(os.path.basename(dat_path))[0]
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == name:
                self.table.selectRow(row)
                if expected_result:
                    # Sorting must be off here too -- setItem on the first
                    # trainer column could re-sort and move this row before
                    # the second setItem call lands, misassigning it.
                    self.table.setSortingEnabled(False)
                    self._set_trainer_columns(
                        row, expected_result.get("trainer1", ""), expected_result.get("trainer2", "")
                    )
                    self.table.setSortingEnabled(True)
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
        if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dest)):
            # Already sitting in replay_dir -- copying it onto itself would
            # truncate it via the "wb" open below before the "rb" read
            # finishes (confirmed: corrupted a real replay this way). Nothing
            # to import, it's already there.
            self.refresh()
            return
        try:
            with open(src, "rb") as f_in, open(dest, "wb") as f_out:
                f_out.write(f_in.read())
            sidecar_src = src + ".json"
            if os.path.exists(sidecar_src):
                metadata_dir = self.config.replay_metadata_dir
                os.makedirs(metadata_dir, exist_ok=True)
                sidecar_dest = os.path.join(metadata_dir, os.path.splitext(os.path.basename(dest))[0] + ".json")
                with open(sidecar_src, "rb") as f_in, open(sidecar_dest, "wb") as f_out:
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

        sidecar_path = dat_path + ".json"
        sidecar = None
        if os.path.exists(sidecar_path):
            try:
                with open(sidecar_path, "r", encoding="utf-8") as f:
                    sidecar = json.load(f)
            except (OSError, json.JSONDecodeError):
                sidecar = None

        if not replay_runner.confirm_long_replay(self, sidecar.get("rounds") if sidecar else None, "watch"):
            return

        self._active_dat_path = dat_path

        replay_dir = self.config.replay_dir
        staging_path = os.path.join(replay_dir, f"{STAGING_NAME}.dat")
        with open(dat_path, "rb") as f_in, open(staging_path, "wb") as f_out:
            f_out.write(f_in.read())

        if sidecar is not None and self._expected_result is None:
            self._expected_result = sidecar

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
        extra_args = ["debug"] if self._is_dev_build and self.debug_check.isChecked() else None
        self.runner.start(
            self.config.vendor_dir, env_vars, None, result_filename=WATCH_RESULT_FILE, extra_args=extra_args
        )

    def _on_started(self):
        self.watch_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

    def _on_finished(self, result):
        self.watch_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

        if self._active_dat_path:
            self.replay_finished.emit(self._active_dat_path, result)
        self._active_dat_path = None

        expected = self._expected_result
        self._expected_result = None
        t1_name = self._names.display_name(expected["trainer1"]) if expected and expected.get("trainer1") else "Trainer 1"
        t2_name = self._names.display_name(expected["trainer2"]) if expected and expected.get("trainer2") else "Trainer 2"

        text = replay_runner.describe_result(result, t1_name, t2_name)
        if result.get("ok") and result.get("had_error"):
            text += (
                "\n\n[error during battle] the engine's own error recovery caught and "
                "logged something mid-battle, then let the battle continue/end normally:"
            )
            if result.get("error_log_entry"):
                text += f"\n{result['error_log_entry']}"
        if expected and result.get("ok") and expected.get("result") is not None:
            if result.get("result") != expected.get("result"):
                text += (
                    f"\n\n[unexpected outcome] expected "
                    f"{replay_runner.outcome_label(expected.get('result'), t1_name, t2_name)}, "
                    f"got {replay_runner.outcome_label(result.get('result'), t1_name, t2_name)}"
                )
        self.status_view.setPlainText(text)
