from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Callable

from gi.repository import Gtk

from calpi.data import monthmath, timeutil
from calpi.widgets.header import Header
from calpi.widgets.util import set_text_if_changed
from calpi.widgets.week_row import WeekRow

log = logging.getLogger("calpi.month_view")


class MonthView(Gtk.Box):
    def __init__(self, week_start: int = 0):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["screen", "month-view"])
        self.week_start = week_start
        self.month_changed_callbacks: list[Callable[[int, int], None]] = []
        self.header = Header()
        self.weekday_row = Gtk.Grid(column_homogeneous=True, css_classes=["weekday-row"])
        self.weekday_labels = [Gtk.Label(css_classes=["weekday-label"], hexpand=True)
                               for _ in range(7)]
        for i, lbl in enumerate(self.weekday_labels):
            self.weekday_row.attach(lbl, i, 0, 1, 1)
        weeks = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, homogeneous=True, vexpand=True,
                        css_classes=["weeks"])
        self.week_rows = [WeekRow() for _ in range(6)]
        for w in self.week_rows:
            weeks.append(w)
        for w in (self.header, self.weekday_row, weeks):
            self.append(w)
        t = timeutil.today()
        self.year, self.month = t.year, t.month
        self._apply_weekday_labels()
        self.show_month(t.year, t.month)

    def _apply_weekday_labels(self) -> None:
        for lbl, wd in zip(self.weekday_labels, monthmath.weekday_order(self.week_start)):
            set_text_if_changed(lbl, monthmath.WEEKDAY_SHORT[wd].upper())

    # --- public API (contracts) ---
    def show_month(self, year: int, month: int) -> None:
        self.year, self.month = year, month
        today = timeutil.today()
        dates = monthmath.month_grid_dates(year, month, self.week_start)
        for i, row in enumerate(self.week_rows):
            row.set_week(dates[i * 7:(i + 1) * 7], month, today)
        self.header.set_title(monthmath.month_title(year, month))
        log.info("month_view: showing %04d-%02d", year, month)
        for cb in list(self.month_changed_callbacks):
            try:
                cb(year, month)
            except Exception:
                log.exception("month_changed callback failed")

    def refresh_today(self) -> None:
        """Re-mark today (US-10 calls this at midnight)."""
        self.show_month(self.year, self.month)

    def set_week_start(self, week_start: int) -> None:
        if week_start == self.week_start:
            return
        self.week_start = week_start
        self._apply_weekday_labels()
        self.show_month(self.year, self.month)

    def visible_range(self) -> tuple[date, date]:
        """[first_day, end_day) currently displayed."""
        d = self.week_rows[0].dates[0]
        return d, d + timedelta(days=monthmath.GRID_DAYS)
