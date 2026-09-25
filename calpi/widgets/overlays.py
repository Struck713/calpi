"""In-app overlays: ConfirmDialog, Toast, BlockingOverlay (no separate windows, US-22).

All three are added to `window.overlay` once and reused. Z-order: whatever is
added later is on top; create them after the keyboard dock (US-21) so dialogs
sit above it.
"""
from __future__ import annotations

import logging
from typing import Callable

from gi.repository import GLib, Gtk

from calpi.widgets.util import set_class

log = logging.getLogger("calpi.overlays")


class ConfirmDialog(Gtk.Box):
    """Dim backdrop + centred panel. One instance; ask() while open replaces nothing (ignored)."""

    def __init__(self, window):
        super().__init__(css_classes=["modal-backdrop"], hexpand=True, vexpand=True)
        self.set_visible(False)
        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                             css_classes=["modal-panel"],
                             halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(css_classes=["modal-title"], wrap=True, xalign=0)
        self.body = Gtk.Label(css_classes=["modal-body"], wrap=True, max_width_chars=48, xalign=0)
        btns = Gtk.Box(spacing=24, halign=Gtk.Align.END)
        self.cancel = Gtk.Button(css_classes=["modal-button"])
        self.ok = Gtk.Button(css_classes=["modal-button"])
        btns.append(self.cancel)
        btns.append(self.ok)
        for w in (self.title, self.body, btns):
            self.panel.append(w)
        self.append(self.panel)
        self.cancel.connect("clicked", lambda *_: self._close(False))
        self.ok.connect("clicked", lambda *_: self._close(True))
        self._cb: Callable[[], None] | None = None
        window.overlay.add_overlay(self)

    @property
    def is_open(self) -> bool:
        return self.get_visible()

    def ask(self, title: str, body: str, confirm_label: str, on_confirm: Callable[[], None],
            destructive: bool = False, cancel_label: str = "Cancel") -> bool:
        if self.is_open:
            log.warning("confirm dialog already open; ignoring %r", title)
            return False
        self.title.set_text(title)
        self.body.set_text(body)
        self.ok.set_label(confirm_label)
        self.cancel.set_label(cancel_label)
        set_class(self.ok, "destructive", destructive)
        self._cb = on_confirm
        self.set_visible(True)
        self.cancel.grab_focus()          # Enter never confirms a destructive action by accident
        return True

    def cancel_dialog(self) -> None:
        if self.is_open:
            self._close(False)

    def _close(self, confirmed: bool) -> None:
        self.set_visible(False)
        cb, self._cb = self._cb, None
        if confirmed and cb:
            try:
                cb()
            except Exception:
                log.exception("confirm callback failed")


class Toast(Gtk.Label):
    """Bottom-centre message that clears itself. Never targetable."""

    def __init__(self, window):
        super().__init__(css_classes=["toast"], halign=Gtk.Align.CENTER, valign=Gtk.Align.END,
                         margin_bottom=40, can_target=False, can_focus=False)
        self.set_visible(False)
        self._timer = 0
        window.overlay.add_overlay(self)

    def show_text(self, text: str, seconds: float = 4) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
        self.set_text(text)
        self.set_visible(True)
        self._timer = GLib.timeout_add(int(seconds * 1000), self._expire)

    def _expire(self) -> bool:
        self._timer = 0
        self.set_visible(False)
        return GLib.SOURCE_REMOVE


class BlockingOverlay(Gtk.Box):
    """Full-screen "please wait" panel with static text and an optional Cancel button."""

    def __init__(self, window):
        super().__init__(css_classes=["modal-backdrop", "blocking"], hexpand=True, vexpand=True)
        self.set_visible(False)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=32,
                        css_classes=["modal-panel"], halign=Gtk.Align.CENTER,
                        valign=Gtk.Align.CENTER)
        self.label = Gtk.Label(css_classes=["modal-title"], wrap=True)
        self.cancel = Gtk.Button(label="Cancel", css_classes=["modal-button"],
                                 halign=Gtk.Align.CENTER)
        self.cancel.set_visible(False)
        self.cancel.connect("clicked", self._on_cancel)
        panel.append(self.label)
        panel.append(self.cancel)
        self.append(panel)
        self._on_cancel_cb: Callable[[], None] | None = None
        window.overlay.add_overlay(self)

    @property
    def is_open(self) -> bool:
        return self.get_visible()

    def show(self, text: str, on_cancel: Callable[[], None] | None = None) -> None:
        self.label.set_text(text)
        self._on_cancel_cb = on_cancel
        self.cancel.set_visible(on_cancel is not None)
        self.set_visible(True)
        if on_cancel is not None:
            self.cancel.grab_focus()

    def hide(self) -> None:
        self.set_visible(False)
        self._on_cancel_cb = None

    def _on_cancel(self, *_):
        cb = self._on_cancel_cb
        self.hide()
        if cb:
            cb()
