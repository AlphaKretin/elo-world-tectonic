import os
import sys

from PySide6.QtCore import QSettings

if getattr(sys, "frozen", False):
    # PyInstaller build: viewer.exe sits at the top of the shipped package,
    # with vendor/, analysis/, results/ as siblings (see scripts/build_release.ps1) --
    # unlike the dev checkout, there's no separate viewer/ subfolder to walk
    # up out of.
    _DEFAULT_REPO_ROOT = os.path.dirname(sys.executable)
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))  # .../viewer/app
    _VIEWER_DIR = os.path.dirname(_APP_DIR)  # .../viewer
    _DEFAULT_REPO_ROOT = os.path.dirname(_VIEWER_DIR)  # dev checkout: viewer/'s parent

DEFAULT_TIMEOUT_SECONDS = 120


def is_dev_build():
    """True for a dev checkout run via `python -m app`, false for a
    PyInstaller-frozen release build -- used to hide debugging-only options
    (e.g. the Generate/Watch tabs' Debug mode checkboxes) that shouldn't be
    exposed to end users of a distributed build."""
    return not getattr(sys, "frozen", False)


class AppConfig:
    """QSettings-backed paths, so a dev checkout and a distributed install
    differ only in these values, not in code (viewer/, results_lib.py, and
    the env-var contract are identical either way)."""

    def __init__(self):
        self._settings = QSettings()

    @property
    def repo_root(self):
        return self._settings.value("paths/repo_root", _DEFAULT_REPO_ROOT)

    @repo_root.setter
    def repo_root(self, value):
        self._settings.setValue("paths/repo_root", value)

    @property
    def vendor_dir(self):
        return self._settings.value(
            "paths/vendor_dir", os.path.join(self.repo_root, "vendor", "tectonic-content")
        )

    @vendor_dir.setter
    def vendor_dir(self, value):
        self._settings.setValue("paths/vendor_dir", value)

    @property
    def results_dir(self):
        # Distributed installs point this at the shipped canonical full-RR
        # results folder; the dev default is the same ground-truth directory
        # results_lib.py itself reads (results/current/, not results/remote/'s
        # pull-landing zone or results/local/'s in-progress shard scratch).
        return self._settings.value(
            "paths/results_dir", os.path.join(self.repo_root, "results", "current")
        )

    @results_dir.setter
    def results_dir(self, value):
        self._settings.setValue("paths/results_dir", value)

    @property
    def analysis_dir(self):
        return os.path.join(self.repo_root, "analysis")

    @property
    def game_exe_path(self):
        return os.path.join(self.vendor_dir, "Game.exe")

    @property
    def replay_dir(self):
        # Matches EloTournament::REPLAY_SAVE_FILE_NAME's "Saves/ELOReplay.rxdata"
        # -> VSRecorder resolves the directory from the save file's basename.
        return os.path.join(self.vendor_dir, "VSRecorder", "ELOReplay")

    @property
    def replay_metadata_dir(self):
        # Viewer-only sidecar metadata (trainer labels/result for a .dat),
        # keyed by the .dat's basename. Deliberately kept outside vendor_dir:
        # that's the vendor/tectonic-content submodule in a dev checkout, so
        # anything written there shows up as untracked submodule content with
        # no way for this repo to gitignore it. This directory lives under
        # the main repo instead, where viewer/replay_metadata/ can just be
        # gitignored normally.
        return os.path.join(self.repo_root, "viewer", "replay_metadata")

    @property
    def timeout_seconds(self):
        return int(self._settings.value("run/timeout_seconds", DEFAULT_TIMEOUT_SECONDS))

    @timeout_seconds.setter
    def timeout_seconds(self, value):
        self._settings.setValue("run/timeout_seconds", int(value))

    def is_valid(self):
        return os.path.isfile(self.game_exe_path)
