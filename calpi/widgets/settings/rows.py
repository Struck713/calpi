"""Touch-friendly settings rows (each >= 72 px tall, full width). See US-22.

Rows that follow a settings key subscribe while mapped and unsubscribe when unmapped, and never
re-set a value that already matches (no feedback loops). Write failures show a toast and revert.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

from gi.repository import GLib, Gtk

from calpi.data.debounce import Debouncer
from calpi.widgets.util import exempt_scrollbars, set_class, set_text_if_changed

log = logging.getLogger("calpi.settings.rows")

STEPPER_DEBOUNCE_S = 0.5
FILTER_DEBOUNCE_S = 0.15


def _toast(widget: Gtk.Widget, text: str) -> None:
    try:
        app = widget.get_root().get_application()
        app.toast(text)
    except Exception:
        log.warning("toast unavailable: %s", text)


def _glib_debouncer(delay: float, action: Callable[[Any], None]) -> Debouncer:
    return Debouncer(delay, action,
                     lambda d, fn: GLib.timeout_add(int(d * 1000), lambda: (fn(), GLib.SOURCE_REMOVE)[1]),
                     GLib.source_remove)


class SettingsGroup(Gtk.Box):
    def __init__(self, title: str | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group-wrap"])
        if title:
            self.append(Gtk.Label(label=title, xalign=0, css_classes=["settings-group-title"]))
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group"])
        super().append(self.rows)

    def add(self, row: Gtk.Widget) -> Gtk.Widget:
        self.rows.append(row)
        return row


class _Row(Gtk.Box):
    def __init__(self, title: str, description: str | None = None):
        super().__init__(css_classes=["settings-row"], spacing=24)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(label=title, xalign=0, css_classes=["row-title"], wrap=True)
        texts.append(self.title)
        self.description = Gtk.Label(label=description or "", xalign=0, css_classes=["row-desc"],
                                     wrap=True)
        self.description.set_visible(bool(description))
        texts.append(self.description)
        self.append(texts)

    def set_description(self, text: str | None) -> None:
        set_text_if_changed(self.description, text or "")
        self.description.set_visible(bool(text))


class _KeyBound:
    """Mixin: subscribe to a settings key while the widget is mapped."""

    def _bind_key(self, widget: Gtk.Widget, settings, key: str | None, refresh: Callable[[], None]):
        self._settings, self._key, self._token = settings, key, None
        self._refresh = refresh
        widget.connect("map", self._on_map)
        widget.connect("unmap", self._on_unmap)

    def _on_map(self, *_):
        if self._settings is not None and self._key and self._token is None:
            self._token = self._settings.subscribe(self._key, lambda *_a: self._refresh())
        self._refresh()

    def _on_unmap(self, *_):
        if self._token is not None:
            self._settings.unsubscribe(self._token)
            self._token = None


class SwitchRow(_Row, _KeyBound):
    def __init__(self, title: str, settings=None, key: str | None = None,
                 getter: Callable[[], bool] | None = None,
                 setter: Callable[[bool], None] | None = None,
                 description: str | None = None):
        super().__init__(title, description)
        self._getter = getter or (lambda: bool(settings.get(key)))
        self._setter = setter or (lambda v: settings.set(key, v))
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=self._getter(),
                                css_classes=["target-exempt"])     # the whole row is the target
        self.append(self.switch)
        self._updating = False
        self.switch.connect("notify::active", self._on_active)
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)
        self._bind_key(self, settings, key, self._sync)

    def _sync(self) -> None:
        val = bool(self._getter())
        if self.switch.get_active() != val:
            self._updating = True
            self.switch.set_active(val)
            self._updating = False

    def _on_active(self, *_):
        if self._updating:
            return
        val = self.switch.get_active()
        if val == bool(self._getter()):
            return
        try:
            self._setter(val)
        except (ValueError, OSError):
            log.exception("could not save %s", self._key)
            _toast(self, "Couldn't save setting")
            self._sync()

    def _on_click(self, _g, _n, x, y):
        w = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while w is not None and w is not self:
            if w is self.switch:
                return                      # the switch handles its own tap
            w = w.get_parent()
        self.switch.set_active(not self.switch.get_active())


class ChoiceRow(_Row, _KeyBound):
    def __init__(self, title: str, options: Sequence[tuple[Any, str]], settings=None,
                 key: str | None = None, getter: Callable[[], Any] | None = None,
                 setter: Callable[[Any], None] | None = None, description: str | None = None):
        super().__init__(title, description)
        self._getter = getter or (lambda: settings.get(key))
        self._setter = setter or (lambda v: settings.set(key, v))
        self._buttons: list[tuple[Any, Gtk.ToggleButton]] = []
        box = Gtk.Box(spacing=16, valign=Gtk.Align.CENTER, css_classes=["choice-box"])
        first = None
        for value, label in options:
            b = Gtk.ToggleButton(label=label, css_classes=["choice-button"])
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._on_toggled, value)
            box.append(b)
            self._buttons.append((value, b))
        self.append(box)
        self._updating = False
        self._bind_key(self, settings, key, self._sync)
        self._sync()

    def _sync(self) -> None:
        cur = self._getter()
        self._updating = True
        for value, b in self._buttons:
            if value == cur and not b.get_active():
                b.set_active(True)
        self._updating = False

    def _on_toggled(self, b, value):
        if self._updating or not b.get_active() or value == self._getter():
            return
        try:
            self._setter(value)
        except (ValueError, OSError):
            log.exception("could not save %s", self._key)
            _toast(self, "Couldn't save setting")
            self._sync()


class StepperRow(_Row):
    def __init__(self, title: str, value: int, min: int, max: int, step: int = 1,
                 format: Callable[[int], str] = str,
                 on_change: Callable[[int], None] | None = None, description: str | None = None):
        super().__init__(title, description)
        self.min, self.max, self.step, self._format = min, max, step, format
        self.value = value
        self._on_change = on_change
        self._deb = _glib_debouncer(STEPPER_DEBOUNCE_S, self._commit)
        box = Gtk.Box(spacing=16, valign=Gtk.Align.CENTER)
        self.minus = Gtk.Button(label="−", css_classes=["stepper-button"])
        self.value_label = Gtk.Label(label=format(value), css_classes=["stepper-value"])
        self.plus = Gtk.Button(label="+", css_classes=["stepper-button"])
        for w in (self.minus, self.value_label, self.plus):
            box.append(w)
        self.append(box)
        self.minus.connect("clicked", lambda *_: self._bump(-self.step))
        self.plus.connect("clicked", lambda *_: self._bump(self.step))
        self.connect("unmap", lambda *_: self.flush())
        self._update_buttons()

    def set_value(self, value: int) -> None:
        """Set from outside without triggering on_change."""
        self.value = max(self.min, min(self.max, value))
        set_text_if_changed(self.value_label, self._format(self.value))
        self._update_buttons()

    def _bump(self, delta: int) -> None:
        new = max(self.min, min(self.max, self.value + delta))
        if new == self.value:
            return
        self.set_value(new)
        self._deb.call(new)

    def _update_buttons(self) -> None:
        self.minus.set_sensitive(self.value > self.min)
        self.plus.set_sensitive(self.value < self.max)

    def _commit(self, value: int) -> None:
        if self._on_change:
            try:
                self._on_change(value)
            except Exception:
                log.exception("stepper on_change failed")
                _toast(self, "Couldn't save setting")

    def flush(self) -> None:
        self._deb.flush()


class ButtonRow(_Row):
    def __init__(self, title: str, button_label: str, on_click: Callable[[], None],
                 destructive: bool = False, description: str | None = None):
        super().__init__(title, description)
        self.button = Gtk.Button(label=button_label, valign=Gtk.Align.CENTER,
                                 css_classes=["row-button"])
        set_class(self.button, "destructive", destructive)
        self.button.connect("clicked", lambda *_: on_click())
        self.append(self.button)


class InfoRow(_Row):
    def __init__(self, title: str, value: str = "", description: str | None = None):
        super().__init__(title, description)
        self.value = Gtk.Label(label=value, xalign=1, css_classes=["row-value"], wrap=True,
                               selectable=False)
        self.append(self.value)

    def set_value(self, text: str) -> None:
        set_text_if_changed(self.value, text)


class ListPickerRow(_Row):
    """Shows the current value and a chevron; a tap anywhere on the row opens the picker."""

    def __init__(self, title: str, value_label: str, open_picker: Callable[[], None],
                 description: str | None = None):
        super().__init__(title, description)
        self.value = Gtk.Label(label=value_label, css_classes=["row-value"])
        self.append(self.value)
        self.append(Gtk.Label(label="›", css_classes=["row-chevron"]))
        self.set_focusable(True)
        self.add_css_class("tappable")
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: open_picker())
        self.add_controller(click)
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key, open_picker)
        self.add_controller(key)

    @staticmethod
    def _on_key(_c, keyval, _kc, _st, open_picker):
        from gi.repository import Gdk
        if Gdk.keyval_name(keyval) in ("Return", "KP_Enter", "space"):
            open_picker()
            return True
        return False

    def set_value(self, text: str) -> None:
        set_text_if_changed(self.value, text)


class ListPickerPage(Gtk.Box):
    """Full-page list. Rows are built once. Push it with ctx.push_page(page, title).

    items: sequence of (value, label). on_pick(value) is called on tap; the caller pops the page.
    """

    manages_scroll = True

    def __init__(self, items: Sequence[tuple[Any, str]], on_pick: Callable[[Any], None],
                 current: Any = None, search: bool = False, keyboard=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                         css_classes=["picker-page"])
        self._on_pick = on_pick
        self._query = ""
        self.entry = None
        if search:
            self.entry = Gtk.Entry(placeholder_text="Search", css_classes=["picker-search"])
            self.entry.connect("changed", self._on_changed)
            self.append(self.entry)
            if keyboard is not None:
                keyboard.attach(self.entry, "text", done_label="Done")
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE,
                                   css_classes=["picker-list"])
        self._values: dict[Gtk.ListBoxRow, tuple[Any, str]] = {}
        for value, label in items:
            row = Gtk.ListBoxRow(css_classes=["picker-row"])
            box = Gtk.Box(spacing=16)
            box.append(Gtk.Label(label=label, xalign=0, hexpand=True, css_classes=["picker-label"]))
            box.append(Gtk.Label(label="✓" if value == current else "",
                                 css_classes=["picker-check"]))
            row.set_child(box)
            self.listbox.append(row)
            self._values[row] = (value, label.lower())
        self.listbox.set_filter_func(self._filter)
        self.listbox.connect("row-activated", self._on_activated)
        sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                kinetic_scrolling=True, child=self.listbox)
        self.append(exempt_scrollbars(sw))
        self._deb = _glib_debouncer(FILTER_DEBOUNCE_S, self._apply_query)

    def _filter(self, row) -> bool:
        return not self._query or self._query in self._values[row][1]

    def _on_changed(self, entry) -> None:
        self._deb.call(entry.get_text().strip().lower())

    def _apply_query(self, q: str) -> None:
        self._query = q
        self.listbox.invalidate_filter()

    def _on_activated(self, _lb, row) -> None:
        try:
            self._on_pick(self._values[row][0])
        except Exception:
            log.exception("picker on_pick failed")
