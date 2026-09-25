from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta
from typing import Callable

from gi.repository import Gtk

from calpi.data import formatting, layout, monthmath, timeutil
from calpi.weather.client import daily_text
from calpi.widgets.calendar_colors import CalendarColors
from calpi.widgets.header import Header
from calpi.widgets.problem_banner import ProblemBanner
from calpi.widgets.util import is_refresh_key, set_text_if_changed, trigger_refresh
from calpi.widgets.view_switcher import ViewSwitcher
from calpi.widgets.week_row import CAPACITY, WeekRow

log = logging.getLogger("calpi.month_view")

MIN_YEAR, MAX_YEAR = 1970, 2100


class MonthView(Gtk.Box):
    def __init__(self, week_start: int = 0):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["screen", "month-view"])
        self.week_start = week_start
        self.store = None                 # EventStore, set by attach_store (US-07)
        self.colors: CalendarColors | None = None
        self._last_key = None
        self._forecast = None             # dict[date, Daily] | None (US-41)
        self.month_changed_callbacks: list[Callable[[int, int], None]] = []
        self.header = Header()
        self.switcher = ViewSwitcher("month")          # US-39
        self.header.start_slot.append(self.switcher)
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
        self.problem_banner = ProblemBanner()            # US-38: shares the weekday row's slot (D4)
        for w in (self.header, self.weekday_row, self.problem_banner, weeks):
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
        self.btn_settings = Gtk.Button(label="\u2699", css_classes=["nav-button", "header-icon"],
                                       focus_on_click=False)       # US-22: far right
        self.btn_settings.connect("clicked", lambda *_: self.open_settings())
        self.header.end_slot.append(self.btn_settings)
        t = timeutil.today()
        self.year, self.month = t.year, t.month
        start = os.environ.get("CALPI_TEST_START_MONTH")     # test hook (US-10)
        if start:
            self.year, self.month = int(start[:4]), int(start[5:7])
        self._apply_weekday_labels()
        self.show_month(self.year, self.month)

    def set_banner_visible(self, on: bool) -> None:
        """US-38: the banner replaces the weekday-name row (same slot height, so the grid doesn't move)."""
        if self.weekday_row.get_visible() == on:
            self.weekday_row.set_visible(not on)

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
        self._apply_forecast()
        log.info("month_view: showing %04d-%02d", year, month)
        self._update_nav_sensitivity()
        for cb in list(self.month_changed_callbacks):
            try:
                cb(year, month)
            except Exception:
                log.exception("month_changed callback failed")

    def set_forecast(self, forecast) -> None:
        """US-41: dict[date, Daily] (or None to clear). Only cells whose text changes are touched."""
        self._forecast = forecast
        self._apply_forecast()

    def _apply_forecast(self) -> None:
        fc = self._forecast
        for row in self.week_rows:
            for cell in row.cells:
                d = fc.get(cell.date) if fc and cell.date is not None else None
                cell.set_forecast(daily_text(d) if d is not None else "")

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

    # view-switcher contract (US-39, see view_switcher.py)
    def anchor_date(self) -> date:
        return timeutil.today() if self.is_current_month() else date(self.year, self.month, 1)

    def show_date(self, d: date) -> None:
        self.show_month(d.year, d.month)

    def open_settings(self) -> None:
        root = self.get_root()
        if root is not None:
            root.navigator.show("settings")

    def on_key(self, name: str, _state) -> bool:
        """Called by KeyRouter (US-11) while the calendar screen is showing."""
        if is_refresh_key(name, _state):
            trigger_refresh(self)
            return True
        if name in ("Left", "Page_Up"):
            self.go_relative(-1, "key")
        elif name in ("Right", "Page_Down"):
            self.go_relative(+1, "key")
        elif name in ("Home", "t"):
            self.go_today("key")
        elif name == "s":
            self.open_settings()
        elif name == "w":
            root = self.get_root()
            if root is not None and hasattr(root, "show_view"):
                root.show_view("week", reason="key")
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

    # --- events (US-07) ---
    def attach_store(self, store) -> None:
        self.store = store
        self.colors = CalendarColors()
        self.month_changed_callbacks.append(lambda _y, _m: self.reload(force=True))
        self.reload(force=True)

    def reload(self, force: bool = False) -> None:
        """Redraw events. Skipped when nothing relevant changed (unless force)."""
        if self.store is None:
            return
        t0 = time.perf_counter()
        tz = timeutil.display_tz()
        self.colors.update(self.store.list_calendars(include_hidden=True))   # US-26: hidden ones keep a class for settings dots
        key = (self.store.revision(), self.year, self.month, tz.key, self.week_start,
               formatting.time_format(), self.colors.hash)
        if not force and key == self._last_key:
            return
        first, end = self.visible_range()
        events = self.store.events_for_days(first, end, tz)
        for row in self.week_rows:
            row.render(layout.layout_week(row.dates, events, tz, CAPACITY), self.colors, self.month)
        self._last_key = key
        _log_until_paint("month_render", t0, self)


def _log_until_paint(name: str, t0: float, widget: Gtk.Widget) -> None:
    """Logs 'perf: <name> NN ms' when the next frame is painted (US-36 may move this to perf.py)."""
    level = logging.INFO if os.environ.get("CALPI_PERF") == "1" else logging.DEBUG
    if not log.isEnabledFor(level):
        return
    clock = widget.get_frame_clock()
    if clock is None:
        log.log(level, "perf: %s %.1f ms (unpainted)", name, (time.perf_counter() - t0) * 1000)
        return
    handler = []

    def on_paint(c):
        c.disconnect(handler[0])
        log.log(level, "perf: %s %.1f ms", name, (time.perf_counter() - t0) * 1000)

    handler.append(clock.connect("after-paint", on_paint))
