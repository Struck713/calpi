"""Calendars section (US-26): show/hide, rename, recolour, reset. Writes only user_* / hidden.

Every change: store.set_calendar_overrides -> app.on_calendars_changed() (colours + all views).
"""
from __future__ import annotations

import logging

from gi.repository import GLib, Gtk

from calpi.data import accounts
from calpi.data.palette import PALETTE
from calpi.widgets.settings.registry import SectionSpec, register_section
from calpi.widgets.settings.rows import ButtonRow, SettingsGroup, SwitchRow
from calpi.widgets.util import set_class, set_text_if_changed

log = logging.getLogger("calpi.settings.calendars")

MAX_NAME = 40
SAMPLE_TITLE = "Sample calendars (development)"
ALL_HIDDEN_TOAST = "All calendars are hidden — the calendar will be empty"


def normalize_name(text: str, remote_name: str) -> str | None:
    """User name to store: trimmed, <= 40 chars; None when empty or equal to the original."""
    name = (text or "").strip()[:MAX_NAME].strip()
    return None if not name or name == remote_name else name


def _dot(app, cal) -> Gtk.Box:
    box = Gtk.Box(css_classes=["cal-dot", app.calendar_colors.css_class(cal.id)],
                  valign=Gtk.Align.CENTER)
    box.set_size_request(28, 28)
    return box


def _apply(app, cal_id: str, **overrides) -> None:
    app.store.set_calendar_overrides(cal_id, **overrides)
    app.on_calendars_changed()


def _set_hidden(app, cal_id: str, hidden: bool) -> None:
    _apply(app, cal_id, hidden=hidden)
    if hidden and not any(not c.hidden for c in app.store.list_calendars(include_hidden=True)):
        app.toast(ALL_HIDDEN_TOAST)


class CalendarRow(Gtk.Box):
    """dot + names + switch. Tap the switch to toggle; tap anywhere else to open the edit page."""

    def __init__(self, app, cal, on_open, on_change):
        super().__init__(css_classes=["settings-row"], spacing=20)
        self.append(_dot(app, cal))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        texts.append(Gtk.Label(label=cal.name, xalign=0, css_classes=["row-title"]))
        sub = Gtk.Label(label=f"iCloud: {cal.remote_name}", xalign=0, css_classes=["row-desc"])
        sub.set_visible(cal.name != cal.remote_name)
        texts.append(sub)
        self.append(texts)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=not cal.hidden,
                                 css_classes=["target-exempt"])
        self.switch.connect("notify::active",
                            lambda sw, _p: self._toggled(sw, app, cal, on_change))
        self.append(self.switch)
        self.append(Gtk.Label(label="›", css_classes=["row-chevron"]))
        click = Gtk.GestureClick()
        click.connect("released", lambda _g, _n, x, y: self._click(x, y, on_open, cal))
        self.add_controller(click)

    @staticmethod
    def _toggled(sw, app, cal, on_change) -> None:
        if sw.get_active() == cal.hidden:       # a real change (not a re-render)
            _set_hidden(app, cal.id, not sw.get_active())
            GLib.idle_add(lambda: (on_change(), GLib.SOURCE_REMOVE)[1])

    def _click(self, x, y, on_open, cal) -> None:
        w = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while w is not None and w is not self:
            if w is self.switch:
                return
            w = w.get_parent()
        on_open(cal.id)


