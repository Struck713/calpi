#!/usr/bin/env python3
"""Minimal reference kiosk app: fullscreen GTK 4, hidden cursor, CSS,
minute-aligned clock, background fetch marshalled back to the UI thread."""
import os

# Pi 3B GPU is GLES 2.0 only; force GTK's software renderer. Must precede Gtk import.
os.environ.setdefault("GSK_RENDERER", "cairo")

import argparse
import datetime as dt
import logging
import threading
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

log = logging.getLogger("calpi")

CSS = b"""
window { background-color: #101418; color: #e8e8e8; }
.clock { font-family: "DejaVu Sans"; font-size: 160px; font-weight: 300; }
.date  { font-size: 48px; color: #9aa4ae; }
.status { font-size: 20px; color: #5c6670; }
"""

REFRESH_SECONDS = 15 * 60
FETCH_URL = "https://example.com/"


class KioskWindow(Gtk.ApplicationWindow):
    def __init__(self, app, windowed: bool):
        super().__init__(application=app, title="calpi")
        self.set_cursor(Gdk.Cursor.new_from_name("none", None))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, spacing=12)
        self.clock = Gtk.Label(css_classes=["clock"])
        self.date = Gtk.Label(css_classes=["date"])
        self.status = Gtk.Label(css_classes=["status"])
        for w in (self.clock, self.date, self.status):
            box.append(w)
        self.set_child(box)

        if windowed:
            self.set_default_size(1920 // 2, 1080 // 2)
        else:
            self.fullscreen()

        self._tick()
        self._schedule_next_minute()
        self._start_fetch()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._on_refresh_timer)

    # --- clock ---------------------------------------------------------
    def _schedule_next_minute(self):
        now = dt.datetime.now()
        delay_ms = (60 - now.second) * 1000 - now.microsecond // 1000 + 50
        GLib.timeout_add(delay_ms, self._on_minute)

    def _on_minute(self):
        try:
            self._tick()
        except Exception:
            log.exception("clock tick failed")
        self._schedule_next_minute()  # recompute each time: survives NTP jumps
        return GLib.SOURCE_REMOVE

    def _tick(self):
        now = dt.datetime.now()
        set_text_if_changed(self.clock, now.strftime("%H:%M"))
        set_text_if_changed(self.date, now.strftime("%A, %B %-d"))

    # --- background data -------------------------------------------------
    def _on_refresh_timer(self):
        self._start_fetch()
        return GLib.SOURCE_CONTINUE

    def _start_fetch(self):
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        # Runs off the main thread: NO widget access here.
        try:
            with urllib.request.urlopen(FETCH_URL, timeout=10) as r:
                result = ("ok", len(r.read()))
        except Exception as e:  # keep last good data on failure
            result = ("error", str(e))
        GLib.idle_add(self._apply_fetch, result)

    def _apply_fetch(self, result):
        # Back on the main thread.
        try:
            kind, value = result
            stamp = dt.datetime.now().strftime("%H:%M")
            if kind == "ok":
                set_text_if_changed(self.status, f"updated {stamp}")
            else:
                log.warning("fetch failed: %s", value)
                set_text_if_changed(self.status, f"offline — retrying (last try {stamp})")
        except Exception:
            log.exception("apply_fetch failed")
        return GLib.SOURCE_REMOVE


def set_text_if_changed(label: Gtk.Label, text: str):
    if label.get_text() != text:
        label.set_text(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windowed", action="store_true", help="don't go fullscreen (dev)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    app = Gtk.Application(application_id="dev.calpi.Kiosk")

    def on_activate(app):
        Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        KioskWindow(app, args.windowed).present()

    app.connect("activate", on_activate)
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
