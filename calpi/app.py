from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from gi.repository import Gdk, GLib, Gtk

from calpi import __version__, crashguard, paths, watchdog
from calpi.input import (CursorManager, KeyRouter, WindowEventHub, check_targets_enabled,
                         install_target_checker)
from calpi.inactivity import DEFAULT_RETURN_SECONDS, InactivityMonitor
from calpi.data import timeutil, week_layout
from calpi.tasks import safe_callback
from calpi.widgets.day_detail import DayDetail
from calpi.widgets.keyboard import KeyboardDock
from calpi.widgets.overlays import BlockingOverlay, ConfirmDialog, Toast
from calpi.widgets.settings.shell import SettingsScreen
from calpi.widgets.month_view import MonthView
from calpi.widgets.view_switcher import screen_for, view_for_screen
from calpi.widgets.week_view import WeekView
from calpi.widgets.agenda_view import AgendaView
from calpi.widgets.util import add_style_provider

log = logging.getLogger("calpi.app")


def _build_stamp() -> str:
    """Contents of calpi/BUILD (written by scripts/pi deploy), or 'dev'."""
    try:
        return (paths.app_dir() / "BUILD").read_text().strip() or "dev"
    except OSError:
        return "dev"


class Navigator:
    """Switches screens in the root Gtk.Stack and calls on_show/on_hide hooks."""

    def __init__(self, stack: Gtk.Stack):
        self._stack = stack
        self._screens: dict[str, Gtk.Widget] = {}
        self._history: list[str] = []

    def add(self, name: str, widget: Gtk.Widget) -> None:
        self._screens[name] = widget
        self._stack.add_named(widget, name)

    def get(self, name: str) -> Gtk.Widget | None:
        return self._screens.get(name)

    @property
    def current(self) -> str | None:
        return self._stack.get_visible_child_name()

    def show(self, name: str, **params) -> None:
        cur = self.current
        if cur == name and not params:
            return
        if cur is not None:
            old = self._screens[cur]
            if hasattr(old, "on_hide"):
                old.on_hide()
            if cur != name:
                self._history.append(cur)
                del self._history[:-10]           # bounded: long uptime (US-37)
        self._stack.set_visible_child_name(name)
        new = self._screens[name]
        if hasattr(new, "on_show"):
            new.on_show(**params)
        log.info("screen=%s", name)

    def back(self, default: str = "calendar") -> None:
        target = self._history.pop() if self._history else default
        self.show(target)

    def reset(self, name: str = "calendar") -> None:
        self._history.clear()
        self.show(name)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: "CalpiApp", windowed: bool):
        super().__init__(application=app, title="calpi")
        self.overlay = Gtk.Overlay()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, hexpand=True, vexpand=True)
        self.overlay.set_child(self.stack)
        self.set_child(self.overlay)
        self.navigator = Navigator(self.stack)
        self.hub = WindowEventHub(self)                 # the single capture controller (US-11)
        self.cursor = CursorManager(self, self.hub)
        self.keys = KeyRouter(self, self.navigator)
        self.keyboard = KeyboardDock(self)             # US-21: one on-screen keyboard dock
        # US-22 overlays, created after the keyboard so they sit above it
        self.confirm = ConfirmDialog(self)
        self.blocking = BlockingOverlay(self)
        self.toast_widget = Toast(self)
        # US-29: software dim layer above everything (US-30's wake-catcher goes above it)
        self.dim_layer = Gtk.Box(css_classes=["dim-layer"], can_target=False, visible=False,
                                 hexpand=True, vexpand=True)
        self.overlay.add_overlay(self.dim_layer)
        self._dim_alpha = 0.0
        app.brightness = self._make_brightness(app)
        if check_targets_enabled():
            install_target_checker(self.navigator)
        self.month_view = MonthView(week_start=app.week_start)      # US-28
        self.month_view.attach_store(app.store)         # US-07
        app.calendar_colors = self.month_view.colors
        self.navigator.add("calendar", self.month_view)
        self.day_detail = DayDetail(app.store, self.month_view.colors, self.navigator,
                                    self.month_view)                        # US-09
        self.navigator.add("day", self.day_detail)
        self.navigator.add("settings", SettingsScreen(app, self))          # US-22
        self.week_view = WeekView(week_start=app.week_start)                # US-39
        self.week_view.attach_store(app.store, self.month_view.colors)
        self.navigator.add("week", self.week_view)
        self.agenda_view = AgendaView()                                     # US-40
        self.agenda_view.attach_store(app.store, self.month_view.colors)
        self.navigator.add("agenda", self.agenda_view)
        app.clock.subscribe_day_changed(self._on_day_changed)
        from calpi.data import accounts as accounts_mod, setup_state           # US-32
        from calpi.data.settings_store import K_SETUP_COMPLETED
        from calpi.widgets.wizard.wizard import SetupWizard
        screen, mig = setup_state.decide_start_screen(
            app.settings.get(K_SETUP_COMPLETED) or os.environ.get("CALPI_SKIP_SETUP") == "1",
            len(accounts_mod.list_accounts(app.settings)),
            bool(getattr(app, "safe_mode", False)))
        if mig:
            app.settings.update(mig)
            log.info("setup: marked complete (existing accounts)")
        self.navigator.add("wizard", SetupWizard(app, self))
        self.navigator.reset(self._default_screen(app) if screen == "calendar" else screen)
        log.info("setup: start screen=%s", screen)
        if os.environ.get("CALPI_DEV_OSK") == "1":     # dev only (US-21)
            from calpi.widgets.dev_osk_demo import DevOskDemo
            self.navigator.add("dev_osk", DevOskDemo(self))
            self.navigator.show("dev_osk")
        self.inactivity = InactivityMonitor(self.hub)
        self._return_handle = self.inactivity.add_idle_callback(
            self._return_seconds(), self._on_idle_return)
        self._wire_return_setting(app)
        # US-30: the wake catcher must be the LAST overlay added (topmost). Add new overlays above.
        from calpi.dimming import create_controller
        app.dimming = create_controller(app, self)
        self.wake_catcher = app.dimming.catcher
        if windowed:
            self.set_default_size(1920, 1080)
            self._install_dev_shortcuts()
        else:
            self.fullscreen()

    def on_data_changed(self) -> None:
        """Called after a sync/settings change (US-16, US-26, US-28): refresh what is showing."""
        self.month_view.reload()
        self.week_view.reload()
        self.agenda_view.reload()
        self.day_detail.reload()

    def _apply_dim(self, alpha: float) -> None:
        """Main thread. Only touches the layer when the value changes; hidden entirely at 0."""
        if abs(alpha - self._dim_alpha) < 0.001:
            return
        self._dim_alpha = alpha
        if alpha <= 0.001:
            self.dim_layer.set_visible(False)
        else:
            self.dim_layer.set_opacity(alpha)
            self.dim_layer.set_visible(True)

    def _make_brightness(self, app):
        from calpi.data.settings_store import K_BRIGHTNESS
        from calpi.system.brightness import BrightnessController
        from calpi.tasks import call_on_main, run_in_thread
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="brightness")
        return BrightnessController(
            app.settings, K_BRIGHTNESS, self._apply_dim, call_on_main=call_on_main,
            run_async=lambda fn: pool.submit(fn),
            probe_async=lambda work, done, err: run_in_thread(
                work, on_done=done, on_error=err, name="brightness-probe"))

    def _on_day_changed(self, old, new):
        wv = self.week_view
        if wv.first_day == week_layout.week_start_of(old, wv.week_start):
            wv.show_week(new)               # was showing the current week: follow midnight
        else:
            wv.refresh_today()
        self.agenda_view.refresh_today()
        mv = self.month_view
        was_current = (mv.year, mv.month) == (old.year, old.month)
        if was_current and (new.year, new.month) != (old.year, old.month):
            mv.show_month(new.year, new.month)
        else:
            mv.refresh_today()
            if hasattr(mv, "reload"):
                mv.reload(force=True)
        if hasattr(self, "on_data_changed"):
            self.on_data_changed()

    def _return_seconds(self) -> int:
        settings = getattr(self.get_application(), "settings", None)
        if settings is None:
            return DEFAULT_RETURN_SECONDS
        from calpi.data.settings_store import K_INACTIVITY_RETURN_SECONDS
        return settings.get(K_INACTIVITY_RETURN_SECONDS)

    def _wire_return_setting(self, app) -> None:
        if app.settings is None:
            return
        from calpi.data.settings_store import K_INACTIVITY_RETURN_SECONDS
        app.settings.subscribe(
            K_INACTIVITY_RETURN_SECONDS,
            lambda _k, v: self.inactivity.tracker.set_timeout(self._return_handle, v))

    def _default_screen(self, app=None) -> str:
        app = app or self.get_application()
        from calpi.data.settings_store import K_DEFAULT_VIEW
        if app is None or app.settings is None:
            return "calendar"
        return screen_for(app.settings.get(K_DEFAULT_VIEW))

    def _on_idle_return(self) -> None:
        """US-08/US-39: back to the default view's current period."""
        cur = self.navigator.current
        if cur == "day" or view_for_screen(cur) is not None:
            target = self._default_screen()
            if cur != target:
                self.navigator.reset(target)
            self.navigator.get(target).go_today(reason="inactivity")

    def show_view(self, view: str, reason: str = "switcher") -> None:
        """Switch between Month/Week/... keeping the period aligned (US-39 D5)."""
        cur = self.navigator.get(self.navigator.current)
        target = self.navigator.get(screen_for(view))
        if target is None or target is cur:
            return
        anchor = cur.anchor_date() if hasattr(cur, "anchor_date") else timeutil.today()
        self.navigator.reset(screen_for(view))
        target.show_date(anchor)
        log.info("view: %s (reason=%s)", view, reason)

    def _install_dev_shortcuts(self):
        def _quit(_widget, _args, *_rest):
            self.get_application().quit()
            return True

        ctl = Gtk.ShortcutController()
        ctl.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>q"),
            Gtk.CallbackAction.new(_quit)))
        self.add_controller(ctl)