class EditPage(Gtk.Box):
    def __init__(self, ctx, cal_id: str, on_change=lambda: None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.on_change = on_change
        self.ctx, self.app, self.cal_id = ctx, ctx.app, cal_id
        cal = self.app.store.get_calendar(cal_id)
        g = SettingsGroup("Name")
        row = Gtk.Box(css_classes=["settings-row"], spacing=20)
        self.entry = Gtk.Entry(text=cal.name, hexpand=True, max_length=MAX_NAME,
                               css_classes=["text-entry"])
        self.entry.connect("activate", lambda *_: self.save_name())
        kb = getattr(ctx.window, "keyboard", None)
        if kb is not None:
            kb.attach(self.entry, "text", "Save", self.save_name)
        row.append(self.entry)
        row.append(_button("Save", self.save_name))
        g.add(row)
        self.original = Gtk.Label(xalign=0, css_classes=["row-desc"], margin_start=24, margin_top=8)
        g.append(self.original)
        self.append(g)

        g = SettingsGroup("Colour")
        grid = Gtk.Grid(column_spacing=16, row_spacing=16, margin_start=24, margin_top=12,
                        margin_bottom=12)
        self.swatches: list[Gtk.Button] = []
        for i, (color, name) in enumerate(PALETTE):
            b = Gtk.Button(css_classes=["swatch", f"swatch-{i}"], tooltip_text=name)
            b.set_size_request(88, 88)
            b.connect("clicked", lambda _b, c=color: self.set_color(c))
            grid.attach(b, i % 6, i // 6, 1, 1)
            self.swatches.append(b)
        g.append(grid)
        self.append(g)

        g = SettingsGroup("Visibility")
        self.visible_row = g.add(SwitchRow(
            "Show on the calendar",
            getter=lambda: not self._cal().hidden,
            setter=lambda v: _set_hidden(self.app, self.cal_id, not v),
            description="Hidden calendars keep syncing."))
        self.append(g)
        g = SettingsGroup()
        self.reset_row = g.add(ButtonRow("Reset to original", "Reset", self.reset,
                                         description="Use the name and colour from the account."))
        self.append(g)
        self.refresh()

    def _cal(self):
        return self.app.store.get_calendar(self.cal_id)

    def refresh(self) -> None:
        cal = self._cal()
        if cal is None:
            return
        self.on_change()
        set_text_if_changed(self.original, f"Original: {cal.remote_name}")
        for (color, _n), b in zip(PALETTE, self.swatches):
            sel = cal.color == color
            set_class(b, "selected", sel)
            if b.get_label() != ("✓" if sel else ""):
                b.set_label("✓" if sel else "")
        self.reset_row.button.set_sensitive(bool(cal.user_name or cal.user_color))
        self.visible_row._sync()

    def save_name(self) -> None:
        cal = self._cal()
        name = normalize_name(self.entry.get_text(), cal.remote_name)
        if name == cal.user_name:
            return
        _apply(self.app, self.cal_id, user_name=name)
        self.entry.set_text(self._cal().name)
        self.app.toast("Renamed")
        self.refresh()

    def set_color(self, color: str) -> None:
        cal = self._cal()
        _apply(self.app, self.cal_id, user_color=None if color == cal.remote_color else color)
        self.refresh()

    def reset(self) -> None:
        _apply(self.app, self.cal_id, user_name=None, user_color=None)
        self.entry.set_text(self._cal().name)
        self.refresh()


def _button(label, fn) -> Gtk.Button:
    b = Gtk.Button(label=label, valign=Gtk.Align.CENTER, css_classes=["row-button"])
    b.connect("clicked", lambda *_: fn())
    return b


class CalendarsSection:
    def __init__(self, ctx):
        self.ctx = ctx
        self.app = ctx.app
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._key = None
        self._page: EditPage | None = None

    def on_show(self) -> None:
        self._render()

    def on_hide(self) -> None:
        self._page = None

    def _group_title(self, account_id) -> str:
        if account_id:
            acc = accounts.get_account(self.app.settings, account_id)
            if acc is not None:
                return acc.display_name
        return SAMPLE_TITLE if (account_id is None) else str(account_id)

    def _render(self) -> None:
        cals = self.app.store.list_calendars(include_hidden=True)
        key = tuple((c.id, c.name, c.color, c.hidden, c.remote_name) for c in cals)
        if key == self._key:
            return
        self._key = key
        while (child := self.widget.get_first_child()) is not None:
            self.widget.remove(child)
        groups: dict = {}
        for c in cals:
            groups.setdefault(c.account_id, []).append(c)
        for account_id, items in groups.items():
            g = SettingsGroup(self._group_title(account_id))
            for c in items:
                g.add(CalendarRow(self.app, c, self._open, self._render))
            self.widget.append(g)

    def _open(self, cal_id: str) -> None:
        cal = self.app.store.get_calendar(cal_id)
        if cal is None:
            return
        self._page = EditPage(self.ctx, cal_id, self._render)
        self.ctx.push_page(self._page, cal.name)


register_section(SectionSpec("calendars", "Calendars", 30, CalendarsSection,
                             available=lambda app: bool(app.store.list_calendars(include_hidden=True))))
