"""Single button whose label ("Generate"/"Watch") and click behavior depend
on whether a replay already exists on disk for a given slug -- the shape
Browse and Trainers tabs' match-action buttons converged on independently.
Bracket tab's per-row buttons additionally layer a "Skip" state and best-
of-N attempt logic on top of this, so they stay bespoke rather than being
squeezed into this widget; this only covers the simpler "one match, one
button" case both other tabs share exactly.

Also owns a vendor_blocked flag: Generate/Watch both actually launch
Game.exe, so a click here must be refused outright -- not just deferred to
the destination tab's own is_valid() check -- while the vendor download/
compile is still running and could have Game.exe open concurrently. See
MainWindow._set_tabs_blocked, which calls set_vendor_blocked on every tab
holding one of these alongside disabling the Generate/Watch tabs themselves.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton

from app import replay_env

BLOCKED_TOOLTIP = "Waiting for the game files to finish downloading/compiling..."


class ReplayActionButton(QPushButton):
    generate_requested = Signal(dict)
    watch_requested = Signal(str, dict)

    def __init__(self, replay_dir, parent=None):
        super().__init__("Generate", parent)
        self._replay_dir = replay_dir
        self._slug = None
        self._payload = None
        self._dat_path = None
        self._vendor_blocked = False
        self.setEnabled(False)
        self.clicked.connect(self._on_clicked)

    def set_vendor_blocked(self, blocked):
        self._vendor_blocked = blocked
        self._apply_enabled()

    def refresh(self, slug, payload):
        """slug/payload None clears the button back to disabled/"Generate"
        (e.g. no row selected). payload is whatever dict Generate should
        hand off (trainer1/trainer2/seed/format/output_name)."""
        self._slug = slug
        self._payload = payload
        self.recheck()

    def recheck(self):
        """Re-does the on-disk replay lookup for the current slug without
        needing a new payload -- for a hand-off finishing (Generate/Watch)
        while this row's selection/data hasn't otherwise changed."""
        self._dat_path = replay_env.find_existing_replay(self._replay_dir, self._slug) if self._slug else None
        self.setText("Watch" if self._dat_path else "Generate")
        self._apply_enabled()

    def matches_slug(self, name):
        return self._slug is not None and name == self._slug

    def _apply_enabled(self):
        self.setEnabled(self._slug is not None and not self._vendor_blocked)
        self.setToolTip(BLOCKED_TOOLTIP if self._vendor_blocked else "")

    def _on_clicked(self):
        if self._dat_path:
            self.watch_requested.emit(self._dat_path, {})
        elif self._payload is not None:
            self.generate_requested.emit(self._payload)
