"""Week view (US-39): day headers, all-day strip, and a cairo/Pango timeline (one DrawingArea).

Layout decisions live in calpi.data.week_layout; this module only draws and routes taps.
The timeline is redrawn only when data / week / size / settings change, plus once a minute
while the displayed week contains today (current-time line).
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import gi
from gi.repository import Gtk, Pango

gi.require_version("PangoCairo", "1.0")
from gi.repository import PangoCairo  # noqa: E402

from calpi import perf  # noqa: E402
from calpi.data import formatting, layout as month_layout, monthmath, timeutil, week_layout  # noqa: E402
from calpi.widgets.calendar_colors import CalendarColors  # noqa: E402
from calpi.widgets.header import Header  # noqa: E402
from calpi.widgets.swipe import attach_horizontal_swipe  # noqa: E402
from calpi.widgets.util import pin_grid_columns, set_class, set_text_if_changed  # noqa: E402
from calpi.widgets.view_switcher import ViewSwitcher  # noqa: E402

log = logging.getLogger("calpi.week_view")

GUTTER = 80
START_H, END_H = 7, 22
ALLDAY_ROW_H = 28
MIN_YEAR, MAX_YEAR = 1970, 2100
# Mirrors of the palette in style.css (cairo cannot read CSS colours cheaply).
BG = (0x10 / 255, 0x14 / 255, 0x18 / 255)
TEXT = (0xe8 / 255, 0xe8 / 255, 0xe8 / 255)
DIM = (0x9a / 255, 0xa4 / 255, 0xae / 255)
ACCENT = (0x4f / 255, 0x9d / 255, 0xff / 255)
FONT = "DejaVu Sans"


def _rgb(hexcolor: str) -> tuple[float, float, float]:
    c = formatting.valid_color(hexcolor)
    return tuple(int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))     # type: ignore[return-value]


def _round_rect(cr, x, y, w, h, r) -> None:
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


class WeekView(Gtk.Box):
    def __init__(self, week_start: int = 0):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["screen", "week-view"])
        self.week_start = week_start
        self.store = None
        self.colors: CalendarColors | None = None
        self.first_day: date = week_layout.week_start_of(timeutil.today(), week_start)
        self._events: list = []
        self._events_key = None
        self._layout_key = None
        self._layout: week_layout.WeekLayout | None = None
        self._rgb: dict[str, tuple] = {}
        self._rgb_hash = None
        self._texts: list[tuple] = []          # per block: (pango layout, text rgb)
        self._markers: list[tuple] = []        # (x, y, w, h, pango layout)
        self._minute_handle = None

        self.header = Header()
        self.header.title.add_css_class("week-title")
        self.switcher = ViewSwitcher("week")
        self.header.start_slot.append(self.switcher)
        self.btn_prev = Gtk.Button(label="‹", css_classes=["nav-button", "nav-arrow"],
                                   focus_on_click=False)
        self.btn_today = Gtk.Button(label="Today", css_classes=["nav-button", "nav-today"],
                                    focus_on_click=False)
        self.btn_next = Gtk.Button(label="›", css_classes=["nav-button", "nav-arrow"],
                                   focus_on_click=False)
        for b in (self.btn_prev, self.btn_today, self.btn_next):
            self.header.center_slot.append(b)
        self.btn_prev.connect("clicked", lambda *_: self.go_relative(-1, "button"))
        self.btn_next.connect("clicked", lambda *_: self.go_relative(+1, "button"))
        self.btn_today.connect("clicked", lambda *_: self.go_today("button"))
        self.btn_settings = Gtk.Button(label="⚙", css_classes=["nav-button", "header-icon"],
                                       focus_on_click=False)
        self.btn_settings.connect("clicked", lambda *_: self.open_settings())
        self.header.end_slot.append(self.btn_settings)

        # day header row: gutter spacer + 7 labels (one gesture; column from x)
        self.day_row = Gtk.Box(css_classes=["week-dayrow"])
        self.day_row.append(Gtk.Box(width_request=GUTTER))
        grid = Gtk.Grid(column_homogeneous=True, hexpand=True)
        self.day_labels = [Gtk.Label(css_classes=["week-day-label"], hexpand=True) for _ in range(7)]
        for i, lbl in enumerate(self.day_labels):
            grid.attach(lbl, i, 0, 1, 1)
        self.day_row.append(grid)
        self._add_column_tap(self.day_row)

        # all-day strip: fixed 3 rows, bars/labels are pooled
        self.strip = Gtk.Box(css_classes=["week-allday"])
        self.strip.append(Gtk.Box(width_request=GUTTER))
        self.strip_grid = Gtk.Grid(column_homogeneous=True, hexpand=True)
        for r in range(week_layout.ALLDAY_CAPACITY):
            self.strip_grid.attach(Gtk.Box(css_classes=["week-allday-row"]), 0, r, 1, 1)
        pin_grid_columns(self.strip_grid, 7)
        self.strip.append(self.strip_grid)
        self._strip_used: list[Gtk.Label] = []
        self._strip_pool: list[Gtk.Label] = []
        self._add_column_tap(self.strip)

        self.timeline = Gtk.DrawingArea(hexpand=True, vexpand=True, css_classes=["week-timeline"])
        self.timeline.set_draw_func(self._draw)
        self.timeline.connect("resize", self._on_resize)
        click = Gtk.GestureClick()
        click.connect("released", self._on_timeline_click)
        self.timeline.add_controller(click)

        for w in (self.header, self.day_row, self.strip, self.timeline):
            self.append(w)
        attach_horizontal_swipe(self, lambda d: self.go_relative(d, "swipe"))   # US-35
        self._apply_header()

    # ---------------------------------------------------------------- helpers
    @property
    def dates(self) -> list[date]:
        return week_layout.week_dates(self.first_day)

    def _add_column_tap(self, widget: Gtk.Widget) -> None:
        click = Gtk.GestureClick()
        click.connect("released", lambda _g, _n, x, _y, w=widget: self._on_column_tap(w, x))
        widget.add_controller(click)

    def _on_column_tap(self, widget: Gtk.Widget, x: float) -> None:
        dw = (widget.get_width() - GUTTER) / 7
        if dw <= 0 or x < GUTTER:
            return
        i = int((x - GUTTER) // dw)
        if 0 <= i < 7:
            self.open_day(self.dates[i])

    def open_day(self, d: date) -> None:
        root = self.get_root()
        if root is not None and root.navigator.get("day") is not None:
            root.navigator.show("day", date=d)

    def open_settings(self) -> None:
        root = self.get_root()
        if root is not None:
            root.navigator.show("settings")

    # ---------------------------------------------------------------- header / navigation
    def _apply_header(self) -> None:
        dates = self.dates
        today = timeutil.today()
        self.header.set_title(week_layout.week_title(dates))
        for lbl, d in zip(self.day_labels, dates):
            set_text_if_changed(lbl, f"{monthmath.WEEKDAY_SHORT[d.weekday()]} {d.day}")
            set_class(lbl, "today", d == today)
            set_class(lbl, "weekend", d.weekday() >= 5)
        can_prev = self.first_day.year > MIN_YEAR
        can_next = self.first_day.year < MAX_YEAR
        for btn, value in ((self.btn_prev, can_prev), (self.btn_next, can_next),
                           (self.btn_today, not self.is_current_week())):
            if btn.get_sensitive() != value:
                btn.set_sensitive(value)

    def is_current_week(self) -> bool:
        return self.first_day == week_layout.week_start_of(timeutil.today(), self.week_start)

    def show_week(self, first_day: date) -> None:
        self.first_day = week_layout.week_start_of(first_day, self.week_start)
        log.info("week_view: showing week of %s", self.first_day.isoformat())
        self._apply_header()
        self.reload()

    def go_relative(self, delta: int, reason: str) -> None:
        try:
            nd = self.first_day + timedelta(weeks=delta)
        except OverflowError:
            return
        if not (MIN_YEAR <= nd.year <= MAX_YEAR):
            return
        self.show_week(nd)
        log.info("nav: week -> %s (reason=%s)", self.first_day, reason)

    def go_today(self, reason: str) -> None:
        if self.is_current_week():
            return
        self.show_week(timeutil.today())
        log.info("nav: week -> %s (reason=%s)", self.first_day, reason)

    # view-switcher contract (see view_switcher.py)
    def anchor_date(self) -> date:
        return timeutil.today() if self.is_current_week() else self.first_day

    def show_date(self, d: date) -> None:
        self.show_week(d)

    def set_week_start(self, week_start: int) -> None:
        if week_start == self.week_start:
            return
        anchor = self.anchor_date()
        self.week_start = week_start
        self.show_week(anchor)

    def refresh_today(self) -> None:
        """US-10 day change: re-mark today and reload."""
        self._apply_header()
        self.reload(force=True)

    def on_show(self, **_params) -> None:
        self._apply_header()
        self.reload()
        if self._minute_handle is None:
            clock = self._clock()
            if clock is not None:
                self._minute_handle = clock.subscribe_minute(self._on_minute)

    def on_hide(self) -> None:
        if self._minute_handle is not None:
            clock = self._clock()
            if clock is not None:
                clock.unsubscribe(self._minute_handle)
            self._minute_handle = None

    def _clock(self):
        root = self.get_root()
        app = root.get_application() if root is not None else None
        return getattr(app, "clock", None)

    def _on_minute(self, *_a) -> None:
        if self.is_current_week():
            self._apply_header()
            self.timeline.queue_draw()

    def on_key(self, name: str, _state) -> bool:
        if name in ("Left", "Page_Up"):
            self.go_relative(-1, "key")
        elif name in ("Right", "Page_Down"):
            self.go_relative(+1, "key")
        elif name in ("Home", "t"):
            self.go_today("key")
        elif name == "m":
            root = self.get_root()
            if root is not None and hasattr(root, "show_view"):
                root.show_view("month", reason="key")
        elif name == "s":
            self.open_settings()
        elif name == "Escape":
            pass                      # this is a top-level view: nothing to go back to
        else:
            return False
        return True

    # ---------------------------------------------------------------- data
    def attach_store(self, store, colors: CalendarColors) -> None:
        self.store = store
        self.colors = colors
        self.reload(force=True)

    def reload(self, force: bool = False) -> None:
        if self.store is None or self.colors is None:
            return
        t0 = time.perf_counter()
        tz = timeutil.display_tz()
        cals = self.store.list_calendars(include_hidden=True)   # US-26
        self.colors.update(cals)
        if self._rgb_hash != self.colors.hash:
            self._rgb = {c.id: _rgb(c.color) for c in cals}
            self._rgb_hash = self.colors.hash
        key = (self.store.revision(), self.first_day, tz.key, self.week_start,
               formatting.time_format(), self.colors.hash)
        if not force and key == self._events_key and self._layout is not None:
            return
        self._events = self.store.events_for_days(self.first_day, self.first_day + timedelta(days=7), tz)
        self._events_key = key
        self._rebuild(force=True)
        perf.until_paint("week_render", self, t0)

    def _on_resize(self, _area, _w, _h) -> None:
        self._rebuild()

    def _geometry(self) -> week_layout.Geometry | None:
        w, h = self.timeline.get_width(), self.timeline.get_height()
        if w <= GUTTER + 7 or h <= 100:
            return None
        return week_layout.Geometry(gutter=GUTTER, day_w=(w - GUTTER) / 7, top=0.0,
                                    hour_px=h / (END_H - START_H), start_h=START_H, end_h=END_H)

    def _rebuild(self, force: bool = False) -> None:
        if self._events_key is None:
            return
        geom = self._geometry()
        if geom is None:
            return
        key = (self._events_key, geom)
        if not force and key == self._layout_key:
            return
        tz = timeutil.display_tz()
        self._layout = week_layout.build(self.dates, self._events, tz, geom)
        self._layout_key = key
        self._make_texts(tz)
        self._render_strip()
        self.timeline.queue_draw()

    # ---------------------------------------------------------------- all-day strip
    def _render_strip(self) -> None:
        for lbl in self._strip_used:
            self.strip_grid.remove(lbl)
            if len(self._strip_pool) < 40:
                self._strip_pool.append(lbl)
        self._strip_used.clear()
        lay = self._layout.allday

        def take(css: list[str]) -> Gtk.Label:
            lbl = self._strip_pool.pop() if self._strip_pool else Gtk.Label(
                xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END, max_width_chars=1,
                single_line_mode=True, can_target=False)
            lbl.set_css_classes(css)
            self._strip_used.append(lbl)
            return lbl

        for bar, c0, c1 in lay.bars:
            lbl = take(["bar", self.colors.css_class(bar.event.calendar_id)]
                       + (["cont-before"] if bar.continues_before and c0 == bar.start_col else [])
                       + (["cont-after"] if bar.continues_after and c1 == bar.end_col else [])
                       + (["tentative"] if bar.event.status == "TENTATIVE" else []))
            set_text_if_changed(lbl, bar.event.summary or "(no title)")
            self.strip_grid.attach(lbl, c0 + 0, bar.lane, c1 - c0 + 1, 1)
        for col, day in enumerate(lay.days):
            if day.hidden_count:
                lbl = take(["week-more"])
                set_text_if_changed(lbl, f"+{day.hidden_count} more")
                self.strip_grid.attach(lbl, col, day.more_slot, 1, 1)

    # ---------------------------------------------------------------- timeline drawing
    def _pango(self, text: str, px: float, width: float | None, lines: int = 1, bold: bool = False
               ) -> Pango.Layout:
        lay = self.timeline.create_pango_layout(text)
        fd = Pango.FontDescription()
        fd.set_family(FONT)
        fd.set_absolute_size(px * Pango.SCALE)
        if bold:
            fd.set_weight(Pango.Weight.BOLD)
        lay.set_font_description(fd)
        if width is not None:
            lay.set_width(int(width * Pango.SCALE))
            lay.set_wrap(Pango.WrapMode.WORD_CHAR)
            lay.set_ellipsize(Pango.EllipsizeMode.END)
            lay.set_height(-lines)
        return lay

    def _make_texts(self, tz) -> None:
        self._texts = []
        for b in self._layout.blocks:
            e = b.segment.event
            title = e.summary or "(no title)"
            if not b.segment.cont_before:
                title = f"{formatting.short_time(e.start.astimezone(tz))} {title}"
            lines = max(1, int((b.h - 6) // 20))
            lay = self._pango(title, 17, b.w - 12, lines)
            hexc = self._hex_for(e.calendar_id)
            self._texts.append((lay, _rgb(formatting.contrast_text(hexc))))
        g = self._layout.geom
        self._markers = []
        for i in range(7):
            x = g.x_of_day(i)
            if self._layout.earlier[i]:
                lay = self._pango(f"↑ {self._layout.earlier[i]} earlier", 16, None)
                self._markers.append((x, g.top, lay))
            if self._layout.later[i]:
                lay = self._pango(f"↓ {self._layout.later[i]} later", 16, None)
                self._markers.append((x, g.bottom - week_layout.MARKER_H, lay))

    def _hex_for(self, calendar_id: str) -> str:
        rgb = self._rgb.get(calendar_id)
        if rgb is None:
            return "#9aa4ae"
        return "#%02x%02x%02x" % tuple(round(v * 255) for v in rgb)

    def _draw(self, _area, cr, width: int, height: int) -> None:
        cr.set_source_rgb(*BG)
        cr.paint()
        lay = self._layout
        if lay is None:
            return
        g = lay.geom
        today = timeutil.today()
        dates = lay.week_dates
        # weekend / today column backgrounds
        for i, d in enumerate(dates):
            if d == today:
                cr.set_source_rgba(*ACCENT, 0.07)
            elif d.weekday() >= 5:
                cr.set_source_rgba(1, 1, 1, 0.025)
            else:
                continue
            cr.rectangle(g.x_of_day(i), 0, g.day_w, height)
            cr.fill()
        # hour lines + labels
        cr.set_line_width(1)
        for h in range(g.start_h, g.end_h + 1):
            y = round(g.y_of_min(h * 60)) + 0.5
            cr.set_source_rgba(*TEXT, 0.10)
            cr.move_to(g.gutter, y)
            cr.line_to(width, y)
            cr.stroke()
            if h < g.end_h:
                lbl = self._hour_label(h)
                cr.set_source_rgb(*DIM)
                cr.move_to(8, y + 2)
                PangoCairo.show_layout(cr, lbl)
        # day separators
        cr.set_source_rgba(*TEXT, 0.08)
        for i in range(8):
            x = round(g.x_of_day(i)) + 0.5
            cr.move_to(x, 0)
            cr.line_to(x, height)
        cr.stroke()
        # blocks
        for b, (tl, trgb) in zip(lay.blocks, self._texts):
            rgb = self._rgb.get(b.segment.event.calendar_id, _rgb("#9aa4ae"))
            tentative = b.segment.event.status == "TENTATIVE"
            _round_rect(cr, b.x + 1, b.y + 1, b.w - 1, b.h - 2, 6)
            if tentative:
                cr.set_source_rgba(*rgb, 0.45)
                cr.fill_preserve()
                cr.set_source_rgb(*rgb)
                cr.set_line_width(2)
                cr.stroke()
                trgb = TEXT
            else:
                cr.set_source_rgb(*rgb)
                cr.fill()
            cr.save()
            cr.rectangle(b.x + 4, b.y + 2, b.w - 8, b.h - 4)
            cr.clip()
            cr.set_source_rgb(*trgb)
            cr.move_to(b.x + 7, b.y + 4)
            PangoCairo.show_layout(cr, tl)
            cr.restore()
            if b.clipped_top or b.clipped_bottom:
                cr.set_source_rgb(*trgb)
                if b.clipped_top:
                    self._arrow(cr, b.x + b.w - 14, b.y + 8, up=True)
                if b.clipped_bottom:
                    self._arrow(cr, b.x + b.w - 14, b.y + b.h - 8, up=False)
        # earlier / later markers
        for x, y, ml in self._markers:
            cr.set_source_rgb(*ACCENT)
            cr.move_to(x + 8, y + 3)
            PangoCairo.show_layout(cr, ml)
        # current-time line
        now = timeutil.now()
        if now.date() in dates:
            minute = now.hour * 60 + now.minute
            if g.start_h * 60 <= minute < g.end_h * 60:
                i = dates.index(now.date())
                y = round(g.y_of_min(minute)) + 0.5
                cr.set_source_rgb(*ACCENT)
                cr.set_line_width(2)
                cr.move_to(g.x_of_day(i), y)
                cr.line_to(g.x_of_day(i) + g.day_w, y)
                cr.stroke()
                cr.arc(g.x_of_day(i), y, 5, 0, 6.2832)
                cr.fill()

    @staticmethod
    def _arrow(cr, x, y, up: bool) -> None:
        d = -5 if up else 5
        cr.move_to(x - 6, y - d)
        cr.line_to(x, y + d)
        cr.line_to(x + 6, y - d)
        cr.close_path()
        cr.fill()

    def _hour_label(self, h: int) -> Pango.Layout:
        cache = self.__dict__.setdefault("_hour_labels", {})
        key = (h, formatting.time_format())
        lay = cache.get(key)
        if lay is None:
            if len(cache) > 60:
                cache.clear()
            text = formatting.long_time(datetime(2000, 1, 1, h, 0))
            lay = cache[key] = self._pango(text, 16, None)
        return lay

    # ---------------------------------------------------------------- taps
    def _on_timeline_click(self, _g, _n, x: float, y: float) -> None:
        if self._layout is None:
            return
        hit = week_layout.hit_test(self._layout, x, y)
        if hit is not None:
            self.open_day(hit[1])
