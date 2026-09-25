"""Header weather label (US-41): '<glyph> <temp>° · <max>°/<min>°'. Hidden without fresh data."""
from __future__ import annotations

from gi.repository import Gtk

from calpi.data import timeutil
from calpi.weather.client import header_text
from calpi.widgets.util import set_text_if_changed, set_visible_if_changed


class WeatherPanel(Gtk.Label):
    def __init__(self, service, clock=None):
        super().__init__(css_classes=["weather-panel"], visible=False, max_width_chars=18,
                         single_line_mode=True)
        self.service = service
        service.callbacks.append(lambda _s: self.update())
        if clock is not None:
            clock.subscribe_minute(lambda _now: self.update())     # hides it once it goes stale
        self.update()

    def update(self) -> None:
        fc = self.service.forecast()
        text = header_text(fc, timeutil.today()) if fc is not None else ""
        set_text_if_changed(self, text)
        set_visible_if_changed(self, bool(text))
