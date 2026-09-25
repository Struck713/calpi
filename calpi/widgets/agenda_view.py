"""Agenda view (US-40): a scrolling list of upcoming events grouped by day.

Item building is pure (calpi.data.agenda). The list is rebuilt only when the built agenda
differs from the one shown, so the per-minute refresh is cheap. Event text is set with
set_text only (untrusted).
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from gi.repository import Gtk, Pango

from calpi import perf
from calpi.data import agenda, formatting, timeutil
from calpi.widgets.calendar_colors import CalendarColors
from calpi.widgets.header import Header
from calpi.widgets.view_switcher import ViewSwitcher

log = logging.getLogger("calpi.agenda_view")


class AgendaView(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["screen", "agenda-view"])
        self.store = None
        self.colors: CalendarColors | None = None
        self._key = None
        self._shown: tuple | None = None
        self._row_days: dict[int, date] = {}
        self._minute_handle = None

        self.header = Header()
        self.header.title.add_css_class("week-title")
        self.header.set_title("Upcoming")
        self.switcher = ViewSwitcher("agenda")
        self.header.start_slot.append(self.switcher)
        self.btn_settings = Gtk.Button(label="⚙", css_classes=["nav-button", "header-icon"],
                                       focus_on_click=False)
        self.btn_settings.connect("clicked", lambda *_: self.open_settings())
        self.header.end_slot.append(self.btn_settings)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, activate_on_single_click=True,
                                   css_classes=["agenda-list"])
        self.listbox.connect("row-activated", self._on_row_activated)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                           kinetic_scrolling=True, child=self.listbox)
        self.empty = Gtk.Label(label=f"No upcoming events in the next {agenda.AGENDA_DAYS} days.",
                               css_classes=["day-empty"], vexpand=True, visible=False)
        for w in (self.header, self.scroller, self.empty):
            self.append(w)

    # ---------------------------------------------------------------- view contract
    def anchor_date(self) -> date:
        return timeutil.today()

    def show_date(self, _d: date) -> None:
        """The agenda always starts now; switching views only resets the scroll position."""
        self.reload(force=True)
        self.scroll_top()

    def go_today(self, reason: str) -> None:
        self.reload(force=True)
        self.scroll_top()
        log.info("nav: agenda top (reason=%s)", reason)

    def refresh_today(self) -> None:
        self.reload(force=True)

    def scroll_top(self) -> None:
        self.scroller.get_vadjustment().set_value(0)

    def open_settings(self) -> None:
        root = self.get_root()
        if root is not None:
            root.navigator.show("settings")

    def on_show(self, **_params) -> None:
        self.reload(force=True)
        self.scroll_top()
        if self._minute_handle is None:
            clock = self._clock()
            if clock is not None:
                self._minute_handle = clock.subscribe_minute(lambda *_a: self.reload())

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

    def on_key(self, name: str, _state) -> bool:
        adj = self.scroller.get_vadjustment()
        if name in ("Down", "Up"):
            adj.set_value(adj.get_value() + (120 if name == "Down" else -120))
        elif name in ("Page_Down", "Page_Up"):
            adj.set_value(adj.get_value() + (1 if name == "Page_Down" else -1) * adj.get_page_size() * 0.9)
        elif name in ("Home", "t"):
            self.go_today("key")
        elif name == "m":
            root = self.get_root()
            if root is not None and hasattr(root, "show_view"):
                root.show_view("month", reason="key")
        elif name == "s":
            self.open_settings()
        elif name == "Escape":
            pass                      # top-level view: nothing to go back to
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
        now = timeutil.now()
        tz = timeutil.display_tz()
        self.colors.update(self.store.list_calendars(include_hidden=False))
        fmt = formatting.time_format()
        key = (self.store.revision(), now.date(), tz.key, fmt, self.colors.hash,
               now.hour, now.minute)
        if not force and key == self._key:
            return
        self._key = key
        today = now.date()
        events = self.store.events_for_days(
            today, today + timedelta(days=agenda.AGENDA_DAYS), tz)
        ag = agenda.build_agenda_full(events, now, tz)
        shown = (fmt, tz.key, self.colors.hash, today, ag)
        if shown == self._shown:
            return
        self._shown = shown
        self._rebuild(ag, today)
        perf.until_paint("agenda_render", self, t0)

    # ---------------------------------------------------------------- rows
    def _rebuild(self, ag: agenda.Agenda, today: date) -> None:
        # ListBox.remove_all() is GTK >= 4.12; the Pi (Bookworm) has 4.8
        while (c := self.listbox.get_first_child()) is not None:
            self.listbox.remove(c)
        self._row_days = {}
        has = bool(ag.groups)
        self.scroller.set_visible(has)
        self.empty.set_visible(not has)
        index = 0
        for day, items in ag.groups:
            self.listbox.append(self._heading_row(agenda.heading_text(day, today)))
            index += 1
            for it in items:
                self.listbox.append(self._item_row(it))
                self._row_days[index] = day
                index += 1
        if ag.more_after is not None:
            row = Gtk.ListBoxRow(activatable=False, selectable=False, css_classes=["agenda-more"])
            row.set_child(Gtk.Label(label=f"More events after {formatting.long_date(ag.more_after)}…",
                                    xalign=0, css_classes=["agenda-more-label"]))
            self.listbox.append(row)

    @staticmethod
    def _heading_row(text: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow(activatable=False, selectable=False, css_classes=["agenda-heading-row"])
        row.set_child(Gtk.Label(label=text, xalign=0, css_classes=["agenda-day-heading"]))
        return row

    def _item_row(self, it: agenda.AgendaItem) -> Gtk.ListBoxRow:
        e = it.event
        tentative = e.status == "TENTATIVE"
        classes = ["agenda-row"] + (["next"] if it.is_next else []) \
            + (["tentative"] if tentative else []) + (["ongoing"] if it.kind == "ongoing" else [])
        row = Gtk.ListBoxRow(css_classes=classes)
        box = Gtk.Box(spacing=0)
        box.append(Gtk.Box(css_classes=["agenda-dot", "bar", self.colors.css_class(e.calendar_id)],
                           valign=Gtk.Align.CENTER))
        time_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                           css_classes=["agenda-time-col"])
        time_col.append(Gtk.Label(label=it.time_text, xalign=0, css_classes=["agenda-time"]))
        if it.kind == "ongoing":
            time_col.append(Gtk.Label(label="Now", xalign=0, css_classes=["agenda-now-tag"]))
        box.append(time_col)
        text_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        title = (e.summary or "(no title)") + (" (tentative)" if tentative else "")
        text_col.append(Gtk.Label(label=title, xalign=0, wrap=True, lines=2, max_width_chars=1,
                                  ellipsize=Pango.EllipsizeMode.END, css_classes=["agenda-title"]))
        sub = " · ".join(x for x in (it.range_text, e.location.strip() if e.location else "") if x)
        if sub:
            text_col.append(Gtk.Label(label=sub, xalign=0, max_width_chars=1, single_line_mode=True,
                                      ellipsize=Pango.EllipsizeMode.END, css_classes=["agenda-sub"]))
        box.append(text_col)
        row.set_child(box)
        return row

    def _on_row_activated(self, _lb, row: Gtk.ListBoxRow) -> None:
        d = self._row_days.get(row.get_index())
        if d is None:
            return
        root = self.get_root()
        if root is not None and root.navigator.get("day") is not None:
            root.navigator.show("day", date=d)
