from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import format_selector
from app.results_source import load_results_lib
from app.trainer_names import TrainerNameResolver

COLUMNS = ["Trainer 1", "Trainer 2", "Seed", "Result", "Rounds"]


class BrowseTab(QWidget):
    """Browses results/*.jsonl via analysis/results_lib.py and hands a
    selected match off to the Generate tab."""

    match_selected = Signal(dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._results_lib = None
        self._rows = []
        self._current_format = None
        self._names = TrainerNameResolver(config)

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.battle_type_combo = QComboBox()
        for value, label in format_selector.BATTLE_TYPES:
            self.battle_type_combo.addItem(label, value)
        self.curse_variant_combo = QComboBox()
        for value, label in format_selector.CURSE_VARIANTS:
            self.curse_variant_combo.addItem(label, value)
        self.refresh_button = QPushButton("Refresh")
        top.addWidget(self.battle_type_combo, 1)
        top.addWidget(self.curse_variant_combo, 1)
        top.addWidget(self.refresh_button)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)

        self.use_button = QPushButton("Use selected match")
        layout.addWidget(self.use_button)

        self.battle_type_combo.currentIndexChanged.connect(self._reload)
        self.curse_variant_combo.currentIndexChanged.connect(self._reload)
        self.refresh_button.clicked.connect(self.refresh)
        self.use_button.clicked.connect(self._emit_selected)
        self.table.itemDoubleClicked.connect(lambda _: self._emit_selected())

        self.refresh()

    def _lib(self):
        if self._results_lib is None:
            self._results_lib = load_results_lib(self.config.analysis_dir)
        return self._results_lib

    def _current_fmt(self):
        return format_selector.format_key(
            self.battle_type_combo.currentData(), self.curse_variant_combo.currentData()
        )

    def refresh(self):
        self._reload()

    def _reload(self):
        self._load_format(self._current_fmt())

    def _load_format(self, fmt):
        self._current_format = fmt or None
        self._rows = []
        self.table.setRowCount(0)
        if not fmt:
            return

        try:
            lib = self._lib()
            self._rows = lib.load_results(fmt, results_dir=self.config.results_dir)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            QMessageBox.warning(self, "Couldn't load results", str(exc))
            return

        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            for col, key in ((0, "trainer1"), (1, "trainer2")):
                label = row.get(key, "")
                item = QTableWidgetItem(self._names.display_name(label))
                item.setToolTip(label)
                self.table.setItem(i, col, item)
            self.table.setItem(i, 2, QTableWidgetItem(str(row.get("seed", ""))))
            self.table.setItem(i, 3, QTableWidgetItem(str(row.get("result", ""))))
            self.table.setItem(i, 4, QTableWidgetItem(str(row.get("rounds", ""))))

    def _emit_selected(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return
        row = self._rows[selected_rows[0].row()]
        payload = dict(row)
        payload["format"] = self._current_format
        self.match_selected.emit(payload)
