"""Weather section (US-41, order 55): enable, city search, units, last update, privacy, attribution."""
from __future__ import annotations

import logging

from gi.repository import Gtk

from calpi.data.settings_store import K_WEATHER
from calpi.tasks import run_in_thread
from calpi.weather import client
from calpi.weather.client import WeatherError
from calpi.widgets.settings.registry import SectionSpec, register_section
from calpi.widgets.settings.rows import (ChoiceRow, InfoRow, ListPickerPage, ListPickerRow,
                                         SettingsGroup, SwitchRow)
from calpi.widgets.util import set_text_if_changed

log = logging.getLogger("calpi.settings.weather")

PRIVACY = "Your city's location is sent to Open-Meteo to get the forecast."
ATTRIBUTION = "Weather data by Open-Meteo.com"


class PlaceSearchPage(Gtk.Box):
    """Entry + Search button + results list. `search` is injectable for tests."""

    manages_scroll = True

    def __init__(self, on_pick, keyboard=None, search=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                         css_classes=["picker-page"])
        self._on_pick = on_pick
        self._search = search or client.search_places
        self._serial = 0
        self._results: Gtk.Widget | None = None
        row = Gtk.Box(spacing=16)
        self.entry = Gtk.Entry(placeholder_text="City name", hexpand=True,
                               css_classes=["picker-search"])
        self.entry.connect("activate", lambda *_: self.run_search())
        self.button = Gtk.Button(label="Search", css_classes=["row-button"])
        self.button.connect("clicked", lambda *_: self.run_search())
        row.append(self.entry)
        row.append(self.button)
        self.append(row)
        if keyboard is not None:
            keyboard.attach(self.entry, "text", done_label="Search", on_done=self.run_search)
        self.message = Gtk.Label(xalign=0, css_classes=["weather-note"], wrap=True, visible=False)
        self.append(self.message)
        self.holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self.append(self.holder)

    def _say(self, text: str) -> None:
        set_text_if_changed(self.message, text)
        self.message.set_visible(bool(text))

    def run_search(self) -> None:
        q = self.entry.get_text().strip()
        if len(q) < 2:
            self._say("Type at least two letters.")
            return
        self._serial += 1
        serial = self._serial
        self._say("Searching…")
        run_in_thread(lambda: self._search(q),
                      on_done=lambda places: self._show(serial, q, places),
                      on_error=lambda e: self._failed(serial, e), name="weather-search")

    def _failed(self, serial: int, exc: BaseException) -> None:
        if serial != self._serial:
            return
        kind = exc.kind if isinstance(exc, WeatherError) else "server"
        self._say(f"Couldn't search: {client.reason_text(kind)}.")

    def _show(self, serial: int, q: str, places) -> None:
        if serial != self._serial:
            return
        if self._results is not None:
            self.holder.remove(self._results)
            self._results = None
        if not places:
            self._say(f"No places found for “{q}”.")
            return
        self._say("")
        by_label = {p.label: p for p in places}
        self._results = ListPickerPage([(p.label, p.label) for p in places],
                                       lambda lbl: self._on_pick(by_label[lbl]))
        self._results.set_vexpand(True)
        self.holder.append(self._results)


class WeatherPanelSection(Gtk.Box):
    def __init__(self, ctx):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.ctx = ctx
        self.app = ctx.app
        settings = self.app.settings
        g = SettingsGroup("Weather")
        g.add(SwitchRow("Show weather", settings=settings, key=K_WEATHER,
                        getter=lambda: settings.get(K_WEATHER)["enabled"],
                        setter=lambda v: self._update(enabled=v),
                        description="Off by default. Shows today's weather in the header and "
                                    "a short forecast in the calendar."))
        self.loc_row = g.add(ListPickerRow("Location", self._loc_text(), self._open_search))
        g.add(ChoiceRow("Units", [("celsius", "°C"), ("fahrenheit", "°F")],
                        getter=lambda: settings.get(K_WEATHER)["units"],
                        setter=lambda v: self._update(units=v), settings=settings, key=K_WEATHER))
        self.status_row = g.add(InfoRow("Last updated", self._status_text()))
        self.append(g)
        self.append(Gtk.Label(label=PRIVACY, xalign=0, wrap=True, css_classes=["weather-note"]))
        self.append(Gtk.Label(label=ATTRIBUTION, xalign=0, css_classes=["weather-note"]))
        self._token = settings.subscribe(K_WEATHER, lambda *_: self.refresh())
        weather = getattr(self.app, "weather", None)
        if weather is not None:
            weather.callbacks.append(self._on_service)
        self.connect("destroy", lambda *_: settings.unsubscribe(self._token))
        self.connect("map", lambda *_: self.refresh())

    def _update(self, **changes) -> None:
        cfg = self.app.settings.get(K_WEATHER)
        cfg.update(changes)
        self.app.settings.set(K_WEATHER, cfg)

    def _loc_text(self) -> str:
        return self.app.settings.get(K_WEATHER)["name"] or "Not set"

    def _status_text(self) -> str:
        weather = getattr(self.app, "weather", None)
        if weather is None or not self.app.settings.get(K_WEATHER)["enabled"]:
            return "Off"
        if self.app.settings.get(K_WEATHER)["lat"] is None:
            return "Choose a location"
        return weather.status_text()

    def _on_service(self, _service) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.loc_row.set_value(self._loc_text())
        self.status_row.set_value(self._status_text())

    def _open_search(self) -> None:
        page = PlaceSearchPage(self._picked, getattr(self.ctx.window, "keyboard", None))
        self.ctx.push_page(page, "Location")

    def _picked(self, place) -> None:
        try:
            self._update(name=place.label[:100], lat=place.lat, lon=place.lon)
        except (ValueError, OSError):
            log.exception("could not save weather location")
            self.app.toast("Couldn't save the location")
            return
        self.ctx.pop_page()
        self.refresh()


class WeatherSettingsSection:
    def __init__(self, ctx):
        self.widget = WeatherPanelSection(ctx)


register_section(SectionSpec("weather", "Weather", 55, WeatherSettingsSection))
