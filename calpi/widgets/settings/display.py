"""Display section (US-29): brightness. US-30 appends its schedule group via DISPLAY_GROUP_FACTORIES."""
from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Callable

from gi.repository import GLib, Gtk

from calpi.data import formatting
from calpi.data.settings_store import (DEFAULT_DIM_SCHEDULE, K_BRIGHTNESS, K_DIM_SCHEDULE,
                                       WAKE_MINUTES_CHOICES)
from calpi.tasks import safe_callback
from calpi.widgets.settings.registry import SectionSpec, register_section
from calpi.widgets.settings.rows import (ButtonRow, ChoiceRow, ListPickerPage, ListPickerRow,
                                         SettingsGroup, StepperRow, SwitchRow, _Row)
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


TIME_CHOICES = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]
_off_warning_shown = False


def time_label(hhmm: str) -> str:
    h, m = int(hhmm[:2]), int(hhmm[3:])
    return formatting.short_time(datetime.combine(datetime(2000, 1, 1), time(h, m)))


class DimSchedulePanel(SettingsGroup):
    """US-30: the Overnight group. Reused by the setup wizard (ctx.mode == "wizard")."""

    def __init__(self, ctx):
        super().__init__("Overnight")
        self.ctx, self.app = ctx, ctx.app
        self.settings = ctx.app.settings
        self.ctl = getattr(ctx.app, "dimming", None)
        self.switch = self.add(SwitchRow(
            "Overnight mode", self.settings, K_DIM_SCHEDULE,
            getter=lambda: self._cfg()["enabled"], setter=lambda v: self._set(enabled=v),
            description="Dim or turn off the screen on a nightly schedule. Touch wakes it."))
        self.start_row = self.add(ListPickerRow(
            "Starts at", "", lambda: self._pick("start", "Starts at")))
        self.end_row = self.add(ListPickerRow(
            "Ends at", "", lambda: self._pick("end", "Ends at")))
        self.mode = self.add(ChoiceRow(
            "When it's night", [("dim", "Dim"), ("off", "Turn off")], self.settings,
            K_DIM_SCHEDULE, getter=lambda: self._cfg()["mode"], setter=self._set_mode))
        self.level = self.add(StepperRow(
            "Night brightness", self._cfg()["night_level"], 10, 50, 5, lambda v: f"{v}%",
            on_change=lambda v: self._set(night_level=v)))
        self.wake = self.add(ChoiceRow(
            "Stay awake after touch",
            [(m, f"{m} min") for m in WAKE_MINUTES_CHOICES], self.settings, K_DIM_SCHEDULE,
            getter=lambda: self._cfg()["wake_minutes"],
            setter=lambda v: self._set(wake_minutes=v)))
        self.preview_row = self.add(ButtonRow(
            "Preview", "Try it", self._preview, description="Applies the night state for 10 seconds."))
        self._token = None
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        self._refresh()

    def _cfg(self) -> dict:
        return {**DEFAULT_DIM_SCHEDULE, **self.settings.get(K_DIM_SCHEDULE)}

    def _set(self, **changes) -> None:
        d = dict(self._cfg())                  # copy, then set: never mutate in place
        d.update(changes)
        self.settings.set(K_DIM_SCHEDULE, d)

    def _on_map(self, *_):
        if self._token is None:
            self._token = self.settings.subscribe(K_DIM_SCHEDULE, lambda *_a: self._refresh())
        self._refresh()

    def _on_unmap(self, *_):
        self.level.flush()
        if self._token is not None:
            self.settings.unsubscribe(self._token)
            self._token = None

    def _refresh(self) -> None:
        cfg = self._cfg()
        self.start_row.set_value(time_label(cfg["start"]))
        self.end_row.set_value(time_label(cfg["end"]))
        self.level.set_value(max(10, cfg["night_level"]))
        self.level.set_visible(cfg["mode"] == "dim")
        self.mode.set_description(self._mode_note(cfg))

    def _mode_note(self, cfg) -> str | None:
        if cfg["mode"] != "off" or self.ctl is None:
            return None
        if not self.ctl.probed:
            return "Checking what this screen supports…"
        if not self.ctl.has_real_off_method():
            return "The screen will go black but stays powered."
        return None

    def _pick(self, field: str, title: str) -> None:
        def on_pick(value: str) -> None:
            try:
                self._set(**{field: value})
            except ValueError:
                self.app.toast("Start and end times can't be the same")
                return
            except OSError:
                self.app.toast("Couldn't save setting")
                return
            self.ctx.pop_page()
        page = ListPickerPage([(t, time_label(t)) for t in TIME_CHOICES], on_pick,
                              current=self._cfg()[field])
        self.ctx.push_page(page, title)

    def _set_mode(self, value: str) -> None:
        global _off_warning_shown
        self._set(mode=value)
        if value == "off" and not _off_warning_shown:
            _off_warning_shown = True
            self.ctx.window.confirm.ask(
                "Turn off the screen overnight?",
                "Some screens can't be woken by touch once they're turned off. Try Preview first. "
                "If the screen doesn't wake, use Dim instead.", "OK", lambda: None)

    def _preview(self) -> None:
        if self.ctl is None:
            return
        method = self.ctl.preview_method()
        needs_check = (self._cfg()["mode"] == "off" and not method.trusted
                       and self._cfg()["confirmed_method"] != method.name)
        self.ctl.preview()
        if needs_check:
            GLib.timeout_add(12000, safe_callback(lambda: self._ask_worked(method.name),
                                                  repeat=False))

    def _ask_worked(self, name: str) -> None:
        self.ctx.window.confirm.ask(
            "Did the screen turn off and come back?",
            "If it did, calpi will use this method overnight. If not, choose Dim instead.",
            "Yes, it worked", lambda: self.ctl.confirm_method(name), cancel_label="No")


def _dim_group(ctx):
    return DimSchedulePanel(ctx)


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


DISPLAY_GROUP_FACTORIES.append(_dim_group)         # US-30
register_section(SectionSpec("display", "Display", 50, DisplaySection))
