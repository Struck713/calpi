from __future__ import annotations

from datetime import date

from gi.repository import Gtk

from calpi.widgets.util import set_class, set_text_if_changed


class DayCell(Gtk.Box):
    """One day: background, border, day number. Click target for US-09."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True,
                         css_classes=["day-cell"])
        self.number = Gtk.Label(css_classes=["day-number"], halign=Gtk.Align.START,
                                valign=Gtk.Align.START)
        self.append(self.number)
        self.date: date | None = None

    def set_day(self, d: date, *, in_month: bool, is_today: bool, is_weekend: bool) -> None:
        self.date = d
        set_text_if_changed(self.number, str(d.day))
        set_class(self, "other-month", not in_month)
        set_class(self, "today", is_today)
        set_class(self, "weekend", is_weekend)
