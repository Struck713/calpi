"""Header sync status (US-16): 'Updating…' while a run is active, else 'Updated HH:MM'.

US-17 (offline), US-19 (refresh button) and US-38 (errors) extend this class.
"""
from __future__ import annotations

import time
from datetime import datetime

from gi.repository import GLib, Gtk

from calpi.data import formatting, sync_text, timeutil
from calpi.widgets.util import set_text_if_changed


def indicator_text(running: bool, last_success: datetime | None, now: datetime) -> str:
    if running:
        return "Updating…"
    if last_success is None:
        return ""
    t = last_success.astimezone(now.tzinfo)
    when = formatting.short_time(t)
    if t.date() == now.date():
        return f"Updated {when}"
    if (now.date() - t.date()).days == 1:
        return f"Updated yesterday {when}"
    return f"Updated {t.day} {t:%b} {when}"


class SyncIndicator(Gtk.Label):
    MIN_RUNNING_S = 1.0            # US-19 D4: "Updating…" stays visible at least this long

    def __init__(self, engine, clock=None, provider_names=None):
        super().__init__(css_classes=["sync-status"], visible=False)
        self.engine = engine
        self._provider_names = provider_names          # () -> {account_id: provider name}, optional
        self._transient: tuple[str, str, float] | None = None    # (text, css state, expiry monotonic)
        self._started_mono = 0.0
        self._hold_until = 0.0
        click = Gtk.GestureClick()
        click.connect("released", self._open_status)
        self.add_controller(click)
        engine.state_callbacks.append(self._on_state)
        engine.result_callbacks.append(self._on_result)
        if clock is not None:
            clock.subscribe_minute(lambda _now: self.update())
        self.update()

    _problem_text: str | None = None       # US-38: header text of an actionable problem

    def set_problem(self, msg) -> None:
        """US-38: show (or clear) the error state; `msg` is a messages.Message for context 'header'."""
        text = msg.title if msg is not None else None
        if text != self._problem_text:
            self._problem_text = text
            self.update()

    def _open_status(self, *_a) -> None:
        root = self.get_root()
        if root is not None and hasattr(root, "navigator") and self._problem_text:
            root.navigator.show("settings", section="status")

    network = None                 # US-17: NetworkMonitor / ClockTrust, set by bind_status()
    clock_trust = None

    def bind_status(self, network=None, clock_trust=None) -> None:
        """US-17: also refresh on network / clock-trust changes."""
        self.network, self.clock_trust = network, clock_trust
        if network is not None:
            network.callbacks.append(lambda _o, _n: self.update())
        if clock_trust is not None:
            clock_trust.callbacks.append(lambda _s: self.update())
        self.update()

    def _on_state(self, running: bool) -> None:
        now = time.monotonic()
        if running:
            self._started_mono = now
        else:
            left = self._started_mono + self.MIN_RUNNING_S - now
            if left > 0:
                self._hold_until = now + left
                GLib.timeout_add(int(left * 1000) + 20, self._release)
        self.update()

    def _release(self):
        self.update()
        return GLib.SOURCE_REMOVE

    def _on_result(self, r: dict) -> None:
        if sync_text.is_manual(r):
            if sync_text.is_success(r):
                self.show_transient("Updated just now", "ok", 5)
            else:
                names = self._provider_names() if self._provider_names else None
                self.show_transient(sync_text.manual_result_text(r, names), "error", 10)
        else:
            self.update()

    def show_transient(self, text: str, state: str, seconds: int) -> None:
        """Temporarily replace the status text (US-19 D3); state is a css class ('ok' or 'error')."""
        self._transient = (text, state, time.monotonic() + seconds)
        GLib.timeout_add(int(seconds * 1000) + 50, self._release)
        self.update()

    def update(self) -> None:
        now_m = time.monotonic()
        running = self.engine.is_running or now_m < self._hold_until
        if self._transient is not None and now_m >= self._transient[2]:
            self._transient = None
        tr = self._transient if not running else None
        if tr:
            text, state = tr[0], tr[1]
        else:
            net = self.network.state.value if self.network is not None else None
            synced = self.clock_trust.synced if self.clock_trust is not None else None
            css, text = sync_text.compute_state(running, getattr(self.engine, "offline", False), synced,
                                                net, self.engine.last_success_wall, timeutil.now(),
                                                error=self._problem_text)
            state = css if css in ("offline", "stale", "clock", "error") else ""
        for c in ("ok", "error", "offline", "stale", "clock"):
            if (c == state) != self.has_css_class(c):
                (self.add_css_class if c == state else self.remove_css_class)(c)
        set_text_if_changed(self, text)
        if self.get_visible() != bool(text):
            self.set_visible(bool(text))
