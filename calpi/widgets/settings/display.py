"""Display section (US-29): brightness. US-30 appends its schedule group via DISPLAY_GROUP_FACTORIES."""
from __future__ import annotations

import logging
from typing import Callable

from gi.repository import Gtk

from calpi.data.settings_store import K_BRIGHTNESS
from calpi.widgets.settings.registry import SectionSpec, register_section
from calpi.widgets.settings.rows import SettingsGroup, StepperRow, _Row
from calpi.widgets.util import set_class, set_text_if_changed

log = logging.getLogger("calpi.settings.display")

PRESETS = (25, 50, 75, 100)

# Other stories append factories `(ctx) -> Gtk.Widget` (a SettingsGroup); built after Brightness.
DISPLAY_GROUP_FACTORIES: list[Callable] = []


class PresetRow(_Row):
    def __init__(self, on_pick: Callable[[int], None]):
        super().__init__("Presets")
        box = Gtk.Box(spacing=16, valign=Gtk.Align.CENTER)
        self.buttons: dict[int, Gtk.Button] = {}
        for p in PRESETS:
            b = Gtk.Button(label=f"{p}%", css_classes=["preset-button"])
            b.connect("clicked", lambda _b, p=p: on_pick(p))
            box.append(b)
            self.buttons[p] = b
        self.append(box)

    def mark(self, value: int) -> None:
        for p, b in self.buttons.items():
            set_class(b, "selected", p == value)


class DisplaySection:
    def __init__(self, ctx):
        self.ctx = ctx
        self.app = ctx.app
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.groups_box = self.widget
        settings, ctl = self.app.settings, getattr(self.app, "brightness", None)
        self.ctl = ctl
        g = SettingsGroup("Brightness")
        self.stepper = g.add(StepperRow(
            "Brightness", settings.get(K_BRIGHTNESS), 10, 100, 10, lambda v: f"{v}%",
            on_change=lambda v: settings.set(K_BRIGHTNESS, v)))
        # Live feedback: the stepper's own write is debounced (500 ms), the screen must not be.
        for btn in (self.stepper.minus, self.stepper.plus):
            btn.connect("clicked", self._preview)
        self.presets = g.add(PresetRow(lambda v: settings.set(K_BRIGHTNESS, v)))
        self.note = Gtk.Label(xalign=0, wrap=True, css_classes=["row-desc"], margin_start=8,
                              margin_bottom=24)
        g.append(self.note)
        self.widget.append(g)
        for factory in list(DISPLAY_GROUP_FACTORIES):
            try:
                self.widget.append(factory(ctx))
            except Exception:
                log.exception("display group factory failed")
        self._token = None
        self._refresh_note()

    def _preview(self, *_):
        if self.ctl is not None:
            self.ctl.set_preview(self.stepper.value)
        self.presets.mark(self.stepper.value)

    def _refresh_note(self) -> None:
        set_text_if_changed(self.note, self.ctl.note() if self.ctl else "")
        self.presets.mark(self.app.settings.get(K_BRIGHTNESS))

    def _on_setting(self, _k, value) -> None:
        self.stepper.set_value(value)
        self.presets.mark(value)

    def on_show(self):
        self.stepper.set_value(self.app.settings.get(K_BRIGHTNESS))
        if self._token is None:
            self._token = self.app.settings.subscribe(K_BRIGHTNESS, self._on_setting)
        if self.ctl is not None:
            self.ctl.ready_callbacks.add(self._refresh_note)
        self._refresh_note()

    def on_hide(self):
        self.stepper.flush()
        if self._token is not None:
            self.app.settings.unsubscribe(self._token)
            self._token = None
        if self.ctl is not None:
            self.ctl.ready_callbacks.remove(self._refresh_note)


register_section(SectionSpec("display", "Display", 50, DisplaySection))
