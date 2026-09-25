"""On-screen keyboard: OnScreenKeyboard (widget), KeyboardDock (overlay + editing).

Never log key presses or entry contents (lengths at most).
"""
from __future__ import annotations

import logging
import time
import weakref

from gi.repository import GLib, Gtk

from calpi.data.keyboard_layouts import LAYOUTS, Key, first_layer, layout_id

log = logging.getLogger("calpi.keyboard")

UNIT = 140
KEY_H = 80
ROW_H = KEY_H + 8            # key + margins
MIN_HEIGHT = 420


def _has_selection(ed: Gtk.Editable) -> bool:
    r = ed.get_selection_bounds()
    if isinstance(r, tuple):
        if len(r) == 3:
            return bool(r[0])
        return len(r) == 2 and r[0] != r[1]
    return bool(r)


def _focus_belongs_to(focus, target) -> bool:
    """True if `focus` is `target` or one of its internals (Entry/PasswordEntry hold a Gtk.Text)."""
    if focus is None or target is None:
        return False
    return focus is target or focus.is_ancestor(target)


class OnScreenKeyboard(Gtk.Box):
    def __init__(self, on_key):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["osk"])
        self._on_key = on_key
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, halign=Gtk.Align.CENTER)
        self.append(self._stack)
        self._built: set[str] = set()
        self._letters: dict[str, list[tuple[Gtk.Button, str]]] = {}
        self._shift_buttons: list[Gtk.Button] = []
        self._done_buttons: list[Gtk.Button] = []
        self._done_label = "Done"
        self.shift = "off"
        self.purpose = None

    def _make_button(self, key: Key, lid: str) -> Gtk.Button:
        btn = Gtk.Button(label=key.label, focusable=False, focus_on_click=False)
        btn.add_css_class("osk-key")
        btn.set_size_request(int(UNIT * key.width), KEY_H)
        if key.insert is None:
            btn.add_css_class("osk-special")
        if key.action == "done":
            btn.add_css_class("osk-done")
            btn.set_label(self._done_label)
            self._done_buttons.append(btn)
        elif key.action == "shift":
            btn.add_css_class("osk-shift")
            self._shift_buttons.append(btn)
        elif key.insert and len(key.insert) == 1 and key.insert.isalpha():
            self._letters.setdefault(lid, []).append((btn, key.insert))
        btn.connect("clicked", lambda _b, k=key: self._on_key(k))
        return btn

    def _build(self, purpose: str) -> None:
        lid = layout_id(purpose)
        if lid in self._built:
            return
        for name, rows in LAYOUTS[lid].items():
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            for row in rows:
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.CENTER)
                for key in row:
                    box.append(self._make_button(key, lid))
                page.append(box)
            self._stack.add_named(page, f"{lid}/{name}")
        self._built.add(lid)

    def set_purpose(self, purpose: str) -> None:
        self._build(purpose)
        self.purpose = purpose
        self.set_shift("off")
        self.set_layer(first_layer(purpose))

    def set_layer(self, name: str) -> None:
        self._stack.set_visible_child_name(f"{layout_id(self.purpose)}/{name}")

    def set_done_label(self, text: str) -> None:
        self._done_label = text
        for b in self._done_buttons:
            if b.get_label() != text:
                b.set_label(text)

    def set_shift(self, state: str) -> None:
        self.shift = state
        upper = state != "off"
        for lid, items in self._letters.items():
            for btn, ch in items:
                label = ch.upper() if upper else ch
                if btn.get_label() != label:
                    btn.set_label(label)
        for b in self._shift_buttons:
            b.remove_css_class("on")
            b.remove_css_class("lock")
            if state == "once":
                b.add_css_class("on")
            elif state == "lock":
                b.add_css_class("lock")


