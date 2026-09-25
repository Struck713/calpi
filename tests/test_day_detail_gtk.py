import os
import subprocess
import textwrap

import pytest

SCRIPT = textwrap.dedent('''
    import sys, tempfile
    sys.path.insert(0, ".")
    from datetime import date
    from gi.repository import Gtk
    from calpi.app import Navigator
    from calpi.data import sample_data, timeutil
    from calpi.data.event_store import EventStore
    from calpi.widgets.month_view import MonthView
    from calpi.widgets.day_detail import DayDetail
    def count(w):
        n, c = 1, w.get_first_child()
        while c:
            n += count(c); c = c.get_next_sibling()
        return n
    store = EventStore(tempfile.mkdtemp() + "/t.sqlite3")
    sample_data.load(store, timeutil.today(), timeutil.display_tz())
    stack = Gtk.Stack(); nav = Navigator(stack)
    mv = MonthView(); mv.attach_store(store)
    nav.add("calendar", mv)
    dd = DayDetail(store, mv.colors, nav, mv); nav.add("day", dd)
    win = Gtk.Window(); win.set_child(stack)
    nav.show("calendar")
    cells = [c for r in mv.week_rows for c in r.cells]
    cells[10].activate_callback(cells[10].date)
    assert nav.current == "day" and dd.date == cells[10].date
    before = count(win)
    for _ in range(200):
        nav.show("day", date=cells[10].date); nav.back()
    nav.show("day", date=cells[10].date)
    assert count(win) == before, (count(win), before)
    # rows for busy day
    best = max(range(-40, 40), key=lambda i: len(store.events_for_days(timeutil.today().fromordinal(timeutil.today().toordinal() + i), timeutil.today().fromordinal(timeutil.today().toordinal() + i + 1), timeutil.display_tz())))
    d = timeutil.today().fromordinal(timeutil.today().toordinal() + best)
    nav.show("day", date=d)
    n = 0; c = dd.list.get_first_child()
    while c: n += 1; c = c.get_next_sibling()
    assert n >= 1 and dd.scroller.get_visible() and not dd.empty.get_visible()
    # month boundary follows; keys; back
    dd.date = date(2026, 9, 30); mv.show_month(2026, 9); dd.shift(1)
    assert (mv.year, mv.month) == (2026, 10), (mv.year, mv.month)
    assert dd.on_key("Left", 0) and dd.date == date(2026, 9, 30) and (mv.year, mv.month) == (2026, 9)
    assert not dd.on_key("x", 0)
    nav.back(); assert nav.current == "calendar"
    print("OK")
''')


@pytest.mark.gtk
def test_day_detail():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6",
               CALPI_FAKE_NOW="2026-09-15T10:00:00", CALPI_TZ="UTC")
    subprocess.run("pgrep -f 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    r = subprocess.run(["timeout", "60", "/usr/bin/python3", "-c", SCRIPT], env=env,
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "OK" in r.stdout, r.stdout + r.stderr
