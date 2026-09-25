import os
import subprocess
import textwrap

import pytest

SCRIPT = textwrap.dedent('''
    import sys, tempfile
    sys.path.insert(0, ".")
    from datetime import date
    from gi.repository import Gtk, GLib
    from calpi.data import sample_data, timeutil
    from calpi.data.event_store import EventStore
    from calpi.widgets.calendar_colors import CalendarColors
    from calpi.widgets.agenda_view import AgendaView

    store = EventStore(tempfile.mkdtemp() + "/e.db")
    av = AgendaView()
    av.attach_store(store, CalendarColors())
    assert av.empty.get_visible() and not av.scroller.get_visible()
    sample_data.load(store, date(2026, 9, 15), timeutil.display_tz())
    av.reload()
    assert av.scroller.get_visible() and not av.empty.get_visible()
    assert av._row_days, "no item rows"
    win = Gtk.Window(); win.set_default_size(1920, 1080); win.set_child(av); win.present()
    ctx = GLib.MainContext.default()
    for _ in range(100): ctx.iteration(False)
    shown = av._shown
    av.reload(); av.reload(force=True)
    assert av._shown is shown, "rebuilt without change"
    def count(w):
        k, c = 1, w.get_first_child()
        while c:
            k += count(c); c = c.get_next_sibling()
        return k
    n = count(av)
    for _ in range(5): av.refresh_today()
    assert count(av) == n
    assert av.anchor_date() == date(2026, 9, 15)
    assert av.on_key("Escape", None) is True
    av.go_today("test")
    assert av.scroller.get_vadjustment().get_value() == 0
    print("OK")
''')


@pytest.mark.gtk
def test_agenda_view():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6",
               CALPI_FAKE_NOW="2026-09-15T10:00:00", CALPI_TZ="UTC")
    subprocess.run("pgrep -fx 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    r = subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", SCRIPT], env=env,
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "OK" in r.stdout, r.stdout + r.stderr
