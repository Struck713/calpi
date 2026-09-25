import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CALPI_GTK_TESTS") != "1", reason="GTK tests off")


def test_swipe_attached():
    from gi.repository import Gtk
    from calpi.widgets.month_view import MonthView
    from calpi.widgets.swipe import attach_horizontal_swipe
    mv = MonthView()
    assert any(isinstance(c, Gtk.GestureDrag) for c in mv.weeks_box.observe_controllers())
    calls = []
    b = Gtk.Box()
    g = attach_horizontal_swipe(b, calls.append)
    assert g.get_propagation_phase() == Gtk.PropagationPhase.CAPTURE
    assert g.get_touch_only()
