import os
import subprocess
import textwrap

import pytest

SCRIPT = textwrap.dedent('''
    import sys, tempfile
    sys.path.insert(0, ".")
    from datetime import date
    from gi.repository import Gtk
    from calpi.data import sample_data, timeutil, settings_store
    from calpi.data.event_store import EventStore
    from calpi.widgets.calendar_colors import CalendarColors
    from calpi.widgets.week_view import WeekView
    from calpi.widgets import view_switcher

    assert [v.name for v in view_switcher.VIEW_DEFS] == list(settings_store.VIEWS)
    store = EventStore(tempfile.mkdtemp() + "/e.db")
    sample_data.load(store, date(2026, 9, 15), timeutil.display_tz())
    wv = WeekView()
    wv.attach_store(store, CalendarColors())
    assert wv.first_day == date(2026, 9, 14), wv.first_day
    assert wv.header.title.get_text() == "14 \\u2013 20 September 2026"
    assert wv.day_labels[1].has_css_class("today")
    wv.set_size_request(1920, 1000)
    win = Gtk.Window(); win.set_default_size(1920, 1080); win.set_child(wv); win.present()
    ctx = __import__("gi").repository.GLib.MainContext.default()
    for _ in range(200):
        ctx.iteration(False)
    assert wv._layout is not None, "no layout after resize"
    n = len(wv._layout.blocks)
    assert n >= 8, n
    assert wv._layout.earlier[5] == 1
    wv.go_relative(1, "test"); wv.go_relative(-1, "test")
    assert wv.first_day == date(2026, 9, 14)
    wv.go_relative(2, "test"); wv.go_today("test")
    assert wv.is_current_week() and not wv.btn_today.get_sensitive()
    def count(w):
        k, c = 1, w.get_first_child()
        while c:
            k += count(c); c = c.get_next_sibling()
        return k
    before = count(wv)
    for i in range(6):
        wv.go_relative(1, "t"); wv.go_relative(-1, "t")
        for _ in range(20): ctx.iteration(False)
    assert count(wv) == before, (count(wv), before)
    assert wv.anchor_date() == date(2026, 9, 15)
    wv.show_date(date(2026, 10, 1)); assert wv.first_day == date(2026, 9, 28)
    wv.set_week_start(6); assert wv.first_day == date(2026, 9, 27)
    print("OK")
''')


@pytest.mark.gtk
def test_week_view():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6",
               CALPI_FAKE_NOW="2026-09-15T10:00:00", CALPI_TZ="UTC")
    subprocess.run("pgrep -f 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    r = subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", SCRIPT], env=env,
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "OK" in r.stdout, r.stdout + r.stderr
