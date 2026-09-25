from __future__ import annotations

from datetime import date

from gi.repository import Gtk, Pango

from calpi.data import formatting
from calpi.data.layout import Line, WeekLayout
from calpi.widgets.calendar_colors import CalendarColors
from calpi.widgets.day_cell import DayCell
from calpi.widgets.util import pin_grid_columns, set_text_if_changed

# px. Must equal .day-cell padding-top + .day-number margin-top + min-height in style.css
# (4 + 4 + 44). Event content is placed below this line.
DAY_NUMBER_HEIGHT = 52
# Event slots. LINE_HEIGHT must equal min-height + vertical margins of .bar / .line / .more /
# .slot-spacer in style.css (23 + 1 + 1). CELL_HEIGHT = (1080 - header - weekday row) / 6
# (US-06 D1); verify on the Pi. CAPACITY is computed, never measured (US-07 D4).
LINE_HEIGHT = 25
CELL_HEIGHT = 152
CAPACITY = (CELL_HEIGHT - DAY_NUMBER_HEIGHT) // LINE_HEIGHT
POOL_LIMIT = 60


def _label(css: str) -> Gtk.Label:
    return Gtk.Label(css_classes=[css], xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                     max_width_chars=1, single_line_mode=True)


class LineWidget(Gtk.Box):
    """Dot + time + summary, built once and reused."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, css_classes=["line"], hexpand=True)
        self.dot = Gtk.Box(css_classes=["dot"], valign=Gtk.Align.CENTER)
        self.time = Gtk.Label(css_classes=["time"], xalign=0)
        self.summary = _label("summary")
        for w in (self.dot, self.time, self.summary):
            self.append(w)

    def set(self, line: Line, cal_class: str, other_month: bool) -> None:
        e = line.event
        set_text_if_changed(self.time, formatting.short_time(line.local_start))
        set_text_if_changed(self.summary, e.summary or "(no title)")
        classes = ["line", cal_class]
        if e.status == "TENTATIVE":
            classes.append("tentative")
        if other_month:
            classes.append("other-month")
        self.set_css_classes(classes)


class WeekRow(Gtk.Overlay):
    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, css_classes=["week-row"])
        self.cells_grid = Gtk.Grid(column_homogeneous=True, hexpand=True, vexpand=True)
        self.cells = [DayCell() for _ in range(7)]
        for i, c in enumerate(self.cells):
            self.cells_grid.attach(c, i, 0, 1, 1)
        self.set_child(self.cells_grid)
        # Layer for events. Non-targetable: clicks reach the DayCells.
        self.content = Gtk.Grid(column_homogeneous=True, hexpand=True, vexpand=True,
                                valign=Gtk.Align.START,
                                margin_top=DAY_NUMBER_HEIGHT, can_target=False,
                                css_classes=["week-content"])
        # Permanent zero-width spacers give every slot row its full height even when empty.
        for slot in range(CAPACITY):
            self.content.attach(Gtk.Box(css_classes=["slot-spacer"], can_target=False), 0, slot, 1, 1)
        pin_grid_columns(self.content, 7)
        self.add_overlay(self.content)
        self.set_clip_overlay(self.content, True)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.dates: list[date] = []
        self._pools: dict[str, list[Gtk.Widget]] = {"bar": [], "line": [], "more": []}
        self._used: dict[str, list[Gtk.Widget]] = {"bar": [], "line": [], "more": []}

    def set_week(self, dates: list[date], month: int, today: date) -> None:
        self.dates = dates
        for cell, d in zip(self.cells, dates):
            cell.set_day(d, in_month=(d.month == month), is_today=(d == today),
                         is_weekend=d.weekday() >= 5)

    # --- event rendering (widget pool, D7) ---
    def _release_all(self) -> None:
        for kind, used in self._used.items():
            pool = self._pools[kind]
            for w in used:
                self.content.remove(w)
                if len(pool) < POOL_LIMIT:
                    pool.append(w)
            used.clear()

    def _take(self, kind: str) -> Gtk.Widget:
        pool = self._pools[kind]
        if pool:
            w = pool.pop()
        elif kind == "line":
            w = LineWidget()
        else:
            w = _label(kind)
            w.set_can_target(False)
        self._used[kind].append(w)
        return w

    def render(self, layout: WeekLayout, colors: CalendarColors, month: int) -> None:
        """Places widgets for a precomputed layout. No layout decisions here."""
        self._release_all()
        for bar, c0, c1 in layout.bars:
            w = self._take("bar")
            set_text_if_changed(w, bar.event.summary or "(no title)")
            classes = ["bar", colors.css_class(bar.event.calendar_id)]
            if bar.continues_before and c0 == bar.start_col:
                classes.append("cont-before")
            if bar.continues_after and c1 == bar.end_col:
                classes.append("cont-after")
            if bar.event.status == "TENTATIVE":
                classes.append("tentative")
            if all(self.dates[i].month != month for i in range(c0, c1 + 1)):
                classes.append("other-month")
            w.set_css_classes(classes)
            self.content.attach(w, c0, bar.lane, c1 - c0 + 1, 1)
        for col, day in enumerate(layout.days):
            other = self.dates[col].month != month
            for slot, line in day.placed_lines:
                w = self._take("line")
                w.set(line, colors.css_class(line.event.calendar_id), other)
                self.content.attach(w, col, slot, 1, 1)
            if day.hidden_count:
                m = self._take("more")
                set_text_if_changed(m, f"+{day.hidden_count} more")
                m.set_css_classes(["more", "other-month"] if other else ["more"])
                self.content.attach(m, col, day.more_slot, 1, 1)
