from PySide6.QtCore import QEvent, QObject, Qt, QThread
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import vendor_fetch
from app.browse_tab import BrowseTab
from app.config import AppConfig
from app.generate_tab import GenerateTab
from app.watch_tab import WatchTab

GENERATE_TAB_INDEX = 1
WATCH_TAB_INDEX = 2
BLOCKED_TAB_TOOLTIP = "Waiting for the game files to finish downloading/compiling..."


class _DisabledTabCursorFilter(QObject):
    """Shows a forbidden cursor while hovering a disabled tab -- Qt greys out
    the label but otherwise leaves the tab looking exactly like a clickable
    one, which reads as broken rather than "not ready yet"."""

    def __init__(self, tab_widget):
        super().__init__(tab_widget)
        self.tab_widget = tab_widget

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseMove:
            index = obj.tabAt(event.pos())
            if index >= 0 and not self.tab_widget.isTabEnabled(index):
                obj.setCursor(Qt.ForbiddenCursor)
            else:
                obj.unsetCursor()
        return False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Elo World Tectonic — Replay Viewer")
        self.resize(900, 700)

        self.config = AppConfig()
        self._current_manifest = None
        self._vendor_thread = None
        self._vendor_worker = None
        self._vendor_compiler = None
        self.redownload_action = None
        self.recompile_action = None

        central = QWidget()
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        self.vendor_status_label = QLabel()
        self.vendor_status_label.setVisible(False)
        layout.addWidget(self.vendor_status_label)

        self.vendor_progress = QProgressBar()
        self.vendor_progress.setVisible(False)
        layout.addWidget(self.vendor_progress)

        self.tabs = QTabWidget()
        self.browse_tab = BrowseTab(self.config)
        self.generate_tab = GenerateTab(self.config)
        self.watch_tab = WatchTab(self.config)
        self.tabs.addTab(self.browse_tab, "Browse")
        self.tabs.addTab(self.generate_tab, "Generate")
        self.tabs.addTab(self.watch_tab, "Watch")
        layout.addWidget(self.tabs)
        self.tabs.tabBar().installEventFilter(_DisabledTabCursorFilter(self.tabs))

        self.browse_tab.match_selected.connect(self._on_match_selected)
        self.generate_tab.watch_requested.connect(self._on_watch_requested)

        self._ensure_vendor_ready()

    def _ensure_vendor_ready(self):
        manifest = vendor_fetch.load_manifest(self.config.repo_root)
        if manifest is None:
            # Dev checkout (or a broken distributed install with no
            # manifest) -- fall back to the old manual "point me at the
            # folder" flow instead of auto-fetching anything.
            self._ensure_valid_config()
            return

        self._current_manifest = manifest
        self._add_advanced_menu()

        if self.config.is_valid() and not vendor_fetch.needs_fetch(manifest, self.config.vendor_dir):
            return
        self._start_vendor_fetch()

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

    def _add_advanced_menu(self):
        # Tucked away in a menu rather than sitting as buttons at the top of
        # the window at all times -- these are "in case something's gone
        # wrong" actions, not part of the everyday flow, so they shouldn't
        # compete for attention once the game's downloaded and working.
        menu = self.menuBar().addMenu("Advanced")
        self.redownload_action = QAction("Re-download game files", self)
        self.recompile_action = QAction("Recompile game data", self)
        self.redownload_action.triggered.connect(self._on_redownload_clicked)
        self.recompile_action.triggered.connect(self._on_recompile_clicked)
        menu.addAction(self.redownload_action)
        menu.addAction(self.recompile_action)

    def _set_tabs_blocked(self, blocked):
        for index in (GENERATE_TAB_INDEX, WATCH_TAB_INDEX):
            self.tabs.setTabEnabled(index, not blocked)
            self.tabs.setTabToolTip(index, BLOCKED_TAB_TOOLTIP if blocked else "")

    def _set_vendor_actions_enabled(self, enabled):
        if self.redownload_action is not None:
            self.redownload_action.setEnabled(enabled)
        if self.recompile_action is not None:
            self.recompile_action.setEnabled(enabled)

    def _start_vendor_fetch(self):
        self._set_tabs_blocked(True)
        self._set_vendor_actions_enabled(False)
        self.vendor_status_label.setVisible(True)
        self.vendor_progress.setVisible(True)
        self.vendor_status_label.setText("Downloading game files...")
        self.vendor_progress.setRange(0, 0)

        self._vendor_thread = QThread(self)
        self._vendor_worker = vendor_fetch.VendorDownloadWorker(
            self._current_manifest["repo"],
            self._current_manifest["commit"],
            self.config.vendor_dir,
            self._current_manifest.get("sha256"),
            self._current_manifest.get("size_bytes"),
        )
        self._vendor_worker.moveToThread(self._vendor_thread)
        self._vendor_thread.started.connect(self._vendor_worker.run)
        self._vendor_worker.progress.connect(self.vendor_status_label.setText)
        self._vendor_worker.download_progress.connect(self._on_download_progress)
        self._vendor_worker.finished.connect(self._on_download_finished)
        self._vendor_thread.start()

    def _on_download_progress(self, read, total):
        if total:
            self.vendor_progress.setRange(0, total)
            self.vendor_progress.setValue(read)
        else:
            self.vendor_progress.setRange(0, 0)

    def _on_download_finished(self, ok, error_message):
        self._vendor_thread.quit()
        self._vendor_thread.wait()
        self._vendor_thread = None
        self._vendor_worker = None

        if not ok:
            self._on_vendor_setup_failed("Download failed", error_message)
            return
        self._start_compile()

    def _start_compile(self):
        self._set_tabs_blocked(True)
        self._set_vendor_actions_enabled(False)
        self.vendor_status_label.setVisible(True)
        self.vendor_progress.setVisible(True)
        self.vendor_progress.setRange(0, 0)
        self.vendor_status_label.setText(
            "Compiling game data (one-time) -- a game window will open and stay open until this finishes."
        )
        self._vendor_compiler = vendor_fetch.VendorCompiler(self.config.vendor_dir, self)
        self._vendor_compiler.finished.connect(self._on_compile_finished)
        self._vendor_compiler.start()

    def _on_compile_finished(self, ok, error_message):
        self._vendor_compiler = None
        self._set_vendor_actions_enabled(True)

        if not ok:
            self._on_vendor_setup_failed("Compile failed", error_message)
            return

        self.vendor_status_label.setVisible(False)
        self.vendor_progress.setVisible(False)
        self._set_tabs_blocked(False)

    def _on_vendor_setup_failed(self, title, error_message):
        self._set_vendor_actions_enabled(True)
        self.vendor_progress.setVisible(False)
        self.vendor_status_label.setText(f"{title}: {error_message} Use the Advanced menu to try again.")
        QMessageBox.warning(self, title, error_message)

    def _on_redownload_clicked(self):
        # Forces a fresh download even if the installed commit already
        # matches the manifest -- e.g. the user suspects local corruption
        # and wants a clean slate rather than waiting for a version bump.
        self._start_vendor_fetch()

    def _on_recompile_clicked(self):
        if not self.config.is_valid():
            QMessageBox.warning(
                self,
                "Game not downloaded",
                "Download the game files first (Advanced > Re-download game files).",
            )
            return
        self._start_compile()

    def _on_match_selected(self, payload):
        self.generate_tab.set_match(payload)
        self.tabs.setCurrentWidget(self.generate_tab)

    def _on_watch_requested(self, dat_path, expected_result):
        self.watch_tab.select_replay(dat_path, expected_result)
        self.tabs.setCurrentWidget(self.watch_tab)