class CalpiApp(Gtk.Application):
    def __init__(self, args: argparse.Namespace):
        super().__init__(application_id="dev.calpi.Kiosk")
        self.args = args
        self.window: MainWindow | None = None
        self.settings = None            # SettingsStore, created in _on_activate
        self.clock = None               # ClockService, created in _on_activate
        self.week_start = 0             # US-28, applied from settings before the window
        self.store = None               # EventStore, created in _on_activate (US-07)
        self.calendar_colors = None     # CalendarColors, shared with later views (US-07)
        self.credentials = None         # CredentialStore, created in _on_activate (US-13)
        self.dimming = None             # DimController, created with the window (US-30)
        self.safe_mode = False          # US-12: crash loop detected; extras/auto-sync must check it
        self.sync = None                # SyncEngine, created in _on_activate (US-16)
        self.sync_status = None         # StatusSnapshot (US-18), refreshed after every sync result
        self.status_callbacks: list = []    # US-18: called with the new snapshot
        self.network = None             # NetworkMonitor (US-17)
        self.clock_trust = None         # ClockTrust (US-17)
        self.weather = None             # WeatherService, created in _on_activate (US-41)
        if not hasattr(self, "startup_notices"):
            self.startup_notices: list[str] = []
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app):
        if self.window is not None:          # activate can fire twice; keep one window
            self.window.present()
            return
        self.safe_mode = crashguard.record_start_and_check()      # US-12 D4, before anything else
        if self.safe_mode:
            self.startup_notices.append("safe_mode")
        crashguard.test_crash_point("start", self.safe_mode)
        from calpi.data import db
        if db.recover_if_corrupt():                               # US-12 D8, before any store opens
            self.startup_notices.append("db_reset")
        from calpi.data.settings_store import SettingsStore
        self.settings = SettingsStore()
        log.info("settings loaded from %s", self.settings.path)
        from calpi.data.credentials import CredentialStore
        self.credentials = CredentialStore()
        st = self.credentials.status()
        log.info("credentials: %s (%d stored)", st, len(self.credentials.ids()) if st == "ok" else 0)
        if st == "unreadable":
            self.startup_notices.append("credentials_unreadable")
        Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
        provider = Gtk.CssProvider()
        provider.load_from_path(str(paths.app_dir() / "style.css"))
        add_style_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._maybe_load_sample_data()
        from calpi.data.event_store import EventStore
        self.store = EventStore()       # the UI process's one store (US-07)
        self.reconcile_accounts()       # US-25 D5
        from calpi.clock import ClockService
        self.clock = ClockService()
        self._apply_regional_settings()      # US-28: before the first render, so there is no flip
        self.window = MainWindow(self, self.args.windowed)
        self._wire_regional_settings()
        self.window.present()
        self._setup_recovery()
        self._setup_sync()
        self._setup_weather()
        log.info("calpi ready version=%s build=%s state_dir=%s renderer=%s",
                 __version__, _build_stamp(), paths.state_dir(),
                 os.environ.get("GSK_RENDERER"))
        if self.args.exit_after:
            GLib.timeout_add_seconds(self.args.exit_after, self._exit_for_test)

    def _apply_regional_settings(self) -> None:
        from calpi.data import formatting, timeutil
        from calpi.data.settings_store import K_TIMEZONE, K_TIME_FORMAT, K_WEEK_START
        timeutil.set_display_tz(self.settings.get(K_TIMEZONE))
        formatting.set_time_format(self.settings.get(K_TIME_FORMAT))
        self.week_start = self.settings.get(K_WEEK_START)
        log.debug("regional: tz=%s time_format=%s week_start=%s",
                  timeutil.display_tz().key, self.settings.get(K_TIME_FORMAT), self.week_start)

    def _wire_regional_settings(self) -> None:
        from calpi.data import formatting
        from calpi.data.settings_store import K_TIMEZONE, K_TIME_FORMAT, K_WEEK_START
        self.settings.subscribe(K_TIMEZONE, lambda _k, v: self._apply_tz(v))
        self.settings.subscribe(K_WEEK_START, lambda _k, v: (self.window.month_view.set_week_start(v),
                                                 self.window.week_view.set_week_start(v)))
        self.settings.subscribe(K_TIME_FORMAT, lambda _k, v: (
            formatting.set_time_format(v), self._refresh_views()))

    def _refresh_views(self) -> None:
        mv = self.window.month_view
        if hasattr(mv, "reload"):
            mv.reload(force=True)
        if hasattr(self.window, "on_data_changed"):
            self.window.on_data_changed()

    def _apply_tz(self, name) -> None:
        from calpi.data import timeutil
        from calpi.system import timezone as system_timezone
        timeutil.set_display_tz(name)
        if self.clock is not None:
            self.clock.notify_tz_changed()      # day change / grid / forced sync (US-10, US-16)
        else:
            self.window.month_view.refresh_today()
        self._refresh_views()
        if name and not os.environ.get("CALPI_NO_SYSTEM_TZ"):
            system_timezone.set_async(
                name, on_error=lambda e: log.warning("system tz not set: %s", e))

    def _setup_recovery(self) -> None:
        """US-12: banner, READY after first paint, watchdog pings from the main loop, stable timer."""
        mv = self.window.month_view
        if self.safe_mode:
            mv.header.end_slot.append(Gtk.Label(label="Safe mode", css_classes=["safe-mode-badge"]))
            self.window.overlay.add_overlay(Gtk.Label(
                label="calpi restarted several times and is running in safe mode. Your data is safe.",
                css_classes=["safe-mode-notice"], halign=Gtk.Align.CENTER, valign=Gtk.Align.END,
                can_target=False))
        if "db_reset" in self.startup_notices:
            log.error("calendar data was reset (integrity check failed); it will download again")
            mv.header.end_slot.append(Gtk.Label(label="Calendar data was reset and will download again",
                                                css_classes=["safe-mode-badge"]))
        log.info("watchdog: NOTIFY_SOCKET=%s interval=%s", os.environ.get("NOTIFY_SOCKET"),
                 watchdog.watchdog_interval_s())
        self._ready_sent = False

        @safe_callback(repeat=False)
        def _send_ready(*_a):
            if not self._ready_sent:
                self._ready_sent = True
                watchdog.ready()
                log.info("watchdog: READY sent")

        def _on_map(win):
            clock = win.get_frame_clock()
            if clock is None:
                GLib.idle_add(_send_ready)
                return
            hid = []
            def _painted(c):
                c.disconnect(hid[0])
                _send_ready()
            hid.append(clock.connect("after-paint", _painted))
            clock.request_phase(Gdk.FrameClockPhase.PAINT)          # make sure a frame is painted
        if self.window.get_mapped():
            _on_map(self.window)
        else:
            self.window.connect("map", _on_map)
        # Fallback so a missing frame clock/paint can never stall startup for the full 90 s.
        GLib.timeout_add_seconds(20, _send_ready)
        # Pings ONLY from the main loop (a thread would hide a frozen UI).
        GLib.timeout_add_seconds(watchdog.DEFAULT_PING_SECONDS,
                                 safe_callback(watchdog.ping, repeat=True))
        GLib.timeout_add_seconds(crashguard.STABLE_S, self._mark_stable)
        crashguard.test_crash_point("render", self.safe_mode)   # stand-in until MonthView.reload exists

    @safe_callback(repeat=False)
    def _mark_stable(self):
        crashguard.mark_stable()
        log.info("crashguard: stable, start counter cleared")

    def _setup_sync(self) -> None:
        """US-16: the engine (worker process launcher), the header indicator, the first schedule."""
        from calpi.sync_engine import SyncEngine
        from calpi.widgets.sync_indicator import SyncIndicator
        self.sync = SyncEngine(self)
        self._refresh_status()                                          # US-18: at startup
        self.sync.result_callbacks.append(self.reconcile_accounts)      # US-25 D5
        self.sync.result_callbacks.append(lambda _r: self._refresh_status())   # US-18
        indicator = SyncIndicator(self.sync, self.clock)
        self.window.month_view.header.end_slot.prepend(indicator)
        self._setup_network(indicator)
        self.sync.start()                                               # no-op in safe mode

    def _setup_network(self, indicator) -> None:
        """US-17: NetworkManager monitor + NTP trust; network-up triggers a sync and a weather refresh."""
        from calpi.system.networkmanager import NetworkMonitor
        from calpi.system.timesync import ClockTrust
        self.network = NetworkMonitor()
        self.clock_trust = ClockTrust()
        self.network.callbacks.append(self.sync.on_network_change)
        self.network.callbacks.append(self._on_network_change)
        indicator.bind_status(self.network, self.clock_trust)

    def _on_network_change(self, old, new) -> None:
        if new.name == "ONLINE" and old.name != "ONLINE" and self.weather is not None:
            self.weather.on_network_up()

    def _setup_weather(self) -> None:
        """US-41: forecast service (off by default), header panel, day-cell forecasts."""
        from calpi.weather.service import WeatherService
        from calpi.widgets.weather_panel import WeatherPanel
        self.weather = WeatherService(self)
        mv = self.window.month_view
        mv.header.end_slot.prepend(WeatherPanel(self.weather, self.clock))
        self.weather.callbacks.append(self._on_weather)
        self.weather.start()               # inactive in safe mode / when disabled

    def _on_weather(self, service) -> None:
        fc = service.forecast()
        self.window.month_view.set_forecast(fc.daily if fc is not None else None)

    def on_data_changed(self) -> None:
        """After a sync (or anything that changed stored data): reload what is showing."""
        if self.window is not None:
            self.window.on_data_changed()

    def _refresh_status(self) -> None:
        """US-18: re-read the persistent sync status and tell the subscribers."""
        from calpi.data import sync_status
        try:
            self.sync_status = sync_status.snapshot(self.store.conn)
        except Exception:
            log.exception("reading sync status failed")
            return
        for cb in list(self.status_callbacks):
            try:
                cb(self.sync_status)
            except Exception:
                log.exception("status callback failed")

    def account_status_text(self, account_id: str) -> str:
        """Short per-account line for the Accounts list (US-25). Full wording is US-38's."""
        from calpi.data import formatting, timeutil
        st = self.sync_status.account(account_id) if self.sync_status else None
        if st is None or st.last_attempt_at is None:
            return "Added"
        if st.last_error_code:
            return f"Sync problem ({st.last_error_code})"
        return "Synced " + formatting.relative_datetime(st.last_success_at, timeutil.now())

    def reconcile_accounts(self, *_a) -> None:
        """US-25 D5: drop calendars of accounts that are no longer configured. Cheap; safe to call
        after every sync result (register as a sync.result_callbacks subscriber)."""
        from calpi.data import accounts
        try:
            n = accounts.reconcile_calendars(self.settings, self.store)
        except Exception:
            log.exception("account reconciliation failed")
            return
        if n:
            log.info("reconciled %d orphaned calendar(s)", n)
            if self.window is not None and hasattr(self.window, "month_view"):
                self.window.month_view.reload(force=True)

    def on_calendars_changed(self) -> None:
        """After any calendar override change (US-26): regenerate colours, refresh every view."""
        if self.window is None or self.store is None:
            return
        self.calendar_colors.update(self.store.list_calendars(include_hidden=True))
        self.window.on_data_changed()

    def toast(self, text: str, seconds: float = 4) -> None:
        """Show a short bottom-centre message (US-22)."""
        if self.window is not None:
            self.window.toast_widget.show_text(text, seconds)

    def _maybe_load_sample_data(self):
        if not (self.args.sample_data or os.environ.get("CALPI_SAMPLE_DATA") == "1"):
            return
        from calpi.data import sample_data, timeutil
        from calpi.data.event_store import EventStore
        store = EventStore()
        try:
            if not store.list_calendars():       # only into an empty store
                tz = timeutil.display_tz()
                n = sample_data.load(store, timeutil.today(), tz)
                log.info("loaded %d sample events", n)
        finally:
            store.close()

    @safe_callback(repeat=False)
    def _exit_for_test(self):
        log.info("exit-after: screen=%s", self.window.navigator.current)
        self.quit()


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="calpi")
    p.add_argument("--windowed", action="store_true", help="don't go fullscreen (dev)")
    p.add_argument("--state-dir", help="override the state directory (dev/tests)")
    p.add_argument("--exit-after", type=int, default=0, metavar="SECONDS",
                   help="log state and quit after N seconds (smoke tests)")
    p.add_argument("--sample-data", action="store_true",
                   help="load sample calendars/events if the store is empty (dev; or CALPI_SAMPLE_DATA=1)")
    return p.parse_args(argv)


def _install_excepthooks() -> None:
    crit = logging.getLogger("calpi")

    def _hook(exc_type, exc, tb):
        crit.critical("uncaught exception", exc_info=(exc_type, exc, tb))
    sys.excepthook = _hook

    def _thread_hook(args):
        crit.critical("uncaught exception in thread %s", args.thread.name if args.thread else "?",
                      exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = _thread_hook


def main(argv=None) -> int:
    from calpi.logging_setup import setup_logging
    setup_logging()
    from calpi.data.credentials import install_log_redaction
    install_log_redaction()
    args = parse_args(argv)
    paths.set_state_dir_override(args.state_dir)
    _install_excepthooks()
    app = CalpiApp(args)

    def _on_term():
        log.info("calpi stopping (SIGTERM)")
        watchdog.stopping()
        app.quit()
        return GLib.SOURCE_REMOVE
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, _on_term)
    return app.run([])       # don't pass our argv to GTK
