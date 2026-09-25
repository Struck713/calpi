"""Preferences section: time zone, first day of the week, time format (US-28).

`PreferencesPanel(ctx)` is reusable by the setup wizard (ctx.mode == "wizard": no toasts).
"""
from __future__ import annotations

import logging

from gi.repository import Gtk

from calpi.data import timeutil
from calpi.data.settings_store import K_DEFAULT_VIEW, K_TIME_FORMAT, K_TIMEZONE, K_WEEK_START
from calpi.system import timezone as tzmod
from calpi.tasks import run_in_thread
from calpi.widgets.settings.registry import SectionSpec, register_section
from calpi.widgets.settings.rows import (ChoiceRow, ListPickerPage, ListPickerRow,
                                         SettingsGroup)

log = logging.getLogger("calpi.settings.preferences")


class _ZonePage(ListPickerPage):
    """Region list; typing in the search box switches to matching cities from every region."""

    def __init__(self, index, on_pick, current, keyboard):
        items = [(("region", r), r) for r in index.regions]
        items += [(("zone", z), f"{tzmod.city_label(z)} — {tzmod.region_of(z)}   {index.offsets[z]}")
                  for z in index.zones if "/" in z]
        super().__init__(items, on_pick, current=("zone", current) if current else None,
                         search=True, keyboard=keyboard)

    def _filter(self, row) -> bool:
        kind = self._values[row][0][0]
        if not self._query:
            return kind == "region"
        return kind == "zone" and self._query in self._values[row][1]


class PreferencesPanel(Gtk.Box):
    def __init__(self, ctx):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.ctx = ctx
        self.app = ctx.app
        self._depth = 0
        settings = self.app.settings
        g = SettingsGroup("Region and time")
        self.tz_row = g.add(ListPickerRow("Time zone", self._tz_label(None), self._open_regions))
        g.add(ChoiceRow("First day of the week",
                        [(0, "Monday"), (6, "Sunday"), (5, "Saturday")],
                        settings=settings, key=K_WEEK_START))
        g.add(ChoiceRow("Time format",
                        [("24h", "24-hour (14:30)"), ("12h", "12-hour (2:30 PM)")],
                        settings=settings, key=K_TIME_FORMAT))
        g.add(ChoiceRow("Start with",
                        [("month", "Month"), ("week", "Week"), ("agenda", "Agenda")],
                        settings=settings, key=K_DEFAULT_VIEW))
        self.append(g)
        self._token = settings.subscribe(K_TIMEZONE, lambda _k, _v: self._refresh_label())
        self.connect("map", lambda *_: self._refresh_label())
        self.connect("destroy", lambda *_: settings.unsubscribe(self._token))
        self._loading = False

    # ---- labels ----
    def _tz_label(self, index) -> str:
        name = self.app.settings.get(K_TIMEZONE)
        z = name or timeutil.system_tz_name()
        try:
            text = f"{tzmod.city_label(z)} ({tzmod.offset_label(z)})"
        except Exception:
            text = z
        return text + (" (system)" if name is None else "")

    def _refresh_label(self) -> None:
        self.tz_row.set_value(self._tz_label(None))

    # ---- picker ----
    def _open_regions(self) -> None:
        if self._loading:
            return
        self._loading = True
        run_in_thread(tzmod.load_zone_index, on_done=self._show_regions,
                      on_error=self._load_failed, name="zone-index")

    def _load_failed(self, _e) -> None:
        self._loading = False
        if self.ctx.mode == "settings":
            self.app.toast("Couldn't load the time zone list")

    def _show_regions(self, index) -> None:
        self._loading = False
        current = self.app.settings.get(K_TIMEZONE) or timeutil.system_tz_name()
        page = _ZonePage(index, lambda v: self._on_item(index, v), current,
                         getattr(self.ctx.window, "keyboard", None))
        self._depth = 1
        self.ctx.push_page(page, "Time zone")

    def _on_item(self, index, value) -> None:
        kind, name = value
        if kind == "zone":
            self._pick(name, 1)
            return
        cities = [(z, f"{tzmod.city_label(z)}   {index.offsets[z]}") for z in index.groups[name]]
        current = self.app.settings.get(K_TIMEZONE) or timeutil.system_tz_name()
        page = ListPickerPage(cities, lambda z: self._pick(z, 2), current=current)
        self.ctx.push_page(page, name)

    def _pick(self, zone: str, depth: int) -> None:
        try:
            self.app.settings.set(K_TIMEZONE, zone)
        except (ValueError, OSError):
            log.exception("could not save time zone")
            if self.ctx.mode == "settings":
                self.app.toast("Couldn't save the time zone")
            return
        for _ in range(depth):
            self.ctx.pop_page()
        if self.ctx.mode == "settings":
            self.app.toast(f"Time zone set to {tzmod.city_label(zone)}")


class PreferencesSection:
    def __init__(self, ctx):
        self.widget = PreferencesPanel(ctx)


register_section(SectionSpec("preferences", "Preferences", 60, PreferencesSection))
