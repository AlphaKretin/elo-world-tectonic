"""Windows-only helper for keeping a spawned Game.exe window from stealing
focus/obscuring the viewer during unattended runs (vendor compile, headless
replay generation) -- as opposed to Watch, where popping the window in the
foreground is the whole point, so this is never applied there.
"""
import sys

from PySide6.QtCore import QObject, QTimer

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32

    _HWND_BOTTOM = 1
    _SWP_NOMOVE = 0x0002
    _SWP_NOSIZE = 0x0001
    _SWP_NOACTIVATE = 0x0010

    def _find_window_for_pid(pid):
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _enum_proc(hwnd, _lparam):
            owner_pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            if owner_pid.value == pid and _user32.IsWindowVisible(hwnd):
                found.append(hwnd)
                return False
            return True

        _user32.EnumWindows(_enum_proc, 0)
        return found[0] if found else None

    def send_window_behind(pid):
        hwnd = _find_window_for_pid(pid)
        if hwnd is None:
            return False
        _user32.SetWindowPos(hwnd, _HWND_BOTTOM, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
        return True

else:

    def send_window_behind(pid):
        return False


class BackgroundWindowSuppressor(QObject):
    """Polls for a just-launched process's top-level window and sends it to
    the back of the Z-order the moment it appears, then re-raises the
    viewer's own window so keyboard focus stays with the app instead of the
    game window that briefly grabbed it on creation."""

    def __init__(self, get_pid, refocus_widget, parent=None, poll_ms=100, timeout_ms=8000):
        super().__init__(parent)
        self._get_pid = get_pid
        self._refocus_widget = refocus_widget
        self._poll_ms = poll_ms
        self._elapsed_ms = 0
        self._timeout_ms = timeout_ms
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(poll_ms)

    def _poll(self):
        self._elapsed_ms += self._poll_ms
        pid = self._get_pid()
        if pid and send_window_behind(pid):
            if self._refocus_widget is not None:
                self._refocus_widget.raise_()
                self._refocus_widget.activateWindow()
            self._timer.stop()
            return
        if self._elapsed_ms >= self._timeout_ms:
            self._timer.stop()
