"""Dev-only touchscreen accuracy test screen (CALPI_DEV_TOUCHTEST=1, US-34).

9 targets (corners, edge midpoints, centre); each touch draws a cross, and the offset to the
nearest target, the device name and source are shown and logged at INFO.
Redraws only when something changes.
"""
from __future__ import annotations

import logging

from gi.repository import Gtk

from calpi.system import touchcal

log = logging.getLogger("calpi.touchtest")


class DevTouchTest(Gtk.Overlay):
    def __init__(self, window=None):
        super().__init__(css_classes=["screen"])
        self.touches: list[tuple[float, float, float, float, float]] = []   # x, y, dx, dy, dist
        self.last_device = ("?", "?")
        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.area.set_draw_func(self._draw)
        self.set_child(self.area)
        legacy = Gtk.EventControllerLegacy()
        legacy.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        legacy.connect("event", self._on_legacy)
        self.area.add_controller(legacy)
        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self._on_pressed)
        self.area.add_controller(click)
        clear = Gtk.Button(label="Clear", halign=Gtk.Align.START, valign=Gtk.Align.START,
                           margin_start=300, margin_top=200)
        clear.set_size_request(240, 96)
        clear.connect("clicked", lambda *_: self.clear())
        self.add_overlay(clear)

    # screen protocol used by the navigator (optional hooks)
    def on_show(self, **_p) -> None:
        self.area.queue_draw()

    def clear(self) -> None:
        self.touches.clear()
        self.area.queue_draw()

    def _targets(self):
        return touchcal.targets(self.area.get_width(), self.area.get_height())

    def _on_legacy(self, _ctl, event) -> bool:
        from gi.repository import Gdk
        if event is not None and event.get_event_type() in (
                Gdk.EventType.TOUCH_BEGIN, Gdk.EventType.BUTTON_PRESS):
            dev = event.get_device()
            if dev is not None:
                self.last_device = (dev.get_name(), dev.get_source().value_nick)
            log.debug("touchtest: %s device=%s source=%s", event.get_event_type().value_nick,
                      *self.last_device)
        return False

    def _on_pressed(self, _g, _n, x, y) -> None:
        dx, dy, dist = touchcal.offset((x, y), self._targets())
        self.touches.append((x, y, dx, dy, dist))
        log.info("touchtest: x=%.0f y=%.0f dx=%+.0f dy=%+.0f dist=%.0f device=%r source=%s",
                 x, y, dx, dy, dist, *self.last_device)
        self.area.queue_draw()

    def summary(self) -> dict:
        return touchcal.summarize(t[4] for t in self.touches)

    def _draw(self, _area, cr, w, h) -> None:
        cr.set_source_rgb(0.08, 0.08, 0.1)
        cr.paint()
        cr.set_line_width(2)
        for tx, ty in touchcal.targets(w, h):
            cr.set_source_rgb(0.3, 0.6, 1)
            cr.arc(tx, ty, 40, 0, 6.2832)
            cr.stroke()
            cr.arc(tx, ty, 2, 0, 6.2832)
            cr.fill()
        for x, y, _dx, _dy, dist in self.touches:
            ok = dist <= touchcal.TOLERANCE_PX
            cr.set_source_rgb(*((0.3, 1, 0.4) if ok else (1, 0.3, 0.3)))
            cr.move_to(x - 12, y); cr.line_to(x + 12, y)
            cr.move_to(x, y - 12); cr.line_to(x, y + 12)
            cr.stroke()
        s = self.summary()
        lines = [f"device: {self.last_device[0]} ({self.last_device[1]})",
                 f"touches: {s['n']}  max {s['max']:.0f}px  mean {s['mean']:.1f}px  "
                 f"{'PASS' if s['ok'] else 'not passing'} (limit {touchcal.TOLERANCE_PX:.0f}px)"]
        for x, y, dx, dy, dist in self.touches[-6:]:
            lines.append(f"({x:.0f},{y:.0f})  dx {dx:+.0f}  dy {dy:+.0f}  d {dist:.0f}")
        cr.set_source_rgb(0.9, 0.9, 0.9)
        cr.set_font_size(22)
        for i, line in enumerate(lines):
            cr.move_to(w / 2 - 300, h / 2 - 120 + i * 30)
            cr.show_text(line)
