"""The wake catcher (US-30 D4): an invisible, topmost layer shown while the screen is in its night
state. The first touch/click only wakes the screen; nothing underneath sees it.

It must be the LAST overlay added to `window.overlay`: add any new overlay before it."""
from __future__ import annotations

import logging

from gi.repository import GLib, Gtk

log = logging.getLogger("calpi.wake")


class WakeCatcher(Gtk.Box):
    def __init__(self, window):
        super().__init__(hexpand=True, vexpand=True, can_target=True, visible=False,
                         css_classes=["wake-catcher"])
        self.on_wake = lambda: None
        self._window = window
        self._down = False
        self._want = False
        g = Gtk.GestureClick()
        g.set_button(0)
        g.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        g.connect("pressed", self._pressed)
        g.connect("released", self._released)
        g.connect("cancel", self._released)
        self.add_controller(g)
        window.overlay.add_overlay(self)

    def _pressed(self, gesture, *_a) -> None:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._down = True
        try:
            self.on_wake()
        except Exception:
            log.exception("wake failed")

    def _released(self, *_a) -> None:
        self._down = False
        if not self._want:
            self.set_visible(False)

    def set_active(self, active: bool) -> None:
        """Show/hide. Hiding waits for the release of a press in progress, so it is swallowed."""
        self._want = active
        if active:
            ov = self._window.overlay
            if ov.get_last_child() is not self:      # something was added above us since: go back on top
                ov.remove_overlay(self)
                ov.add_overlay(self)
            self.set_visible(True)
            self._window.set_focus(None)          # a focused button must not react to Space/Enter
        elif not self._down:
            self.set_visible(False)
        else:
            GLib.timeout_add(600, self._force_hide)      # safety if no release ever arrives

    def _force_hide(self):
        if not self._want:
            self._down = False
            self.set_visible(False)
        return GLib.SOURCE_REMOVE
