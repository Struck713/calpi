from __future__ import annotations

from gi.repository import Gtk

from calpi.widgets.util import set_text_if_changed


class Header(Gtk.CenterBox):
    """Title plus start/center/end slot boxes that later stories fill."""

    def __init__(self):
        super().__init__(css_classes=["header"])
        start = Gtk.Box(spacing=24)
        self.title = Gtk.Label(css_classes=["month-title"], xalign=0)
        self.start_slot = Gtk.Box(spacing=16)
        start.append(self.title)
        start.append(self.start_slot)
        self.center_slot = Gtk.Box(spacing=16)
        self.end_slot = Gtk.Box(spacing=16)
        self.set_start_widget(start)
        self.set_center_widget(self.center_slot)
        self.set_end_widget(self.end_slot)

    def set_title(self, text: str) -> None:
        set_text_if_changed(self.title, text)
