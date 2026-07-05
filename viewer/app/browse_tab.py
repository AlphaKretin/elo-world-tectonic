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

from app.results_source import load_results_lib

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

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.format_combo = QComboBox()
        self.refresh_button = QPushButton("Refresh")
        top.addWidget(self.format_combo, 1)
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

        self.format_combo.currentTextChanged.connect(self._load_format)
        self.refresh_button.clicked.connect(self.refresh)
        self.use_button.clicked.connect(self._emit_selected)
        self.table.itemDoubleClicked.connect(lambda _: self._emit_selected())

        self.refresh()

    def _lib(self):
        if self._results_lib is None:
            self._results_lib = load_results_lib(self.config.analysis_dir)
        return self._results_lib

    def refresh(self):
        try:
            lib = self._lib()
            formats = lib.discover_formats(results_dir=self.config.results_dir)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            QMessageBox.warning(self, "Couldn't load results", str(exc))
            return

        current = self.format_combo.currentText()
        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        self.format_combo.addItems(formats)
        if current in formats:
            self.format_combo.setCurrentText(current)
        self.format_combo.blockSignals(False)

        self._load_format(self.format_combo.currentText())

    def _load_format(self, fmt):
        self._current_format = fmt or None
        self._rows = []
        self.table.setRowCount(0)
        if not fmt:
            return

        lib = self._lib()
        self._rows = lib.load_results(fmt, results_dir=self.config.results_dir)
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            self.table.setItem(i, 0, QTableWidgetItem(row.get("trainer1", "")))
            self.table.setItem(i, 1, QTableWidgetItem(row.get("trainer2", "")))
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
