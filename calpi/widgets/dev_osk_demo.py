"""Dev-only demo screen for the on-screen keyboard (CALPI_DEV_OSK=1)."""
from __future__ import annotations

from gi.repository import Gtk

from calpi.widgets.keyboard import make_password_field


class DevOskDemo(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16, css_classes=["screen"],
                         valign=Gtk.Align.START)
        self.set_margin_top(32); self.set_margin_start(48); self.set_margin_end(48)
        kb = window.keyboard
        self._lengths = []
        self.email = Gtk.Entry(placeholder_text="email")
        pw_box, self.password, _t = make_password_field()
        self.url = Gtk.Entry(placeholder_text="url")
        for title, widget, entry, purpose, done in (
                ("Email", self.email, self.email, "email", "Next"),
                ("Password", pw_box, self.password, "password", "Next"),
                ("URL", self.url, self.url, "url", "Done")):
            row = Gtk.Box(spacing=16)
            row.append(Gtk.Label(label=title, width_chars=10, xalign=0))
            row.append(widget)
            widget.set_hexpand(True)
            n = Gtk.Label(label="0")
            row.append(n)
            entry.connect("changed", lambda e, n=n: n.set_text(f"{len(e.get_text())} chars"))
            kb.attach(entry, purpose, done)
            self.append(row)
