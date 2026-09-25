from __future__ import annotations

import argparse
import logging
import os

from gi.repository import GLib, Gtk

from calpi import __version__, paths
from calpi.input import (CursorManager, KeyRouter, WindowEventHub, check_targets_enabled,
                         install_target_checker)
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
        self.navigator.show("calendar")
        if windowed:
            self.set_default_size(1920, 1080)
            self._install_dev_shortcuts()
        else:
            self.fullscreen()

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
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app):
        if self.window is not None:          # activate can fire twice; keep one window
            self.window.present()
            return
        from calpi.data.settings_store import SettingsStore
        self.settings = SettingsStore()
        log.info("settings loaded from %s", self.settings.path)
        Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
        provider = Gtk.CssProvider()
        provider.load_from_path(str(paths.app_dir() / "style.css"))
        add_style_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = MainWindow(self, self.args.windowed)
        self.window.present()
        log.info("calpi ready version=%s build=%s state_dir=%s renderer=%s",
                 __version__, _build_stamp(), paths.state_dir(),
                 os.environ.get("GSK_RENDERER"))
        if self.args.exit_after:
            GLib.timeout_add_seconds(self.args.exit_after, self._exit_for_test)

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
    return p.parse_args(argv)


def main(argv=None) -> int:
    from calpi.logging_setup import setup_logging
    setup_logging()
    args = parse_args(argv)
    paths.set_state_dir_override(args.state_dir)
    app = CalpiApp(args)
    return app.run([])       # don't pass our argv to GTK