class KeyboardDock(Gtk.Box):
    HEIGHT = MIN_HEIGHT

    def __init__(self, window):
        super().__init__(valign=Gtk.Align.END, halign=Gtk.Align.FILL, css_classes=["osk-dock"])
        self._window = window
        self.set_visible(False)
        self.osk: OnScreenKeyboard | None = None
        self._target_ref = None
        self._on_done = None
        self._purpose = "text"
        self.reserved_height = self.HEIGHT
        window.overlay.add_overlay(self)
        self._wrap_navigator(window.navigator)

    # -- public API -------------------------------------------------------
    def attach(self, editable, purpose="text", done_label="Done", on_done=None) -> None:
        ref = weakref.ref(editable)
        args = (purpose, done_label, on_done)

        def enter(*_):
            ed = ref()
            if ed is not None:
                self._show_for(ed, *args)

        fc = Gtk.EventControllerFocus()
        fc.connect("enter", enter)
        fc.connect("leave", lambda *_: GLib.idle_add(self._maybe_hide))
        editable.add_controller(fc)
        # Tapping an already-focused entry after the keyboard was hidden shows it again.
        gc = Gtk.GestureClick()
        gc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gc.connect("released", lambda *_: enter())
        editable.add_controller(gc)

    def is_shown(self) -> bool:
        return self.get_visible()

    def hide(self) -> None:
        if self.get_visible():
            self.set_visible(False)
            self._notify(False)

    # -- internals --------------------------------------------------------
    def _target(self):
        return self._target_ref() if self._target_ref else None

    def _wrap_navigator(self, nav) -> None:
        orig = nav.show

        def show(name, **params):
            self.hide()
            orig(name, **params)
        nav.show = show

    def _notify(self, visible: bool) -> None:
        nav = self._window.navigator
        screen = nav.get(nav.current) if nav.current else None
        cb = getattr(screen, "on_keyboard_visible", None)
        if cb:
            try:
                cb(visible)
            except Exception:
                log.exception("on_keyboard_visible failed")

    def _show_for(self, ed, purpose, done_label, on_done) -> None:
        t0 = time.monotonic()
        if self.osk is None:
            self.osk = OnScreenKeyboard(self._apply)
            self.append(self.osk)
        if self._target() is not ed or not self.get_visible() or purpose != self._purpose:
            self.osk.set_purpose(purpose)
            if purpose == "text" and not ed.get_text():
                self.osk.set_shift("once")
        self.osk.set_done_label(done_label)
        self._target_ref = weakref.ref(ed)
        self._on_done = on_done
        self._purpose = purpose
        rows = len(LAYOUTS[layout_id(purpose)][first_layer(purpose)])
        self.reserved_height = max(self.HEIGHT, rows * ROW_H + 40)
        self.set_size_request(-1, self.reserved_height)
        was = self.get_visible()
        self.set_visible(True)
        if not was:
            self._notify(True)
        log.debug("perf: osk_show %.1f ms", (time.monotonic() - t0) * 1000)

    def _maybe_hide(self):
        root = self.get_root()
        focus = root.get_focus() if root else None
        if not _focus_belongs_to(focus, self._target()):
            self.hide()
        return GLib.SOURCE_REMOVE

    def _apply(self, key: Key) -> None:
        ed = self._target()
        if ed is None:
            self.hide()
            return
        osk = self.osk
        if key.insert is not None:
            ch = key.insert
            if osk.shift != "off" and len(ch) == 1 and ch.isalpha():
                ch = ch.upper()
            self._insert(ed, ch)
            if osk.shift == "once":
                osk.set_shift("off")
            return
        act = key.action or ""
        if act == "backspace":
            self._backspace(ed)
        elif act == "left":
            ed.set_position(max(0, ed.get_position() - 1))
        elif act == "right":
            ed.set_position(ed.get_position() + 1)
        elif act == "space":
            self._insert(ed, " ")
        elif act == "clear":
            ed.set_text("")
        elif act == "shift":
            osk.set_shift({"off": "once", "once": "lock", "lock": "off"}[osk.shift])
        elif act == "hide":
            self.hide()
        elif act == "done":
            if self._on_done is not None:
                self._on_done()
            else:
                ed.emit("activate")
        elif act.startswith("layer:"):
            osk.set_layer(act.split(":", 1)[1])

    @staticmethod
    def _insert(ed, text: str) -> None:
        if _has_selection(ed):
            ed.delete_selection()
        pos = ed.get_position()
        try:
            new_pos = ed.insert_text(text, pos)         # PyGObject override: (text, position)
        except TypeError:
            new_pos = ed.insert_text(text, -1, pos)
        ed.set_position(new_pos if isinstance(new_pos, int) else pos + len(text))

    @staticmethod
    def _backspace(ed) -> None:
        if _has_selection(ed):
            ed.delete_selection()
            return
        pos = ed.get_position()
        if pos > 0:
            ed.delete_text(pos - 1, pos)


def make_password_field():
    """(box, entry, toggle): a masked Gtk.Entry plus a 72x72 Show/Hide button."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
    entry = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD, hexpand=True)
    entry.add_css_class("osk-entry")
    toggle = Gtk.Button(label="Show", focusable=False, focus_on_click=False)
    toggle.set_size_request(96, 72)

    def flip(_b):
        vis = not entry.get_visibility()
        entry.set_visibility(vis)
        toggle.set_label("Hide" if vis else "Show")
    toggle.connect("clicked", flip)
    box.append(entry)
    box.append(toggle)
    return box, entry, toggle
