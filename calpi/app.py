from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading

from gi.repository import GLib, Gtk

from calpi import __version__, crashguard, paths, watchdog
from calpi.input import (CursorManager, KeyRouter, WindowEventHub, check_targets_enabled,
                         install_target_checker)
from calpi.inactivity import DEFAULT_RETURN_SECONDS, InactivityMonitor
from calpi.tasks import safe_callback
from calpi.widgets.month_view import MonthView
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
        if check_targets_enabled():
            install_target_checker(self.navigator)
        self.month_view = MonthView(week_start=0)
        self.navigator.add("calendar", self.month_view)
        app.clock.subscribe_day_changed(self._on_day_changed)
        self.navigator.show("calendar")
        self.inactivity = InactivityMonitor(self.hub)
        self._return_handle = self.inactivity.add_idle_callback(
            self._return_seconds(), self._on_idle_return)
        self._wire_return_setting(app)
        if windowed:
            self.set_default_size(1920, 1080)
            self._install_dev_shortcuts()
        else:
            self.fullscreen()

    def _on_day_changed(self, old, new):
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

    def _on_idle_return(self) -> None:
        if self.navigator.current in ("calendar", "day"):
            if self.navigator.current != "calendar":
                self.navigator.reset("calendar")
            self.month_view.go_today(reason="inactivity")

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
        self.credentials = None         # CredentialStore, created in _on_activate (US-13)
        self.safe_mode = False          # US-12: crash loop detected; extras/auto-sync must check it
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
        from calpi.clock import ClockService
        self.clock = ClockService()
        self.window = MainWindow(self, self.args.windowed)
        self.window.present()
        self._setup_recovery()
        log.info("calpi ready version=%s build=%s state_dir=%s renderer=%s",
                 __version__, _build_stamp(), paths.state_dir(),
                 os.environ.get("GSK_RENDERER"))
        if self.args.exit_after:
            GLib.timeout_add_seconds(self.args.exit_after, self._exit_for_test)

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
            clock.request_phase(0x20)          # make sure a frame is painted
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

    def _maybe_load_sample_data(self):
        if not (self.args.sample_data or os.environ.get("CALPI_SAMPLE_DATA") == "1"):
            return
        from calpi.data import sample_data
        from calpi.data.event_store import EventStore
        store = EventStore()
        try:
            if not store.list_calendars():       # only into an empty store
                tz = sample_data._system_tz()    # TODO(US-06): use timeutil.display_tz()
                n = sample_data.load(store, dt.datetime.now(tz).date(), tz)
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
