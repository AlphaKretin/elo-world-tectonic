"""Dialog for creating or editing one custom bracket: a name, a format, and
16 seeds in order. Reordering seeds (without necessarily changing who's in
the bracket) is done here too, via per-row up/down buttons -- this is how
Luna re-seeds a curated bracket to explore a different outcome, by
duplicating it into a custom bracket first (see bracket_manager_dialog.py)
and then reordering here.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import format_selector
from app.trainer_names import TrainerNameResolver
from app.trainer_picker_dialog import TrainerPickerDialog

SEED_COUNT = 16


class BracketEditorDialog(QDialog):
    def __init__(self, config, existing_names, initial=None, parent=None):
        """existing_names: names already taken by *other* brackets (curated
        or custom) -- the dialog's own starting name, if editing, is not
        included, so saving without changing the name doesn't collide with
        itself."""
        super().__init__(parent)
        self.config = config
        self._existing_names = set(existing_names)
        self._names = TrainerNameResolver(config)
        self._seeds = list(initial["seeds"]) if initial else [None] * SEED_COUNT
        self.setWindowTitle("Edit Custom Bracket" if initial else "New Custom Bracket")
        self.resize(480, 650)

        layout = QVBoxLayout(self)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(initial["name"] if initial else "")
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("Battle type:"))
        self.battle_type_combo = QComboBox()
        for value, label in format_selector.BATTLE_TYPES:
            self.battle_type_combo.addItem(label, value)
        format_row.addWidget(self.battle_type_combo, 1)
        format_row.addWidget(QLabel("Curse variant:"))
        self.curse_variant_combo = QComboBox()
        for value, label in format_selector.CURSE_VARIANTS:
            self.curse_variant_combo.addItem(label, value)
        format_row.addWidget(self.curse_variant_combo, 1)
        layout.addLayout(format_row)

        if initial:
            battle_type, curse_variant = format_selector.parse_format_key(initial["format"])
            self.battle_type_combo.setCurrentIndex(self.battle_type_combo.findData(battle_type))
            self.curse_variant_combo.setCurrentIndex(self.curse_variant_combo.findData(curse_variant))

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        seeds_widget = QWidget()
        self._seeds_layout = QVBoxLayout(seeds_widget)
        self._seeds_layout.setAlignment(Qt.AlignTop)
        scroll_area.setWidget(seeds_widget)
        layout.addWidget(scroll_area, 1)

        self._row_labels = []
        for i in range(SEED_COUNT):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"Seed {i + 1}:"))
            name_label = QLabel()
            name_label.setStyleSheet("color: gray;")
            row.addWidget(name_label, 1)
            self._row_labels.append(name_label)

            up_button = QPushButton("▲")
            up_button.setFixedWidth(28)
            up_button.clicked.connect(lambda _, idx=i: self._move_seed(idx, -1))
            row.addWidget(up_button)

            down_button = QPushButton("▼")
            down_button.setFixedWidth(28)
            down_button.clicked.connect(lambda _, idx=i: self._move_seed(idx, 1))
            row.addWidget(down_button)

            choose_button = QPushButton("Choose...")
            choose_button.clicked.connect(lambda _, idx=i: self._choose_seed(idx))
            row.addWidget(choose_button)

            self._seeds_layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        self._refresh_seed_labels()

    def _refresh_seed_labels(self):
        for i, label in enumerate(self._seeds):
            text = self._names.display_name(label) if label else "(empty)"
            self._row_labels[i].setText(text)

    def _choose_seed(self, idx):
        dialog = TrainerPickerDialog(self.config, self)
        if dialog.exec() == QDialog.Accepted:
            self._seeds[idx] = dialog.selected_label()
            self._refresh_seed_labels()

    def _move_seed(self, idx, delta):
        other = idx + delta
        if not (0 <= other < SEED_COUNT):
            return
        self._seeds[idx], self._seeds[other] = self._seeds[other], self._seeds[idx]
        self._refresh_seed_labels()

    def _on_save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Enter a name for this bracket.")
            return
        if name in self._existing_names:
            QMessageBox.warning(self, "Name in use", f"A bracket named {name!r} already exists.")
            return
        if any(label is None for label in self._seeds):
            QMessageBox.warning(self, "Incomplete bracket", "All 16 seeds must be filled in.")
            return
        if len(set(self._seeds)) != SEED_COUNT:
            QMessageBox.warning(self, "Duplicate trainer", "The same trainer can't fill two seeds.")
            return

        fmt = format_selector.format_key(self.battle_type_combo.currentData(), self.curse_variant_combo.currentData())
        self._result = {"name": name, "format": fmt, "seeds": list(self._seeds)}
        self.accept()

    def result_bracket(self):
        return self._result
