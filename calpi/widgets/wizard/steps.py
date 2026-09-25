"""The wizard's steps and the STEPS registry (US-32).

A step is a small object with `.widget`, optional `on_show()` / `on_hide()`, and `next_label`.
It talks to the wizard only through `wiz` (results, `go_next()`, `ctx`). Steps reuse the same
components as the Settings sections; they must not reach for the Settings sidebar or toasts.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from gi.repository import GLib, Gtk

from calpi.data import accounts, formatting
from calpi.data.settings_store import K_SYNC_INTERVAL_MINUTES
from calpi.tasks import safe_callback
from calpi.widgets import icloud_guide
from calpi.widgets.settings.rows import InfoRow, SettingsGroup

log = logging.getLogger("calpi.wizard")

AUTO_NEXT_SECONDS = 1


def _label(text: str, css: str, **kw) -> Gtk.Label:
    return Gtk.Label(label=text, xalign=0, wrap=True, css_classes=[css], **kw)


def _online(app) -> bool:
    mon = getattr(app, "network", None)
    state = getattr(mon, "state", None)
    return getattr(state, "name", "") == "ONLINE"


class Step:
    next_label = "Next"

    def __init__(self, wiz):
        self.wiz = wiz
        self.ctx = wiz.ctx
        self.app = wiz.app
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

    def on_show(self) -> None:
        pass

    def on_hide(self) -> None:
        pass


class WelcomeStep(Step):
    next_label = "Start"

    def __init__(self, wiz):
        super().__init__(wiz)
        self.widget.set_valign(Gtk.Align.CENTER)
        self.widget.append(_label("Welcome to calpi", "wizard-hero"))
        self.widget.append(_label(
            "Let's connect calpi to Wi-Fi and your calendars. You can skip any step and change "
            "everything later in Settings.", "wizard-lead"))


class WifiStep(Step):
    def __init__(self, wiz):
        super().__init__(wiz)
        from calpi.widgets.settings.network import WifiPicker
        self._ssid: str | None = None
        self._auto = 0
        self.banner = _label("", "wizard-banner")
        self.banner.set_visible(False)
        self.widget.append(self.banner)
        self.picker = WifiPicker(self.ctx, on_connected=self._connected, on_networks=self._networks)
        self.widget.append(self.picker)

    def _refresh_banner(self) -> None:
        if self._ssid:
            text = f"Connected to {self._ssid}"
        elif _online(self.app):
            text = "Connected to the network"
        else:
            text = ""
        self.banner.set_text(text)
        self.banner.set_visible(bool(text))

    def _networks(self, nets) -> None:
        cur = next((n for n in nets if n.in_use), None)
        self._ssid = cur.ssid if cur else None
        self._refresh_banner()

    def _connected(self, ssid) -> None:
        self._ssid = ssid
        self._refresh_banner()
        self.wiz.results["wifi"] = "connected"
        if self._auto:
            GLib.source_remove(self._auto)
        self._auto = GLib.timeout_add_seconds(AUTO_NEXT_SECONDS, safe_callback(self._advance))

    def _advance(self) -> bool:
        self._auto = 0
        if self.wiz.current == "wifi" and not self.wiz.host_pages("wifi"):
            self.wiz.go_next()
        return False

    def on_show(self) -> None:
        self._refresh_banner()
        self.picker.on_show()

    def on_hide(self) -> None:
        if self._auto:
            GLib.source_remove(self._auto)
            self._auto = 0
        self.picker.on_hide()


class PreferencesStep(Step):
    def __init__(self, wiz):
        super().__init__(wiz)
        from calpi.widgets.settings.preferences import PreferencesPanel
        self.panel = PreferencesPanel(self.ctx)
        self.widget.append(self.panel)


class AccountStep(Step):
    def __init__(self, wiz):
        super().__init__(wiz)
        self.widget.append(_label(
            "Sign in to your calendar account and choose which calendars to show.", "wizard-lead"))
        self.offline = _label(
            "Needs an internet connection. You can skip this and add an account later in "
            "Settings → Accounts.", "wizard-note")
        self.widget.append(self.offline)
        self.summary = _label("", "wizard-banner")
        self.summary.set_visible(False)
        self.widget.append(self.summary)
        self.add_btn = Gtk.Button(label="Add iCloud account", css_classes=["wide-button"])
        self.add_btn.connect("clicked", lambda *_: self._add())
        self.widget.append(self.add_btn)
        if icloud_guide.AVAILABLE:                                   # US-33
            help_btn = Gtk.Button(label="Help with iCloud sign-in", css_classes=["wide-button"])
            help_btn.connect("clicked", lambda *_: icloud_guide.open_guide(self.ctx))
            self.widget.append(help_btn)
        self._last: accounts.Account | None = None

    def _add(self) -> None:
        from calpi.widgets.settings.accounts import SignInFlow
        SignInFlow(self.ctx, on_finished=self._added).start()

    def _added(self, acc) -> None:
        self._last = acc
        self.wiz.results["account"] = "added"
        self._refresh()

    def _refresh(self) -> None:
        accs = accounts.list_accounts(self.app.settings)
        if accs:
            acc = self._last or accs[-1]
            try:
                n = len(self.app.store.calendars_for_account(acc.id))
            except Exception:
                log.exception("calendar count failed")
                n = 0
            name = acc.username or acc.display_name
            self.summary.set_text(f"Added {name} · {n} calendar{'' if n == 1 else 's'}"
                                  + (f" (and {len(accs) - 1} more account"
                                     f"{'' if len(accs) == 2 else 's'})" if len(accs) > 1 else ""))
            self.summary.set_visible(True)
            self.add_btn.set_label("Add another account")
        else:
            self.summary.set_visible(False)
            self.add_btn.set_label("Add iCloud account")
        self.offline.set_visible(not _online(self.app) and getattr(self.app, "network", None)
                                 is not None)

    def on_show(self) -> None:
        self._refresh()


class RefreshStep(Step):
    def __init__(self, wiz):
        super().__init__(wiz)
        from calpi.widgets.settings.sync import IntervalChooser
        self.widget.append(_label(
            "How often should calpi check your calendars for changes? "
            "15 minutes is recommended.", "wizard-lead"))
        g = SettingsGroup()
        g.add(IntervalChooser(self.ctx))
        self.widget.append(g)


class OvernightStep(Step):
    def __init__(self, wiz):
        super().__init__(wiz)
        from calpi.widgets.settings.display import DimSchedulePanel
        self.widget.append(_label(
            "Dim or turn off the screen at night. Touch wakes it.", "wizard-lead"))
        self.widget.append(DimSchedulePanel(self.ctx))


class DoneStep(Step):
    next_label = "Show calendar"

    def __init__(self, wiz):
        super().__init__(wiz)
        self.widget.append(_label("You're all set", "wizard-hero"))
        self.group = SettingsGroup("Summary")
        self.wifi_row = self.group.add(InfoRow("Wi-Fi", ""))
        self.account_row = self.group.add(InfoRow("Calendar account", ""))
        self.refresh_row = self.group.add(InfoRow("Refresh", ""))
        self.widget.append(self.group)
        self.widget.append(_label("Everything can be changed later in Settings.", "wizard-note"))

    def on_show(self) -> None:
        r = self.wiz.results
        wifi = r.get("wifi") or ("already" if _online(self.app) else "skipped")
        self.wifi_row.set_value({"connected": "Connected", "already": "Connected",
                                 "skipped": "Skipped"}.get(wifi, wifi))
        n = len(accounts.list_accounts(self.app.settings))
        if r.get("account") == "added":
            acc = "Added"
        elif n:
            acc = "Set earlier"
        else:
            acc = "Skipped"
        self.account_row.set_value(acc)
        self.refresh_row.set_value(
            "Every " + formatting.interval_label(self.app.settings.get(K_SYNC_INTERVAL_MINUTES)).lower())


def _overnight_available(_app) -> bool:
    try:
        importlib.import_module("calpi.widgets.settings.display").DimSchedulePanel   # noqa: B018
        return importlib.util.find_spec("calpi.dimming") is not None
    except Exception:
        return False


@dataclass
class StepSpec:
    id: str
    title: str
    factory: Callable[[Any], Step]
    counted: bool = True
    skippable: bool = True
    available: Callable[[Any], bool] = field(default=lambda app: True)


STEPS: list[StepSpec] = [
    StepSpec("welcome", "Welcome", WelcomeStep, counted=False, skippable=False),
    StepSpec("wifi", "Wi-Fi", WifiStep),
    StepSpec("preferences", "Region and time", PreferencesStep),
    StepSpec("account", "Calendar account", AccountStep),
    StepSpec("refresh", "Refresh", RefreshStep),
    StepSpec("overnight", "Overnight", OvernightStep, available=_overnight_available),
    StepSpec("done", "All set", DoneStep, counted=False, skippable=False),
]
