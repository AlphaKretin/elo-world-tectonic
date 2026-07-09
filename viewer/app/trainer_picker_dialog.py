"""Small reusable "pick one trainer from the full roster" dialog -- used by
the bracket editor (assigning a seed slot) and by GenerateTab (picking
Trainer 1/2), so raw "TYPE:Name" labels don't have to be typed by hand in
either place. Mirrors TrainersTab's own search-box + sorted-list pattern
(trainers_tab.py's _populate_trainer_list/_apply_filter) rather than sharing
code with it -- that tab's list is entangled with its rating/highlights
columns, which don't apply here.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from app.results_source import load_results_lib
from app.trainer_names import TrainerNameResolver


class TrainerPickerDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose trainer")
        self.resize(360, 480)
        self._names = TrainerNameResolver(config)

        layout = QVBoxLayout(self)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search trainers...")
        layout.addWidget(self.search_box)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        results_lib = load_results_lib(config.analysis_dir)
        try:
            trainer_data = results_lib.load_trainer_data(results_dir=config.results_dir)
        except OSError:
            trainer_data = {}
        labels = sorted(trainer_data.keys(), key=lambda label: self._names.display_name(label).lower())
        for label in labels:
            item = QListWidgetItem(self._names.display_name(label))
            item.setData(Qt.UserRole, label)
            self.list_widget.addItem(item)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

        self.search_box.textChanged.connect(self._apply_filter)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.search_box.setFocus()

    def _apply_filter(self, text):
        query = text.strip().lower()
        first_visible = None
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            hidden = bool(query) and query not in item.text().lower()
            item.setHidden(hidden)
            if not hidden and first_visible is None:
                first_visible = item
        current = self.list_widget.currentItem()
        if first_visible is not None and (current is None or current.isHidden()):
            self.list_widget.setCurrentItem(first_visible)

    def selected_label(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.UserRole) if item else None

    def accept(self):
        if self.list_widget.currentItem() is None or self.list_widget.currentItem().isHidden():
            return
        super().accept()
