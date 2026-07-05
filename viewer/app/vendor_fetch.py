import hashlib
import json
import os
import shutil
import urllib.request
import zipfile

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from app import win_window_utils

MANIFEST_FILENAME = "vendor_manifest.json"
COMMIT_MARKER_FILENAME = ".vendor_commit"
COMPILE_MARKER_RELATIVE = os.path.join("Analysis", "compile_done.txt")
# "compile" (matching "Debug Game With PBS Compile.bat") also rebuilds the
# gitignored PBS data, not just Data/PluginScripts.rxdata -- takes longer
# than a plain script recompile, hence the generous timeout.
COMPILE_TIMEOUT_SECONDS = 300

# Dirs the engine/viewer expect to exist at runtime but that are gitignored
# in the vendor repo (recordings/saves/compiled-data output), so a fresh
# archive extraction won't contain them.
RUNTIME_DIRS = ["Save Game", "VSRecorder", "Analysis"]


def load_manifest(repo_root):
    """Only present in a distributed build (written by build_release.ps1);
    a dev checkout has no manifest, which is how callers tell the two
    apart and skip auto-fetch entirely in dev."""
    path = os.path.join(repo_root, MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def installed_commit(vendor_dir):
    path = os.path.join(vendor_dir, COMMIT_MARKER_FILENAME)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def needs_fetch(manifest, vendor_dir):
    return installed_commit(vendor_dir) != manifest["commit"]


class ChecksumMismatch(Exception):
    pass


class VendorDownloadWorker(QObject):
    """Runs on a QThread: downloads the pinned commit as a GitHub archive
    (no git/git-lfs dependency on the end user's machine) and extracts it
    over vendor_dir. Compiling the gitignored PluginScripts.rxdata/PBS data
    is a separate step (VendorCompiler) since it needs a QProcess/GUI event
    loop rather than a worker thread.
    """

    progress = Signal(str)
    download_progress = Signal(int, int)  # bytes_read, total_bytes (total==0 -> indeterminate)
    finished = Signal(bool, str)  # ok, error_message

    def __init__(self, repo, commit, vendor_dir, sha256=None, expected_size=None):
        super().__init__()
        self.repo = repo
        self.commit = commit
        self.vendor_dir = vendor_dir
        self.sha256 = sha256
        self.expected_size = expected_size

    def run(self):
        try:
            self._download_and_extract()
            self._write_commit_marker()
        except Exception as exc:
            self.finished.emit(False, str(exc))
            return
        self.finished.emit(True, "")

    def _download_and_extract(self):
        url = f"https://codeload.github.com/{self.repo}/zip/{self.commit}"
        os.makedirs(os.path.dirname(self.vendor_dir), exist_ok=True)

        self.progress.emit("Downloading game files...")
        tmp_zip = self.vendor_dir + "_download.zip.tmp"
        hasher = hashlib.sha256()
        with urllib.request.urlopen(url) as resp:
            # codeload responses are often chunked-transfer without a
            # Content-Length header, so fall back to the size recorded in
            # the manifest (from the same archive, at build time) for a
            # determinate progress bar instead of leaving it indeterminate.
            total = int(resp.headers.get("Content-Length", 0)) or (self.expected_size or 0)
            read = 0
            with open(tmp_zip, "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    hasher.update(chunk)
                    read += len(chunk)
                    self.download_progress.emit(read, total)

        # GitHub doesn't publish an official checksum for a zipball itself,
        # but build_release.ps1 downloads this same archive at release time
        # and records its hash, so this at least catches a corrupted or
        # truncated transfer before it's extracted over the previous install.
        if self.sha256:
            digest = hasher.hexdigest()
            if digest != self.sha256.lower():
                os.remove(tmp_zip)
                raise ChecksumMismatch(
                    f"Downloaded archive checksum mismatch (expected {self.sha256}, got {digest}) -- "
                    "the download may be corrupted or incomplete."
                )

        self.progress.emit("Extracting...")
        extract_root = self.vendor_dir + "_extract.tmp"
        if os.path.isdir(extract_root):
            shutil.rmtree(extract_root)
        try:
            with zipfile.ZipFile(tmp_zip) as zf:
                zf.extractall(extract_root)
        finally:
            os.remove(tmp_zip)

        # GitHub's codeload archives wrap everything in a single
        # "<repo>-<commit>" top-level folder.
        (inner_name,) = os.listdir(extract_root)
        inner_path = os.path.join(extract_root, inner_name)

        if os.path.isdir(self.vendor_dir):
            shutil.rmtree(self.vendor_dir)
        shutil.move(inner_path, self.vendor_dir)
        shutil.rmtree(extract_root)

        for d in RUNTIME_DIRS:
            os.makedirs(os.path.join(self.vendor_dir, d), exist_ok=True)

    def _write_commit_marker(self):
        with open(os.path.join(self.vendor_dir, COMMIT_MARKER_FILENAME), "w", encoding="utf-8") as f:
            f.write(self.commit)


class VendorCompiler(QObject):
    """Runs the "Debug Game With PBS Compile" launch (Game.exe debug compile,
    ELO_COMPILE_ONLY=1, poll for Analysis/compile_done.txt) once on the end
    user's machine after a fresh download -- PluginScripts.rxdata and the
    compiled PBS data are both gitignored, so the downloaded archive never
    contains them. This pops a real game window for the duration of the
    compile; if the user closes it early the process exit is caught below
    and surfaced as a failure the user can retry, not looped automatically."""

    finished = Signal(bool, str)

    def __init__(self, vendor_dir, parent=None):
        super().__init__(parent)
        self.vendor_dir = vendor_dir
        self._process = None
        self._elapsed_seconds = 0
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._check_marker)
        self._window_suppressor = None

    def start(self):
        marker_path = os.path.join(self.vendor_dir, COMPILE_MARKER_RELATIVE)
        if os.path.isfile(marker_path):
            os.remove(marker_path)

        qenv = QProcessEnvironment.systemEnvironment()
        qenv.insert("ELO_TOURNAMENT", "1")
        qenv.insert("ELO_COMPILE_ONLY", "1")

        self._process = QProcess(self)
        self._process.setWorkingDirectory(self.vendor_dir)
        self._process.setProcessEnvironment(qenv)
        self._process.setProgram(os.path.join(self.vendor_dir, "Game.exe"))
        self._process.setArguments(["debug", "compile"])
        self._process.start()

        self._window_suppressor = win_window_utils.BackgroundWindowSuppressor(
            get_pid=lambda: self._process.processId() if self._process else None,
            refocus_widget=self.parent(),
            parent=self,
        )

        self._elapsed_seconds = 0
        self._poll_timer.start(2000)

    def _check_marker(self):
        self._elapsed_seconds += 2
        marker_path = os.path.join(self.vendor_dir, COMPILE_MARKER_RELATIVE)
        done = os.path.isfile(marker_path)
        timed_out = self._elapsed_seconds >= COMPILE_TIMEOUT_SECONDS
        still_running = self._process.state() != QProcess.NotRunning

        if not done and not timed_out and still_running:
            return

        self._poll_timer.stop()
        if still_running:
            self._process.kill()
            self._process.waitForFinished(3000)

        if done:
            self.finished.emit(True, "")
        elif timed_out:
            self.finished.emit(False, "Game.exe did not finish compiling within the timeout.")
        else:
            self.finished.emit(False, "Game.exe exited before compiling finished.")
