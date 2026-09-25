"""SetupWizard: the first-boot guided setup screen ("wizard") (US-32).

Frame: header (step title + "Step N of M"), body (one lazily built step per stack child, each in a
settings `_Host` so reused components can push sub-pages), fixed footer (Back / Skip / Next).
The footer is hidden while the on-screen keyboard is shown (the keyboard's Done key drives the
form). No inactivity return: the wizard registers no idle callback (US-08/US-22 only act on
their own screens). Escape = Back.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from gi.repository import Gtk

from calpi.data import setup_state
from calpi.data.settings_store import K_SETUP_COMPLETED, K_WIZARD_STEP
from calpi.widgets.settings.shell import SectionContext, _Host
from calpi.widgets.util import set_visible_if_changed
from calpi.widgets.wizard.steps import STEPS

log = logging.getLogger("calpi.wizard")


@dataclass
class WizardContext(SectionContext):
    """A SectionContext in wizard mode; push_page/pop_page act on the current step's page stack."""
    wizard: Any = None


class SetupWizard(Gtk.Box):
    def __init__(self, app, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["screen", "wizard"])
        self.app, self.window = app, window
        self.steps = [s for s in STEPS if s.available(app)]
        self.ids = [s.id for s in self.steps]
        self._spec = {s.id: s for s in self.steps}
        self._built: dict[str, Any] = {}
        self._hosts: dict[str, _Host] = {}
        self.current: str | None = None
        self.results: dict[str, str] = {}      # D7: in-memory only
        self.ctx = WizardContext(
            app=app, window=window, mode="wizard", wizard=self,
            navigate_back=self.back,
            push_page=lambda w, t: self._push(w, t),
            pop_page=lambda: self._pop())

        header = Gtk.Box(spacing=24, css_classes=["wizard-header"])
        self.title = Gtk.Label(label="", xalign=0, hexpand=True, css_classes=["settings-title"])
        self.progress_label = Gtk.Label(label="", xalign=1, css_classes=["wizard-progress"])
        header.append(self.title)
        header.append(self.progress_label)
        self.append(header)
        self.body = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, hexpand=True,
                              vexpand=True)
        self.append(self.body)
        self.footer = Gtk.Box(spacing=24, css_classes=["wizard-footer"])
        self.back_btn = Gtk.Button(label="Back", css_classes=["wizard-button"])
        self.skip_btn = Gtk.Button(label="Skip", css_classes=["wizard-button"])
        self.next_btn = Gtk.Button(label="Next", css_classes=["wizard-button", "suggested"])
        self.back_btn.connect("clicked", lambda *_: self.back())
        self.skip_btn.connect("clicked", lambda *_: self.skip())
        self.next_btn.connect("clicked", lambda *_: self.go_next())
        self.footer.append(self.back_btn)
        self.footer.append(Gtk.Box(hexpand=True))
        self.footer.append(self.skip_btn)
        self.footer.append(self.next_btn)
        self.append(self.footer)
        self._kb_visible = False

    # ---- screen protocol ----
    def on_show(self, **_kw) -> None:
        saved = self.app.settings.get(K_WIZARD_STEP)
        self.go(setup_state.resume_step(self.ids, saved))

    def on_hide(self) -> None:
        if self.current is not None:
            self._step(self.current).on_hide()
            self.current = None

    def on_key(self, name: str, _state) -> bool:
        if name == "Escape":
            self.back()
            return True
        return False

    def on_keyboard_visible(self, visible: bool) -> None:
        self._kb_visible = visible
        set_visible_if_changed(self.footer, not visible)

    # ---- navigation ----
    def _step(self, step_id: str):
        step = self._built.get(step_id)
        if step is None:
            spec = self._spec[step_id]
            step = spec.factory(self)
            host = _Host(spec.title)
            host.set_root(step.widget)
            self._built[step_id] = step
            self._hosts[step_id] = host
            self.body.add_named(host, step_id)
        return step

    def host_pages(self, step_id: str) -> int:
        host = self._hosts.get(step_id)
        return len(host.pages) if host else 0

    def go(self, step_id: str) -> None:
        if self.current == step_id:
            return
        if self.current is not None:
            self._step(self.current).on_hide()
        self.current = step_id
        step = self._step(step_id)
        self.body.set_visible_child_name(step_id)
        spec = self._spec[step_id]
        self.title.set_text(spec.title if step_id != "welcome" else "")
        counted = [s.id for s in self.steps if s.counted]
        prog = setup_state.progress(counted, step_id)
        self.progress_label.set_text(f"Step {prog[0]} of {prog[1]}" if prog else "")
        self._update_footer()
        try:
            self.app.settings.set(K_WIZARD_STEP, step_id)
        except (ValueError, OSError):
            log.exception("could not save the wizard step")
        log.info("wizard: step=%s", step_id)
        step.on_show()

    def _update_footer(self) -> None:
        sid = self.current
        if sid is None:
            return
        spec = self._spec[sid]
        sub = self.host_pages(sid) > 0
        set_visible_if_changed(self.back_btn, sub or sid != self.ids[0])
        set_visible_if_changed(self.skip_btn, spec.skippable and not sub)
        set_visible_if_changed(self.next_btn, not sub)
        self.next_btn.set_label(self._step(sid).next_label)

    def go_next(self) -> None:
        nxt = setup_state.next_step(self.ids, self.current)
        if nxt is None:
            self.finish()
        else:
            self.go(nxt)

    def skip(self) -> None:
        sid = self.current
        if sid in ("wifi", "account") and sid not in self.results:
            self.results[sid] = "skipped"
        self.go_next()

    def back(self) -> None:
        if self.current is None:
            return
        if self.host_pages(self.current):
            self._pop()
            return
        prev = setup_state.prev_step(self.ids, self.current)
        if prev is not None:
            self.go(prev)

    def finish(self) -> None:
        self.app.settings.update({K_SETUP_COMPLETED: True, K_WIZARD_STEP: None})
        log.info("wizard: finished")
        self.window.navigator.reset("calendar")

    # ---- sub-pages inside the current step ----
    def _push(self, widget, title: str) -> None:
        host = self._hosts[self.current]
        host.push(widget, title, self._pop)
        self._update_footer()

    def _pop(self) -> None:
        if self.current is None:
            return
        self._hosts[self.current].pop()
        self._update_footer()
