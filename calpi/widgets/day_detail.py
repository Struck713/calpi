"""US-09: the `day` screen. Every event of one day in full. Event text is always set with
set_text (never markup): server text is not trusted."""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from gi.repository import Gtk, Pango

from calpi.data import formatting, timeutil
from calpi.widgets.util import (exempt_scrollbars, is_refresh_key, set_text_if_changed, set_visible_if_changed,
                               trigger_refresh)

log = logging.getLogger("calpi.day_detail")


def _label(text: str, css: str, *, lines: int = 0, one_line: bool = False) -> Gtk.Label:
    lbl = Gtk.Label(xalign=0, hexpand=True, css_classes=[css], wrap=not one_line,
                    wrap_mode=Pango.WrapMode.WORD_CHAR)
    lbl.set_text(text)
    if one_line:
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_max_width_chars(1)
    elif lines:
        lbl.set_lines(lines)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
    return lbl


class DayDetail(Gtk.Box):
    def __init__(self, store, colors, navigator, month_view):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["screen", "day-detail"])
        self.store, self.colors, self.navigator, self.month_view = store, colors, navigator, month_view
        self.date: date | None = None
        self._built_key = None
        self._open_t0: float | None = None
        hdr = Gtk.CenterBox(css_classes=["header"])
        self.btn_back = Gtk.Button(label="← Back", css_classes=["nav-button"], focus_on_click=False)
        self.title = Gtk.Label(css_classes=["day-title"])
        self.subtitle = Gtk.Label(css_classes=["day-subtitle"])
        tbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tbox.append(self.title)
        tbox.append(self.subtitle)
        nav = Gtk.Box(spacing=16)
        self.btn_prev = Gtk.Button(label="‹", css_classes=["nav-button", "nav-arrow"], focus_on_click=False)
        self.btn_next = Gtk.Button(label="›", css_classes=["nav-button", "nav-arrow"], focus_on_click=False)
        nav.append(self.btn_prev)
        nav.append(self.btn_next)
        hdr.set_start_widget(self.btn_back)
        hdr.set_center_widget(tbox)
        hdr.set_end_widget(nav)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["day-list"])
        self.empty = Gtk.Label(label="No events", css_classes=["day-empty"], vexpand=True)
        self.scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroller.set_child(self.list)
        exempt_scrollbars(self.scroller)
        for w in (hdr, self.scroller, self.empty):
            self.append(w)
        self.btn_back.connect("clicked", lambda *_: self.navigator.back())
        self.btn_prev.connect("clicked", lambda *_: self.shift(-1))
        self.btn_next.connect("clicked", lambda *_: self.shift(+1))
        # US-09 D3: any day cell opens this screen (cells are created once by MonthView)
        for row in month_view.week_rows:
            for cell in row.cells:
                cell.activate_callback = self.open_day

    # --- navigation ---
    def open_day(self, d: date) -> None:
        self._open_t0 = time.perf_counter()
        self.navigator.show("day", date=d)

    def on_show(self, date: date | None = None, **_):
        if date is not None:
            self.date = date
        if self.date is None:
            self.date = timeutil.today()
        self._build(force=True)
        self.scroller.get_vadjustment().set_value(0)
        if self._open_t0 is not None:
            from calpi.widgets.month_view import _log_until_paint
            _log_until_paint("day_open", self._open_t0, self)
            self._open_t0 = None

    def on_hide(self):
        self._clear()                     # free the rows while hidden (memory, US-37)
        self._built_key = None

    def on_key(self, name: str, _state) -> bool:
        if is_refresh_key(name, _state):
            trigger_refresh(self)
        elif name == "BackSpace":
            self.navigator.back()
        elif name == "Left":
            self.shift(-1)
        elif name == "Right":
            self.shift(+1)
        else:
            return False                  # Escape: route_key goes back
        return True

    def shift(self, days: int) -> None:
        if self.date is None:
            return
        try:
            self.date += timedelta(days=days)
        except OverflowError:
            return
        if (self.date.year, self.date.month) != (self.month_view.year, self.month_view.month):
            self.month_view.show_month(self.date.year, self.date.month)
        self._build(force=True)
        self.scroller.get_vadjustment().set_value(0)

    def reload(self) -> None:
        if self.navigator.current == "day":
            self._build(force=False)

    # --- building ---
    def _clear(self) -> None:
        while (c := self.list.get_first_child()) is not None:
            self.list.remove(c)

    def _build(self, force: bool) -> None:
        tz = timeutil.display_tz()
        today = timeutil.today()
        key = (self.date, today, self.store.revision(), tz.key, formatting.time_format(),
               self.colors.hash)
        if not force and key == self._built_key:
            return
        self._built_key = key
        set_text_if_changed(self.title, formatting.long_date(self.date))
        word = formatting.relative_day_word(self.date, today) or ""
        set_text_if_changed(self.subtitle, word)
        set_visible_if_changed(self.subtitle, bool(word))
        names = {c.id: c.name for c in self.store.list_calendars()}
        events = self.store.events_for_days(self.date, self.date + timedelta(days=1), tz)
        self._clear()
        for e in events:
            self.list.append(self._row(e, tz, names.get(e.calendar_id, "")))
        set_visible_if_changed(self.empty, not events)
        set_visible_if_changed(self.scroller, bool(events))

    def _row(self, e, tz, cal_name: str) -> Gtk.Box:
        tentative = e.status == "TENTATIVE"
        row = Gtk.Box(css_classes=["event-row"] + (["tentative"] if tentative else []))
        marker = Gtk.Box(css_classes=["cal-marker", "bar", self.colors.css_class(e.calendar_id)])
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        time_text = formatting.time_range_text(e, self.date, tz)
        multi = formatting.multi_day_text(e, self.date, tz)
        if multi:
            time_text += " · " + multi
        body.append(_label(time_text, "event-time"))
        body.append(_label(e.summary or "(no title)", "event-title", lines=3))
        if e.location:
            body.append(_label(e.location, "event-meta", one_line=True))
        meta = cal_name + (" (tentative)" if tentative else "")
        if meta:
            body.append(_label(meta, "event-meta", one_line=True))
        notes = formatting.clean_description(e.description)
        if notes:
            body.append(_label(notes, "event-notes", lines=4))
        row.append(marker)
        row.append(body)
        return row
