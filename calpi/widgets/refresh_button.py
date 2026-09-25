"""Manual refresh button (US-19). Follows the engine state; usable in the header and in Settings (US-27)."""
from __future__ import annotations

import logging

from gi.repository import Gtk

log = logging.getLogger("calpi.refresh_button")


class RefreshButton(Gtk.Button):
    def __init__(self, app, label: str = "↻"):
        super().__init__(label=label, css_classes=["nav-button", "refresh-button"])
        self.app = app
        self._subscribed = False
        self.connect("clicked", lambda *_: self.app.trigger_manual_refresh())
        self.connect("realize", self._subscribe)
        self.connect("unrealize", self._unsubscribe)
        self._on_state(self._running())

    def _running(self) -> bool:
        return bool(self.app.sync is not None and self.app.sync.is_running)

    def _subscribe(self, *_):
        if self._subscribed or self.app.sync is None:
            return
        self._subscribed = True
        self._h_state = self.app.sync.state_callbacks.add(self._on_state)
        self._on_state(self._running())

    def _unsubscribe(self, *_):
        if self._subscribed:
            self._subscribed = False
            self.app.sync.state_callbacks.remove(self._h_state)

    def _on_state(self, running: bool) -> None:
        if self.get_sensitive() == running:          # insensitive while a sync is running
            self.set_sensitive(not running)
