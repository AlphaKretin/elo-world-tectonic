import json
import os

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from app import win_window_utils

DEFAULT_RESULT_FILE_RELATIVE = os.path.join("Analysis", "replay_result.txt")
STDOUT_TAIL_CHARS = 4000
STDERR_TAIL_CHARS = 4000


class ReplayRunner(QObject):
    """Drives Game.exe exactly as save_replay.ps1 does, but waits for
    completion and reports a structured result instead of firing-and-forgetting.

    Shared by both generation (Analysis/replay_result.txt) and watch
    (Analysis/watch_result.txt) -- same QProcess orchestration either way,
    just a different env dict and result file. QProcess.finished is the
    sole completion signal: headless_boot.rb exits the process once its
    task is done, so there's no race to resolve with a file watcher.
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
        self._timed_out = False
        self._window_suppressor = None

    def is_running(self):
        return self._process is not None and self._process.state() != QProcess.NotRunning

    def start(
        self,
        vendor_dir,
        env_vars,
        timeout_seconds,
        result_filename=DEFAULT_RESULT_FILE_RELATIVE,
        suppress_window=False,
    ):
        """suppress_window sends the game's window behind the viewer instead
        of letting it steal focus -- appropriate for Generate (meant to run
        unattended), never for Watch (the whole point is seeing the battle).

        timeout_seconds is falsy (None/0) to disable the watchdog entirely --
        appropriate for Watch, where a human is present and slow text/battle
        animations can legitimately run well past any fixed bound. Generate
        (headless, unattended) still wants a real timeout as its only
        defense against a genuinely stuck process."""
        if self.is_running():
            raise RuntimeError("A replay run is already in progress.")

        self._vendor_dir = vendor_dir
        self._result_filename = result_filename
        self._cancelled = False
        self._timed_out = False

        result_path = os.path.join(vendor_dir, result_filename)
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

        self._window_suppressor = None
        if suppress_window:
            self._window_suppressor = win_window_utils.BackgroundWindowSuppressor(
                get_pid=lambda: self._process.processId() if self._process else None,
                refocus_widget=self.parent(),
                parent=self,
            )

        if timeout_seconds:
            self._timer.start(int(timeout_seconds * 1000))
        self.started.emit()

    def cancel(self):
        if not self.is_running():
            return
        self._cancelled = True
        self._timer.stop()
        self._process.kill()

    def _on_timeout(self):
        self._timed_out = True
        if self.is_running():
            self._process.kill()
        # Don't emit `finished` here -- QProcess.finished will still fire
        # once Windows reports the killed process as terminated, and
        # _on_finished (guarded by self._timed_out below) is what actually
        # reports it. Emitting here too used to race with that: the later,
        # genuine QProcess.finished signal would land second and overwrite
        # this "Timeout" result with a spurious "Crash" one (kill() forces
        # exit_status=CrashExit and a Qt-internal TerminateProcess exit code
        # -- 0xf291/62097 on Windows -- that looks exactly like a real crash
        # but isn't).

    def _on_finished(self, exit_code, exit_status):
        self._timer.stop()
        result_path = os.path.join(self._vendor_dir, self._result_filename)

        if os.path.exists(result_path):
            with open(result_path, "r", encoding="utf-8") as f:
                try:
                    result = json.load(f)
                except json.JSONDecodeError:
                    result = {
                        "ok": False,
                        "error_class": "MalformedResult",
                        "error_message": f"{os.path.basename(result_path)} was not valid JSON.",
                    }
        elif self._cancelled:
            result = {"ok": False, "error_class": "Cancelled", "error_message": "Cancelled by user."}
        elif self._timed_out:
            result = {
                "ok": False,
                "error_class": "Timeout",
                "error_message": "Game.exe did not finish within the configured timeout.",
            }
        else:
            stdout = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
            stderr = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
            result = {
                "ok": False,
                "error_class": "Crash",
                "error_message": f"Game.exe exited (code {exit_code}) without producing a result.",
                "exit_status": "CrashExit" if exit_status == QProcess.CrashExit else "NormalExit",
                "stdout_tail": stdout[-STDOUT_TAIL_CHARS:],
                "stderr_tail": stderr[-STDERR_TAIL_CHARS:],
            }

        self.finished.emit(result)
