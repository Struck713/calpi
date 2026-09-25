"""Horizontal swipe helper (US-35). No animation: the callback fires once when the swipe ends."""
from __future__ import annotations

import logging
import os
import time
from typing import Callable

from gi.repository import Gtk

from calpi.data.gestures import classify_swipe, should_claim

log = logging.getLogger("calpi.swipe")


def attach_horizontal_swipe(widget: Gtk.Widget, on_swipe: Callable[[int], None],
                            touch_only: bool = True) -> Gtk.GestureDrag:
    """Call on_swipe(+1) for a leftward swipe (next) and on_swipe(-1) for rightward (previous).

    Capture phase on an ancestor of the tappable children; claims the sequence only once the
    movement is clearly horizontal, which cancels child click gestures. Taps are untouched.
    """
    g = Gtk.GestureDrag()
    g.set_touch_only(touch_only and os.environ.get("CALPI_SWIPE_MOUSE") != "1")
    g.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    st = {"t0": 0.0, "claimed": False}

    def begin(_g, _x, _y):
        st["t0"] = time.monotonic()
        st["claimed"] = False

    def update(gest, dx, dy):
        try:
            if not st["claimed"] and should_claim(dx, dy):
                gest.set_state(Gtk.EventSequenceState.CLAIMED)
                st["claimed"] = True
        except Exception:
            log.exception("swipe update failed")

    def end(_g, dx, dy):
        try:
            if not st["claimed"]:
                return
            st["claimed"] = False
            d = classify_swipe(dx, dy, time.monotonic() - st["t0"])
            log.debug("swipe end dx=%.0f dy=%.0f -> %d", dx, dy, d)
            if d:
                on_swipe(d)
        except Exception:
            log.exception("swipe end failed")

    g.connect("drag-begin", begin)
    g.connect("drag-update", update)
    g.connect("drag-end", end)
    widget.add_controller(g)
    widget._swipe = g  # keep a reference
    return g
