import os
import subprocess
import sys
import textwrap

import pytest

SCRIPT = textwrap.dedent('''
    import sys
    sys.path.insert(0, ".")
    from gi.repository import Gtk
    from calpi.widgets.month_view import MonthView
    def count(w):
        n, c = 1, w.get_first_child()
        while c:
            n += count(c); c = c.get_next_sibling()
        return n
    mv = MonthView()
    before = count(mv)
    y, m = 2026, 1
    for _ in range(12):
        m += 1
        if m > 12: y, m = y + 1, 1
        mv.show_month(y, m)
    mv.set_week_start(6)
    assert count(mv) == before, (count(mv), before)
    assert mv.weekday_labels[0].get_text() == "SUN"
    # today marking: 2026-09-15 fake clock
    mv.set_week_start(0); mv.show_month(2026, 9)
    marked = [c.date for r in mv.week_rows for c in r.cells if c.has_css_class("today")]
    assert marked == [__import__("datetime").date(2026, 9, 15)], marked
    mv.show_month(2026, 10)   # Sep 15 not in Oct grid
    assert not [1 for r in mv.week_rows for c in r.cells if c.has_css_class("today")]
    print("OK")
''')


@pytest.mark.gtk
def test_month_view_no_new_widgets():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6",
               CALPI_FAKE_NOW="2026-09-15T10:00:00", CALPI_TZ="UTC")
    subprocess.run("pgrep -fx 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    r = subprocess.run(["timeout", "30", "/usr/bin/python3", "-c", SCRIPT], env=env,
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "OK" in r.stdout, r.stdout + r.stderr
