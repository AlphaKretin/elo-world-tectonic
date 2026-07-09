"""Dialog for creating/editing/deleting custom brackets, and for duplicating
any bracket (curated or custom) into a new custom one -- the latter is how
Luna re-seeds a curated bracket without ever touching bracket_seeds.py
itself (see bracket_editor_dialog.py for the actual seed reordering)."""
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app import custom_brackets, format_selector
from app.bracket_editor_dialog import BracketEditorDialog


class BracketManagerDialog(QDialog):
    def __init__(self, config, curated_brackets, parent=None):
        super().__init__(parent)
        self.config = config
        self._curated_brackets = curated_brackets
        self._custom_brackets = custom_brackets.load_custom_brackets(config)
        self.changed = False
        self.setWindowTitle("Custom Brackets")
        self.resize(420, 400)

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        buttons_row = QHBoxLayout()
        self.new_button = QPushButton("New...")
        self.duplicate_button = QPushButton("Duplicate From...")
        self.edit_button = QPushButton("Edit...")
        self.delete_button = QPushButton("Delete")
        for button in (self.new_button, self.duplicate_button, self.edit_button, self.delete_button):
            buttons_row.addWidget(button)
        layout.addLayout(buttons_row)

        close_buttons = QDialogButtonBox(QDialogButtonBox.Close)
        layout.addWidget(close_buttons)

        self.new_button.clicked.connect(self._on_new)
        self.duplicate_button.clicked.connect(self._on_duplicate)
        self.edit_button.clicked.connect(self._on_edit)
        self.delete_button.clicked.connect(self._on_delete)
        close_buttons.rejected.connect(self.reject)
        close_buttons.accepted.connect(self.accept)
        self.list_widget.currentRowChanged.connect(self._update_button_states)

        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()
        for entry in self._custom_brackets:
            self.list_widget.addItem(QListWidgetItem(f"{entry['name']} ({format_selector.format_label(entry['format'])})"))
        self._update_button_states()

    def _update_button_states(self):
        has_selection = self.list_widget.currentRow() >= 0
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

    def _all_names(self):
        return {entry["name"] for entry in self._curated_brackets} | {entry["name"] for entry in self._custom_brackets}

    def _save(self):
        custom_brackets.save_custom_brackets(self.config, self._custom_brackets)
        self.changed = True

    def _on_new(self):
        dialog = BracketEditorDialog(self.config, self._all_names(), parent=self)
        if dialog.exec() == QDialog.Accepted:
            self._custom_brackets.append(dialog.result_bracket())
            self._save()
            self._refresh_list()

    def _on_duplicate(self):
        all_brackets = self._curated_brackets + self._custom_brackets
        names = [entry["name"] for entry in all_brackets]
        if not names:
            return
        name, ok = QInputDialog.getItem(self, "Duplicate From", "Base bracket:", names, editable=False)
        if not ok:
            return
        source = next(entry for entry in all_brackets if entry["name"] == name)
        initial = {"name": "", "format": source["format"], "seeds": list(source["seeds"])}
        dialog = BracketEditorDialog(self.config, self._all_names(), initial=initial, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self._custom_brackets.append(dialog.result_bracket())
            self._save()
            self._refresh_list()

    def _on_edit(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        entry = self._custom_brackets[row]
        existing_names = self._all_names() - {entry["name"]}
        dialog = BracketEditorDialog(self.config, existing_names, initial=entry, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self._custom_brackets[row] = dialog.result_bracket()
            self._save()
            self._refresh_list()

    def _on_delete(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        entry = self._custom_brackets[row]
        confirm = QMessageBox.question(
            self, "Delete bracket", f"Delete custom bracket {entry['name']!r}? This can't be undone."
        )
        if confirm != QMessageBox.Yes:
            return
        del self._custom_brackets[row]
        self._save()
        self._refresh_list()
