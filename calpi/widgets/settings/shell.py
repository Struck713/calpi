"""SettingsScreen: header, section sidebar, lazily built section content (US-22).

SECTION-REUSE CONTRACT (D5) - every settings section follows this
-----------------------------------------------------------------
* Register with `register_section(SectionSpec(id, title, order, factory, available))` (see
  registry.py); add the module to `SECTION_MODULES` in settings/__init__.py.
* `factory(ctx)` returns a Section: an object with `.widget` and optional `on_show()`,
  `on_hide()`, `on_key(name, state) -> bool`, `dispose()`. It is built the first time the
  section is opened and kept for the life of the app.
* The factory must work in BOTH modes: ctx.mode is "settings" or "wizard" (US-32). In wizard
  mode a section may hide advanced rows and must not assume a sidebar exists.
* Content widgets talk only to `ctx` (app, window, mode, navigate_back(), push_page(widget,
  title), pop_page()); never reach into SettingsScreen. Choosing among many options uses a
  full-page ListPickerPage pushed with ctx.push_page (never a popover/dropdown).
* Settings apply immediately (no Save button); multi-field forms have an explicit action button.
* Open a specific section from anywhere: window.navigator.show("settings", section="network").
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from gi.repository import Gtk

from calpi.tasks import safe_callback
from calpi.widgets.settings import load_sections
from calpi.widgets.util import exempt_scrollbars
from calpi.widgets.settings.registry import (SECTIONS, SectionSpec, ordered_sections,  # noqa: F401
                                             register_section)

log = logging.getLogger("calpi.settings.ui")

IDLE_RETURN_S = 600


@dataclass
class SectionContext:
    app: Any
    window: Any
    mode: str = "settings"                       # "settings" | "wizard"
    navigate_back: Callable[[], None] = lambda: None
    push_page: Callable[[Gtk.Widget, str], None] = lambda w, t: None
    pop_page: Callable[[], None] = lambda: None


class _Placeholder:
    def __init__(self, text: str):
        self.widget = Gtk.Label(label=text, css_classes=["row-desc"], xalign=0, wrap=True,
                                margin_top=32, margin_start=48)


class _Host(Gtk.Box):
    """One section's area: an inner stack with the section root and pushed sub-pages."""

    def __init__(self, title: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self.title = title
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, vexpand=True,
                               hexpand=True)
        self.append(self.stack)
        self.pages: list[tuple[str, Gtk.Widget]] = []      # (page title, page)

    def set_root(self, widget: Gtk.Widget) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-content"])
        box.append(widget)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=box)
        exempt_scrollbars(sw)
        self.stack.add_named(sw, "root")
        self.stack.set_visible_child_name("root")

    def push(self, widget: Gtk.Widget, title: str, on_back: Callable[[], None]) -> None:
        prev_title = self.pages[-1][0] if self.pages else self.title
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-subpage"])
        back = Gtk.Button(label=f"← {prev_title}", halign=Gtk.Align.START,
                          css_classes=["nav-button", "subpage-back"])
        back.connect("clicked", lambda *_: on_back())
        page.append(back)
        if getattr(widget, "manages_scroll", False):
            page.append(widget)
        else:
            page.append(exempt_scrollbars(Gtk.ScrolledWindow(
                hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=widget)))
        self.stack.add_named(page, f"p{len(self.pages)}")
        self.stack.set_visible_child_name(f"p{len(self.pages)}")
        self.pages.append((title, page))

    def pop(self) -> bool:
        if not self.pages:
            return False
        _title, page = self.pages.pop()
        self.stack.set_visible_child_name(f"p{len(self.pages) - 1}" if self.pages else "root")
        self.stack.remove(page)
        return True


