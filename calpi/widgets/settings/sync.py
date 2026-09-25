"""Sync section (US-27): refresh interval, last/next update. `IntervalChooser` is reused by the wizard."""
from __future__ import annotations

import logging

from gi.repository import GLib, Gtk

from calpi.data import formatting, timeutil
from calpi.data.settings_store import K_SYNC_INTERVAL_MINUTES, SYNC_INTERVAL_CHOICES
from calpi import tasks
from calpi.tasks import safe_callback
from calpi.widgets.settings.registry import SectionSpec, register_section
from calpi.widgets.settings.rows import ButtonRow, InfoRow, ListPickerPage, ListPickerRow, SettingsGroup

log = logging.getLogger("calpi.settings.sync")

RECOMMENDED_MINUTES = 15
REFRESH_SECONDS = 30


class IntervalChooser(ListPickerRow):
    def __init__(self, ctx, on_changed=None):
        self.ctx = ctx
        self.on_changed = on_changed
        settings = ctx.app.settings
        super().__init__("Refresh every", formatting.interval_label(settings.get(K_SYNC_INTERVAL_MINUTES)),
                         self._open)
        self._token = settings.subscribe(
            K_SYNC_INTERVAL_MINUTES, lambda _k, v: self.set_value(formatting.interval_label(v)))
        self.connect("destroy", lambda *_: settings.unsubscribe(self._token))

    def _open(self) -> None:
        items = [(m, formatting.interval_label(m) + (" (recommended)" if m == RECOMMENDED_MINUTES else ""))
                 for m in SYNC_INTERVAL_CHOICES]
        page = ListPickerPage(items, self._pick,
                              current=self.ctx.app.settings.get(K_SYNC_INTERVAL_MINUTES))
        self.ctx.push_page(page, "Refresh every")

    def _pick(self, minutes: int) -> None:
        try:
            self.ctx.app.settings.set(K_SYNC_INTERVAL_MINUTES, minutes)
        except (ValueError, OSError):
            log.exception("could not save the sync interval")
            if self.ctx.mode == "settings":
                self.ctx.app.toast("Couldn't save the refresh interval")
            return
        self.ctx.pop_page()
        if self.ctx.mode == "settings":
            self.ctx.app.toast(f"Calendars will refresh every {formatting.interval_label(minutes)}")
        if self.on_changed:
            self.on_changed(minutes)


class SyncSection:
    def __init__(self, ctx):
        self.ctx = ctx
        self.app = ctx.app
        self._timer = 0
        self._engine = None
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        g = SettingsGroup("Updates")
        self.chooser = g.add(IntervalChooser(ctx))
        self.last_row = g.add(InfoRow("Last updated"))
        self.next_row = g.add(InfoRow("Next update"))
        self.sync_now = g.add(ButtonRow("Update now", "Sync now", self._sync_now))
        root.append(g)
        root.append(Gtk.Label(
            label="calpi checks your calendars in the background. More frequent updates use a "
                  "little more network data.",
            css_classes=["row-desc"], xalign=0, wrap=True, margin_top=16, margin_start=16))
        self.widget = root
        self._refresh()

    def _sync_now(self) -> None:
        """US-19's manual refresh (ignored while running / right after a successful one)."""
        trig = getattr(self.app, "trigger_manual_refresh", None)
        if trig is not None:
            trig()

    # ---- lifecycle: timers/callbacks only while visible ----
    def on_show(self, **_kw) -> None:
        self._engine = getattr(self.app, "sync", None)
        if self._engine is not None:
            if self._on_result not in self._engine.result_callbacks:
                self._engine.result_callbacks.append(self._on_result)
            if self._on_state not in self._engine.state_callbacks:
                self._engine.state_callbacks.append(self._on_state)
        self._token = self.app.settings.subscribe(K_SYNC_INTERVAL_MINUTES, self._on_interval)
        if not self._timer:
            self._timer = tasks.add_periodic_seconds("sync-screen", REFRESH_SECONDS, self._tick)
        self._refresh()

    def on_hide(self) -> None:
        if self._timer:
            tasks.remove_periodic("sync-screen")
            self._timer = 0
        eng = self._engine
        if eng is not None:
            for lst, cb in ((eng.result_callbacks, self._on_result), (eng.state_callbacks, self._on_state)):
                if cb in lst:
                    lst.remove(cb)
        tok = getattr(self, "_token", None)
        if tok is not None:
            self.app.settings.unsubscribe(tok)
            self._token = None

    @safe_callback(repeat=True)
    def _tick(self):
        self._refresh()

    def _on_result(self, _r) -> None:
        self._refresh()

    def _on_state(self, _running) -> None:
        self._refresh()

    def _on_interval(self, _k, _v) -> None:
        self._refresh()      # the engine subscribed earlier (at start), so it has already re-armed

    def _refresh(self) -> None:
        eng = getattr(self.app, "sync", None)
        if eng is None:
            return
        now = timeutil.now()
        self.sync_now.button.set_sensitive(not eng.is_running)
        self.last_row.set_value(formatting.relative_datetime(eng.last_success_wall, now))
        self.next_row.set_value(formatting.next_update_text(
            eng.next_run_in_seconds(), eng.is_running,
            offline=bool(getattr(eng, "offline", False)),
            safe_mode=bool(getattr(self.app, "safe_mode", False))))


register_section(SectionSpec("sync", "Sync", 40, SyncSection))
