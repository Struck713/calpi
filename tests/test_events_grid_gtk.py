import os
import subprocess
import textwrap

import pytest

SCRIPT = textwrap.dedent('''
    import sys, tempfile
    sys.path.insert(0, ".")
    from datetime import date
    from gi.repository import Gtk
    from calpi.data import sample_data, timeutil
    from calpi.data.event_store import EventStore
    from calpi.widgets.month_view import MonthView

    store = EventStore(tempfile.mkdtemp() + "/e.db")
    sample_data.load(store, date(2026, 9, 15), timeutil.display_tz())
    def count(w):
        n, c = 1, w.get_first_child()
        while c:
            n += count(c); c = c.get_next_sibling()
        return n
    def texts(mv, css):
        out = []
        for r in mv.week_rows:
            c = r.content.get_first_child()
            while c:
                if c.has_css_class(css):
                    out.append(c)
                c = c.get_next_sibling()
        return out
    mv = MonthView()
    mv.attach_store(store)
    mv.show_month(2026, 9)
    bars = texts(mv, "bar"); mores = texts(mv, "more")
    assert any(b.get_text() == "School trip" for b in bars), [b.get_text() for b in bars]
    assert any(m.get_text().startswith("+") for m in mores)
    assert not any("Archived" in b.get_text() for b in bars)
    n_sep = count(mv)
    mv.reload()                          # unchanged: no widget changes
    assert count(mv) == n_sep
    for y, m in [(2026, 10), (2026, 8), (2026, 9), (2026, 10), (2026, 9)]:
        mv.show_month(y, m)
    assert count(mv) == n_sep, (count(mv), n_sep)
    print("OK")
''')


@pytest.mark.gtk
def test_events_render():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6",
               CALPI_FAKE_NOW="2026-09-15T10:00:00", CALPI_TZ="UTC")
    subprocess.run("pgrep -f 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    r = subprocess.run(["timeout", "30", "/usr/bin/python3", "-c", SCRIPT], env=env,
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "OK" in r.stdout, r.stdout + r.stderr
