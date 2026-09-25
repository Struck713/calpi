"""Dev demo of every row type, dialogs, toast, blocking overlay (CALPI_DEV_ROWS=1 only)."""
from __future__ import annotations

from gi.repository import GLib, Gtk

from calpi.widgets.settings.registry import SectionSpec, register_section
from calpi.widgets.settings.rows import (ButtonRow, ChoiceRow, InfoRow, ListPickerPage,
                                         ListPickerRow, SettingsGroup, StepperRow, SwitchRow)


class DevRows:
    def __init__(self, ctx):
        self.ctx = ctx
        w = ctx.window
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        state = {"sw": False, "choice": "b", "zone": "Zone 3"}
        g = SettingsGroup("Rows")
        g.add(SwitchRow("Demo switch", getter=lambda: state["sw"],
                        setter=lambda v: state.__setitem__("sw", v), description="Tap anywhere"))
        g.add(ChoiceRow("Demo choice", [("a", "A"), ("b", "B"), ("c", "C")],
                        getter=lambda: state["choice"],
                        setter=lambda v: state.__setitem__("choice", v)))
        g.add(StepperRow("Demo stepper", 5, 0, 10, 1, lambda v: f"{v} min",
                         on_change=lambda v: w.get_application().toast(f"stepper={v}")))
        self.picker_row = ListPickerRow("Demo picker", state["zone"], self._open_picker)
        g.add(self.picker_row)
        g.add(InfoRow("Info", "read-only"))
        g.add(ButtonRow("Confirm", "Ask", lambda: w.confirm.ask(
            "Delete everything?", "This is only a demo.", "Delete", lambda: None, destructive=True)))
        g.add(ButtonRow("Toast", "Show", lambda: w.get_application().toast("Hello toast")))
        g.add(ButtonRow("Blocking", "Show 3 s", self._block))
        self.widget.append(g)
        self._state = state

    def _open_picker(self):
        items = [(f"Zone {i}", f"Zone {i}") for i in range(400)]
        page = ListPickerPage(items, self._picked, current=self._state["zone"], search=True,
                              keyboard=getattr(self.ctx.window, "keyboard", None))
        self.ctx.push_page(page, "Choose zone")

    def _picked(self, v):
        self._state["zone"] = v
        self.picker_row.set_value(v)
        self.ctx.pop_page()

    def _block(self):
        self.ctx.window.blocking.show("Connecting to Wi-Fi…")
        GLib.timeout_add_seconds(3, lambda: (self.ctx.window.blocking.hide(), GLib.SOURCE_REMOVE)[1])


register_section(SectionSpec("devrows", "Dev rows", 1, DevRows))
