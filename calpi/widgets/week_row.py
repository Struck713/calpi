from __future__ import annotations

from datetime import date

from gi.repository import Gtk

from calpi.widgets.day_cell import DayCell

# px. Must equal .day-cell padding-top + .day-number margin-top + min-height in style.css
# (4 + 4 + 44). US-07 places event content below this line.
DAY_NUMBER_HEIGHT = 52


class WeekRow(Gtk.Overlay):
    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, css_classes=["week-row"])
        self.cells_grid = Gtk.Grid(column_homogeneous=True, hexpand=True, vexpand=True)
        self.cells = [DayCell() for _ in range(7)]
        for i, c in enumerate(self.cells):
            self.cells_grid.attach(c, i, 0, 1, 1)
        self.set_child(self.cells_grid)
        # Layer for US-07 (events). Non-targetable: clicks reach the DayCells.
        self.content = Gtk.Grid(column_homogeneous=True, hexpand=True, vexpand=True,
                                margin_top=DAY_NUMBER_HEIGHT, can_target=False,
                                css_classes=["week-content"])
        self.add_overlay(self.content)
        self.set_clip_overlay(self.content, True)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.dates: list[date] = []

    def set_week(self, dates: list[date], month: int, today: date) -> None:
        self.dates = dates
        for cell, d in zip(self.cells, dates):
            cell.set_day(d, in_month=(d.month == month), is_today=(d == today),
                         is_weekend=d.weekday() >= 5)