class SettingsScreen(Gtk.Box):
    def __init__(self, app, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["screen", "settings"])
        self.app, self.window = app, window
        load_sections()
        header = Gtk.Box(spacing=24, css_classes=["settings-header"])
        back = Gtk.Button(label="← Calendar", css_classes=["nav-button", "back-button"])
        back.connect("clicked", lambda *_: self._leave())
        header.append(back)
        header.append(Gtk.Label(label="Settings", css_classes=["settings-title"]))
        self.append(header)
        body = Gtk.Box(vexpand=True, hexpand=True)
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["sidebar"],
                               vexpand=True)
        self.content = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, hexpand=True,
                                 vexpand=True)
        body.append(self.sidebar)
        body.append(self.content)
        self.append(body)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_sidebar_key)
        self.sidebar.add_controller(keys)

        self._specs: list[SectionSpec] = []
        self._buttons: dict[str, Gtk.ToggleButton] = {}
        self._sections: dict[str, Any] = {}
        self._hosts: dict[str, _Host] = {}
        self._selected: str | None = None       # remembered while the app runs (not persisted)
        self._active = False
        self._syncing = False
        self._idle_handle = None

    # ---- screen protocol ----
    def on_show(self, section: str | None = None, **_):
        self._active = True
        self._register_idle()
        self._rebuild_sidebar_if_needed()
        if not self._specs:
            return
        ids = [s.id for s in self._specs]
        target = section if section in ids else (self._selected if self._selected in ids else ids[0])
        if target == self._selected:
            self._activate(target)
        else:
            self.select(target)

    def on_hide(self):
        self._active = False
        self._call(self._selected, "on_hide")
        kb = getattr(self.window, "keyboard", None)
        if kb is not None:
            kb.hide()

    def on_key(self, name: str, state) -> bool:
        cur = self._sections.get(self._selected)
        handler = getattr(cur, "on_key", None)
        if handler:
            try:
                if handler(name, state):
                    return True
            except Exception:
                log.exception("section on_key failed")
        if name == "Escape":
            if not self.pop_page(self._selected):
                self._leave()
            return True
        return False

    # ---- sections ----
    def select(self, section_id: str) -> None:
        if section_id == self._selected:
            return
        if self._active:
            self._call(self._selected, "on_hide")
        kb = getattr(self.window, "keyboard", None)
        if kb is not None:
            kb.hide()
        self._selected = section_id
        self._activate(section_id)

    def _activate(self, section_id: str) -> None:
        self._ensure_built(section_id)
        self.content.set_visible_child_name(section_id)
        self._syncing = True
        btn = self._buttons.get(section_id)
        if btn is not None and not btn.get_active():
            btn.set_active(True)
        self._syncing = False
        self._selected = section_id
        if self._active:
            self._call(section_id, "on_show")
            log.info("settings: section %s shown", section_id)

    def _call(self, section_id: str | None, method: str) -> None:
        fn = getattr(self._sections.get(section_id), method, None)
        if fn:
            try:
                fn()
            except Exception:
                log.exception("section %s.%s failed", section_id, method)

    def _ensure_built(self, section_id: str) -> None:
        if section_id in self._sections:
            return
        spec = next(s for s in self._specs if s.id == section_id)
        host = _Host(spec.title)
        self._hosts[section_id] = host
        ctx = SectionContext(
            app=self.app, window=self.window, mode="settings",
            navigate_back=self._leave,
            push_page=lambda w, t, sid=section_id: self.push_page(sid, w, t),
            pop_page=lambda sid=section_id: self.pop_page(sid))
        try:
            section = spec.factory(ctx)
            widget = section.widget
        except Exception:
            log.exception("settings section %s failed to build", section_id)
            section = _Placeholder("This section couldn't be loaded.")
            widget = section.widget
        host.set_root(widget)
        self._sections[section_id] = section
        self.content.add_named(host, section_id)

    def push_page(self, section_id: str, widget: Gtk.Widget, title: str) -> None:
        host = self._hosts[section_id]
        host.push(widget, title, lambda: self.pop_page(section_id))

    def pop_page(self, section_id: str | None) -> bool:
        host = self._hosts.get(section_id)
        return bool(host and host.pop())

    # ---- sidebar ----
    def _rebuild_sidebar_if_needed(self) -> None:
        specs = ordered_sections(self.app)
        if [s.id for s in specs] == [s.id for s in self._specs]:
            return
        self._specs = specs
        child = self.sidebar.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.sidebar.remove(child)
            child = nxt
        self._buttons.clear()
        first = None
        for spec in specs:
            b = Gtk.ToggleButton(label=spec.title, css_classes=["sidebar-item"])
            b.get_child().set_xalign(0)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._on_toggled, spec.id)
            self.sidebar.append(b)
            self._buttons[spec.id] = b

    def _on_toggled(self, btn, section_id):
        if self._syncing or not btn.get_active():
            return
        self.select(section_id)

    def _on_sidebar_key(self, _c, keyval, _kc, _st) -> bool:
        from gi.repository import Gdk
        name = Gdk.keyval_name(keyval)
        if name not in ("Up", "Down") or not self._specs:
            return False
        ids = [s.id for s in self._specs]
        i = ids.index(self._selected) if self._selected in ids else 0
        i = max(0, min(len(ids) - 1, i + (1 if name == "Down" else -1)))
        self.select(ids[i])
        self._buttons[ids[i]].grab_focus()
        return True

    # ---- leaving / inactivity ----
    def _leave(self) -> None:
        self.window.navigator.reset("calendar")

    def _register_idle(self) -> None:
        inactivity = getattr(self.window, "inactivity", None)
        if self._idle_handle is None and inactivity is not None:
            self._idle_handle = inactivity.add_idle_callback(
                IDLE_RETURN_S, safe_callback(self._idle, repeat=False))

    def _idle(self) -> None:
        if self.window.navigator.current != "settings":
            return
        blocking = getattr(self.window, "blocking", None)
        if blocking is not None and blocking.is_open:
            poke = getattr(getattr(self.window, "inactivity", None), "poke", None)
            if poke:
                poke()                       # try again after another full idle period
            return
        log.info("settings: idle return to calendar")
        self._leave()
