import json
import os

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

RESULT_FILE_RELATIVE = os.path.join("Analysis", "replay_result.txt")
STDOUT_TAIL_CHARS = 4000
STDERR_TAIL_CHARS = 4000


class ReplayRunner(QObject):
    """Drives Game.exe exactly as save_replay.ps1 does, but waits for
    completion and reports a structured result instead of firing-and-forgetting.

    QProcess.finished is the sole completion signal, for both headless and
    watch-live runs: headless_boot.rb exits the process once the battle is
    done regardless of display settings, so there's no race to resolve with
    a file watcher.
    """

    finished = Signal(dict)
    started = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._cancelled = False

    def is_running(self):
        return self._process is not None and self._process.state() != QProcess.NotRunning

    def start(self, vendor_dir, env_vars, timeout_seconds):
        if self.is_running():
            raise RuntimeError("A replay run is already in progress.")

        self._vendor_dir = vendor_dir
        self._cancelled = False

        result_path = os.path.join(vendor_dir, RESULT_FILE_RELATIVE)
        if os.path.exists(result_path):
            os.remove(result_path)

        qenv = QProcessEnvironment.systemEnvironment()
        for key, value in env_vars.items():
            qenv.insert(key, value)

        self._process = QProcess(self)
        self._process.setWorkingDirectory(vendor_dir)
        self._process.setProcessEnvironment(qenv)
        self._process.setProgram(os.path.join(vendor_dir, "Game.exe"))
        self._process.finished.connect(self._on_finished)

        self._process.start()
        self._timer.start(int(timeout_seconds * 1000))
        self.started.emit()

    def cancel(self):
        if not self.is_running():
            return
        self._cancelled = True
        self._timer.stop()
        self._process.kill()

    def _on_timeout(self):
        if self.is_running():
            self._process.kill()
        self.finished.emit(
            {
                "ok": False,
                "error_class": "Timeout",
                "error_message": "Game.exe did not finish within the configured timeout.",
            }
        )

    def _on_finished(self, exit_code, exit_status):
        self._timer.stop()
        result_path = os.path.join(self._vendor_dir, RESULT_FILE_RELATIVE)

        if os.path.exists(result_path):
            with open(result_path, "r", encoding="utf-8") as f:
                try:
                    result = json.load(f)
                except json.JSONDecodeError:
                    result = {
                        "ok": False,
                        "error_class": "MalformedResult",
                        "error_message": "replay_result.txt was not valid JSON.",
                    }
        elif self._cancelled:
            result = {"ok": False, "error_class": "Cancelled", "error_message": "Cancelled by user."}
        else:
            stdout = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
            stderr = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
            result = {
                "ok": False,
                "error_class": "Crash",
                "error_message": f"Game.exe exited (code {exit_code}) without producing a result.",
                "stdout_tail": stdout[-STDOUT_TAIL_CHARS:],
                "stderr_tail": stderr[-STDERR_TAIL_CHARS:],
            }

        self.finished.emit(result)
