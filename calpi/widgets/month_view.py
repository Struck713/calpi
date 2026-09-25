from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Callable

from gi.repository import Gtk

from calpi.data import monthmath, timeutil
from calpi.widgets.header import Header
from calpi.widgets.util import set_text_if_changed
from calpi.widgets.week_row import WeekRow

log = logging.getLogger("calpi.month_view")

MIN_YEAR, MAX_YEAR = 1970, 2100


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
        self.btn_prev = Gtk.Button(label="\u2039", css_classes=["nav-button", "nav-arrow"],
                                   focus_on_click=False)
        self.btn_today = Gtk.Button(label="Today", css_classes=["nav-button", "nav-today"],
                                    focus_on_click=False)
        self.btn_next = Gtk.Button(label="\u203a", css_classes=["nav-button", "nav-arrow"],
                                   focus_on_click=False)
        for b in (self.btn_prev, self.btn_today, self.btn_next):
            self.header.center_slot.append(b)
        self.btn_prev.connect("clicked", lambda *_: self.go_relative(-1, reason="button"))
        self.btn_next.connect("clicked", lambda *_: self.go_relative(+1, reason="button"))
        self.btn_today.connect("clicked", lambda *_: self.go_today(reason="button"))
        t = timeutil.today()
        self.year, self.month = t.year, t.month
        start = os.environ.get("CALPI_TEST_START_MONTH")     # test hook (US-10)
        if start:
            self.year, self.month = int(start[:4]), int(start[5:7])
        self._apply_weekday_labels()
        self.show_month(self.year, self.month)

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
        self._update_nav_sensitivity()
        for cb in list(self.month_changed_callbacks):
            try:
                cb(year, month)
            except Exception:
                log.exception("month_changed callback failed")

    def _update_nav_sensitivity(self) -> None:
        for btn, value in ((self.btn_prev, self.year > MIN_YEAR or self.month > 1),
                           (self.btn_next, self.year < MAX_YEAR or self.month < 12),
                           (self.btn_today, not self.is_current_month())):
            if btn.get_sensitive() != value:
                btn.set_sensitive(value)

    def is_current_month(self) -> bool:
        t = timeutil.today()
        return (self.year, self.month) == (t.year, t.month)

    def go_relative(self, delta: int, reason: str) -> None:
        y, m = monthmath.add_months(self.year, self.month, delta)
        if not (MIN_YEAR <= y <= MAX_YEAR):
            return
        self.show_month(y, m)
        log.info("nav: month -> %04d-%02d (reason=%s)", y, m, reason)

    def go_today(self, reason: str) -> None:
        if self.is_current_month():
            return
        t = timeutil.today()
        self.show_month(t.year, t.month)
        log.info("nav: month -> %04d-%02d (reason=%s)", t.year, t.month, reason)

    def on_key(self, name: str, _state) -> bool:
        """Called by KeyRouter (US-11) while the calendar screen is showing."""
        if name in ("Left", "Page_Up"):
            self.go_relative(-1, "key")
        elif name in ("Right", "Page_Down"):
            self.go_relative(+1, "key")
        elif name in ("Home", "t"):
            self.go_today("key")
        else:
            return False
        return True

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
