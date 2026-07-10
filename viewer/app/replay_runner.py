import json
import os

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from app import win_window_utils

DEFAULT_RESULT_FILE_RELATIVE = os.path.join("Analysis", "replay_result.txt")
DEFAULT_HEARTBEAT_FILE_RELATIVE = os.path.join("Analysis", "elo_turn_heartbeat.json")
STDOUT_TAIL_CHARS = 4000
STDERR_TAIL_CHARS = 4000
HEARTBEAT_POLL_MS = 1000

# Above this many rounds (0-indexed, so the real round count is +1), Generate/
# Watch show a confirmation before launching Game.exe -- both can otherwise
# run for a long time with no way to bail out short of Cancel.
LONG_REPLAY_ROUND_THRESHOLD = 100


def confirm_long_replay(parent, rounds, action, estimated=False):
    """True if it's fine to proceed. rounds is the raw 0-indexed count (as
    stored in sidecars/RR rows); estimated marks a same-pairing/seed-chain
    guess (Generate, before the battle has actually run) rather than an
    exact known count (Watch, already-played)."""
    if rounds is None or rounds + 1 <= LONG_REPLAY_ROUND_THRESHOLD:
        return True
    qualifier = "is estimated to last around" if estimated else "lasted"
    reply = QMessageBox.question(
        parent,
        "Long replay",
        f"This replay {qualifier} {rounds + 1} rounds and may take a while to {action}. Continue?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    return reply == QMessageBox.Yes


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
    heartbeat = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.timeout.connect(self._poll_heartbeat)
        self._heartbeat_path = None
        self._heartbeat_mtime = None
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
        heartbeat_filename=None,
        extra_args=None,
    ):
        """extra_args (e.g. ["debug"]) is passed straight to Game.exe -- the
        same "debug" argument the launcher's own debug-recompile flow uses
        (vendor_fetch.py), which allocates the real console window so
        echoln/monkey-patch-warning output is visible, unlike a normal
        (non-debug) launch where nothing is attached to see it.

        suppress_window sends the game's window behind the viewer instead
        of letting it steal focus -- appropriate for Generate (meant to run
        unattended), never for Watch (the whole point is seeing the battle).

        timeout_seconds is falsy (None/0) to disable the watchdog entirely --
        appropriate for Watch, where a human is present and slow text/battle
        animations can legitimately run well past any fixed bound. Generate
        (headless, unattended) still wants a real timeout as its only
        defense against a genuinely stuck process -- but when heartbeat_filename
        is also given, the timer resets on every heartbeat update instead of
        counting down from process start, so it's really a turn-stall timeout
        (same TurnStallTimeoutSeconds idea as run_tournament.ps1's watchdog):
        a legitimately slow-but-progressing battle on weak hardware won't get
        killed, only a turn that's genuinely stuck ever trips it.

        heartbeat_filename polls headless_boot.rb's per-round
        elo_turn_heartbeat.json (only written while $aiBenchmarkRunning,
        i.e. during Generate's AI-vs-AI battle -- Watch's playRecordedBattle
        never sets that flag, so pass None there rather than poll a file
        that will never update)."""
        if self.is_running():
            raise RuntimeError("A replay run is already in progress.")

        self._vendor_dir = vendor_dir
        self._result_filename = result_filename
        self._cancelled = False
        self._timed_out = False

        result_path = os.path.join(vendor_dir, result_filename)
        if os.path.exists(result_path):
            os.remove(result_path)

        self._heartbeat_path = os.path.join(vendor_dir, heartbeat_filename) if heartbeat_filename else None
        self._heartbeat_mtime = None
        if self._heartbeat_path and os.path.exists(self._heartbeat_path):
            os.remove(self._heartbeat_path)

        qenv = QProcessEnvironment.systemEnvironment()
        for key, value in env_vars.items():
            qenv.insert(key, value)

        self._process = QProcess(self)
        self._process.setWorkingDirectory(vendor_dir)
        self._process.setProcessEnvironment(qenv)
        self._process.setProgram(os.path.join(vendor_dir, "Game.exe"))
        if extra_args:
            self._process.setArguments(extra_args)
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
        if self._heartbeat_path:
            self._heartbeat_timer.start(HEARTBEAT_POLL_MS)
        self.started.emit()

    def cancel(self):
        if not self.is_running():
            return
        self._cancelled = True
        self._timer.stop()
        self._process.kill()

    def _poll_heartbeat(self):
        try:
            mtime = os.path.getmtime(self._heartbeat_path)
        except OSError:
            return
        if mtime == self._heartbeat_mtime:
            return
        self._heartbeat_mtime = mtime
        try:
            with open(self._heartbeat_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            # A poll can race the engine's write; the next tick picks up
            # the completed write since mtime will have moved on again.
            return
        if self._timer.isActive():
            self._timer.start()  # no-arg restart reuses the last interval -- turn-stall reset.
        self.heartbeat.emit(data)

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
        self._heartbeat_timer.stop()
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


def outcome_label(value, win_label="Trainer 1", loss_label="Trainer 2"):
    """Renders runBattle/playRecordedBattle's shared result scale: 1 =
    party1/trainer1 side wins, 2 = party2/trainer2 side wins, 5 = draw
    (matches results_lib.WIN/LOSS/DRAW -- no rescaling between raw replay
    results and RR-derived rows is needed). 0 is not a real outcome -- it's
    the engine's pre-battle sentinel, left in place if playback was
    cancelled in-game before a decision was ever reached."""
    return {1: f"{win_label} wins", 2: f"{loss_label} wins", 5: "Draw", 0: "Cancelled (no result)"}.get(
        value, f"Unknown result ({value!r})"
    )


def describe_result(result, trainer1_name="Trainer 1", trainer2_name="Trainer 2", hide_outcome=False):
    """Turns one of replay.rb/watch.rb's saved result JSONs (or one of
    ReplayRunner's own Cancelled/Timeout/Crash/MalformedResult shapes,
    which share the same ok/error_class/error_message keys) into a plain-
    English status report, replacing a raw json.dumps dump.

    hide_outcome drops the win/loss/draw line (still reports rounds/time,
    which don't spoil anything) -- for a bracket-triggered Generate, where
    printing the winner here would leak the result before the user watches
    it on the Bracket tab."""
    if not result.get("ok"):
        lines = [f"Failed: {result.get('error_class', 'Error')} -- {result.get('error_message', '(no message)')}"]
        backtrace = result.get("backtrace")
        if backtrace:
            lines.append("")
            lines.append("Backtrace:")
            lines.extend(backtrace)
        if result.get("stdout_tail"):
            lines.append("")
            lines.append("--- stdout tail ---")
            lines.append(result["stdout_tail"])
        if result.get("stderr_tail"):
            lines.append("")
            lines.append("--- stderr tail ---")
            lines.append(result["stderr_tail"])
        return "\n".join(lines)

    lines = ["Battle finished (result hidden)."] if hide_outcome else [
        outcome_label(result.get("result"), trainer1_name, trainer2_name)
    ]
    rounds = result.get("rounds")
    if rounds is not None:
        time_s = result.get("time_s")
        time_part = f", {time_s:.1f}s" if isinstance(time_s, (int, float)) else ""
        lines.append(f"{rounds + 1} rounds{time_part}")
    if result.get("saved_to"):
        lines.append(f"Saved to {result['saved_to']}")
    return "\n".join(lines)
