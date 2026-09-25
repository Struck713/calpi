from __future__ import annotations

from datetime import date

from gi.repository import Gtk

from calpi.widgets.util import set_class, set_text_if_changed, set_visible_if_changed


class DayCell(Gtk.Box):
    """One day: background, border, day number. Click target for US-09."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True,
                         css_classes=["day-cell"])
        self.number = Gtk.Label(css_classes=["day-number"], halign=Gtk.Align.START,
                                valign=Gtk.Align.START)
        # The number row keeps its height (DAY_NUMBER_HEIGHT); the forecast (US-41) sits at its right.
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, valign=Gtk.Align.START)
        row.append(self.number)
        self.forecast = Gtk.Label(css_classes=["cell-forecast"], halign=Gtk.Align.END,
                                  valign=Gtk.Align.START, hexpand=True, visible=False,
                                  can_target=False)          # built once, hidden when empty
        row.append(self.forecast)
        self.append(row)
        self.date: date | None = None
        self.activate_callback = None          # US-09: called with the date on release inside the cell
        click = Gtk.GestureClick()
        click.set_button(0)                    # any button; touch is emulated as button 1
        click.connect("released", self._on_released)
        self.add_controller(click)

    def _on_released(self, _gesture, _n_press, x, y) -> None:
        if self.date is None or self.activate_callback is None:
            return
        if 0 <= x <= self.get_width() and 0 <= y <= self.get_height():
            self.activate_callback(self.date)

    def set_forecast(self, text: str) -> None:
        set_text_if_changed(self.forecast, text)
        set_visible_if_changed(self.forecast, bool(text))

    def set_day(self, d: date, *, in_month: bool, is_today: bool, is_weekend: bool) -> None:
        self.date = d
        set_text_if_changed(self.number, str(d.day))
        set_class(self, "other-month", not in_month)
        set_class(self, "today", is_today)
        set_class(self, "weekend", is_weekend)
