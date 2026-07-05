from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QTabWidget

from app.browse_tab import BrowseTab
from app.config import AppConfig
from app.generate_tab import GenerateTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Elo World Tectonic — Replay Viewer")
        self.resize(900, 700)

        self.config = AppConfig()
        self._ensure_valid_config()

        self.tabs = QTabWidget()
        self.browse_tab = BrowseTab(self.config)
        self.generate_tab = GenerateTab(self.config)
        self.tabs.addTab(self.browse_tab, "Browse")
        self.tabs.addTab(self.generate_tab, "Generate")
        self.setCentralWidget(self.tabs)

        self.browse_tab.match_selected.connect(self._on_match_selected)

    def _ensure_valid_config(self):
        if self.config.is_valid():
            return
        QMessageBox.information(
            self,
            "Locate the game",
            f"Game.exe wasn't found at {self.config.game_exe_path!r}. "
            "Select the vendor/tectonic-content folder that contains it.",
        )
        while not self.config.is_valid():
            chosen = QFileDialog.getExistingDirectory(self, "Select the vendor/tectonic-content folder")
            if not chosen:
                break
            self.config.vendor_dir = chosen

    def _on_match_selected(self, payload):
        self.generate_tab.set_match(payload)
        self.tabs.setCurrentWidget(self.generate_tab)
