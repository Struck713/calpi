"""One-slot problem banner (US-38) and the controller that decides what it and the header show.

The banner sits in the calendar's weekday-row slot (MonthView swaps them, so the grid's geometry does
not change). It never opens a dialog. Rules and wording live in calpi.data.problem_rules / messages.
"""
from __future__ import annotations

import logging

from gi.repository import GLib, Gtk, Pango

from calpi.data import messages, problem_rules, timeutil
from calpi.widgets.util import set_text_if_changed

log = logging.getLogger("calpi.problems")

DEVICE_PROBE_S = 300


class ProblemBanner(Gtk.Box):
    def __init__(self, on_fix=None, on_dismiss=None, on_open_status=None):
        super().__init__(spacing=12, css_classes=["problem-banner"], visible=False)
        self._sev = None
        self._on_fix, self._on_dismiss, self._on_status = on_fix, on_dismiss, on_open_status
        self.text_button = Gtk.Button(css_classes=["problem-text-button"], hexpand=True, focus_on_click=False)
        self.text = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, css_classes=["problem-text"], hexpand=True)
        self.text_button.set_child(self.text)
        self.text_button.connect("clicked", lambda *_: self._on_status and self._on_status())
        self.fix_button = Gtk.Button(css_classes=["problem-fix"], focus_on_click=False, visible=False)
        self.fix_button.connect("clicked", lambda *_: self._on_fix and self._on_fix())
        self.dismiss_button = Gtk.Button(label="✕", css_classes=["problem-dismiss"], focus_on_click=False)
        self.dismiss_button.connect("clicked", lambda *_: self._on_dismiss and self._on_dismiss())
        for w in (self.text_button, self.fix_button, self.dismiss_button):
            self.append(w)

    def show_message(self, msg: messages.Message | None) -> None:
        if msg is None:
            if self.get_visible():
                self.set_visible(False)
            return
        text = msg.title + ((" · " + msg.detail) if msg.detail else "")
        set_text_if_changed(self.text, text)
        if msg.severity != self._sev:
            if self._sev:
                self.remove_css_class(self._sev)
            self.add_css_class(msg.severity)
            self._sev = msg.severity
        label = msg.fix_label or ""
        if self.fix_button.get_label() != label:
            self.fix_button.set_label(label)
        if self.fix_button.get_visible() != bool(label):
            self.fix_button.set_visible(bool(label))
        if not self.get_visible():
            self.set_visible(True)


class ProblemController:
    """Collects problems, drives the banner and the header indicator. All on the main thread."""

    def __init__(self, app, banner: ProblemBanner, indicator=None):
        self.app, self.banner, self.indicator = app, banner, indicator
        self.started_at = timeutil.now()
        self.dismissals = problem_rules.Dismissals(app.settings)
        self._offline_since = None
        self._clock_since = None
        self._device_codes: tuple[str, ...] = ()
        self._device_busy = False
        self._probe_at = -1e9
        self._current: problem_rules.Problem | None = None
        banner._on_fix = self.fix
        banner._on_dismiss = self.dismiss
        banner._on_status = self.open_status
        app.status_callbacks.append(lambda _s: self.refresh())
        net, ct = getattr(app, "network", None), getattr(app, "clock_trust", None)
        if net is not None:
            net.callbacks.append(lambda _o, _n: self.refresh())
        if ct is not None:
            ct.callbacks.append(lambda _s: self.refresh())
        GLib.timeout_add_seconds(60, self._tick)
        self.refresh()

    def _tick(self):
        try:
            self.refresh()
        except Exception:
            log.exception("problem refresh failed")
        return GLib.SOURCE_CONTINUE

    # --- inputs ---
    def in_wizard(self) -> bool:
        win = self.app.window
        return win is not None and win.navigator.current == "wizard"

    def _account_info(self) -> dict:
        from calpi.data import accounts
        from calpi.sync import providers
        info = {}
        try:
            for a in accounts.list_accounts(self.app.settings):
                try:
                    pn = providers.get(a.provider).display_name
                except Exception:
                    pn = a.provider
                info[a.id] = (pn, a.display_name or a.username)
        except Exception:
            log.exception("account info failed")
        return info

    def _probe_device(self) -> None:
        import time
        from calpi.system import device_info
        from calpi.tasks import run_in_thread
        if self._device_busy or time.monotonic() - self._probe_at < DEVICE_PROBE_S:
            return
        self._device_busy, self._probe_at = True, time.monotonic()

        def done(info):
            self._device_busy = False
            codes = tuple(c for c, on in (("POWER_UNDERVOLTAGE", info.undervoltage_now),
                                          ("TEMP_HIGH", info.temp_high), ("DISK_LOW", info.disk_low)) if on)
            if codes != self._device_codes:
                self._device_codes = codes
                self.refresh()

        def failed(_e):
            self._device_busy = False
        run_in_thread(device_info.collect, on_done=done, on_error=failed, name="problem-device")

    def problems(self) -> list[problem_rules.Problem]:
        now = timeutil.now()
        app = self.app
        net = getattr(app, "network", None)
        net_down = net is not None and net.state.value in ("offline", "limited")
        if net_down or getattr(getattr(app, "sync", None), "offline", False):
            self._offline_since = self._offline_since or now
        else:
            self._offline_since = None
        ct = getattr(app, "clock_trust", None)
        if ct is not None and ct.synced is False:
            self._clock_since = self._clock_since or now
        else:
            self._clock_since = None
        notices = tuple(app.startup_notices)
        if app.safe_mode and "safe_mode" not in notices:
            notices += ("safe_mode",)
        inp = problem_rules.ProblemInputs(
            snapshot=app.sync_status, startup_notices=notices, started_at=self.started_at,
            offline_since=self._offline_since, clock_unsynced_since=self._clock_since,
            device_codes=self._device_codes, account_info=self._account_info())
        return problem_rules.collect(inp, now)

    # --- outputs ---
    def refresh(self) -> None:
        now = timeutil.now()
        self.dismissals.prune(now)
        self._probe_device()
        probs = self.problems()
        wiz = self.in_wizard()
        top = problem_rules.visible_banner(probs, now, self.dismissals.items, wiz)
        self._current = top
        self.banner.show_message(self._msg(top, "banner") if top else None)
        mv = getattr(getattr(self.app, "window", None), "month_view", None)
        if mv is not None and hasattr(mv, "set_banner_visible"):
            mv.set_banner_visible(top is not None)
        if self.indicator is not None:
            hp = problem_rules.header_problem(probs, now, wiz)
            self.indicator.set_problem(self._msg(hp, "header") if hp else None)

    def _msg(self, p, ctx) -> messages.Message:
        return messages.describe(p.code, context=ctx, provider=p.provider, account=p.account)

    # --- actions ---
    def dismiss(self) -> None:
        if self._current is not None:
            self.dismissals.dismiss(self._current, timeutil.now())
            self.refresh()

    def open_status(self) -> None:
        self.app.window.navigator.show("settings", section="status")

    def fix(self) -> None:
        p = self._current
        if p is None:
            return
        target = messages.entry_for(p.code).fix_target
        nav = self.app.window.navigator
        if target == "update_password":
            nav.show("settings", section="accounts")
            sec = getattr(nav.get("settings"), "_sections", {}).get("accounts")
            if sec is not None and hasattr(sec, "open_update_password"):
                sec.open_update_password(p.account_id)
        elif target:
            nav.show("settings", section=target)
