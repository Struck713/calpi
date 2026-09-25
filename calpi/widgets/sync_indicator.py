"""Header sync status (US-16): 'Updating…' while a run is active, else 'Updated HH:MM'.

US-17 (offline), US-19 (refresh button) and US-38 (errors) extend this class.
"""
from __future__ import annotations

from datetime import datetime

from gi.repository import Gtk

from calpi.data import formatting, timeutil
from calpi.widgets.util import set_text_if_changed


def indicator_text(running: bool, last_success: datetime | None, now: datetime) -> str:
    if running:
        return "Updating…"
    if last_success is None:
        return ""
    t = last_success.astimezone(now.tzinfo)
    when = formatting.short_time(t)
    if t.date() == now.date():
        return f"Updated {when}"
    if (now.date() - t.date()).days == 1:
        return f"Updated yesterday {when}"
    return f"Updated {t.day} {t:%b} {when}"


class SyncIndicator(Gtk.Label):
    def __init__(self, engine, clock=None):
        super().__init__(css_classes=["sync-status"], visible=False)
        self.engine = engine
        engine.state_callbacks.append(lambda _running: self.update())
        engine.result_callbacks.append(lambda _r: self.update())
        if clock is not None:
            clock.subscribe_minute(lambda _now: self.update())
        self.update()

    def update(self) -> None:
        text = indicator_text(self.engine.is_running, self.engine.last_success_wall, timeutil.now())
        set_text_if_changed(self, text)
        if self.get_visible() != bool(text):
            self.set_visible(bool(text))
