import os
import subprocess
import textwrap

import pytest

SCRIPT = textwrap.dedent('''
    import sys, json, tempfile
    sys.path.insert(0, ".")
    from datetime import date
    from types import SimpleNamespace
    from gi.repository import Gtk, GLib
    from calpi.data import settings_store as ss
    from calpi.widgets.month_view import MonthView
    from calpi.widgets.weather_panel import WeatherPanel
    from calpi.weather import client
    from calpi.widgets.settings.weather import PlaceSearchPage

    def count(w):
        n, c = 1, w.get_first_child()
        while c:
            n += count(c); c = c.get_next_sibling()
        return n

    raw = json.load(open("tests/fixtures/weather/forecast.json"))
    fc = client.parse_forecast(raw)
    mv = MonthView()
    mv.show_month(2026, 9)
    before = count(mv)
    svc = SimpleNamespace(callbacks=[], forecast=lambda: fc)
    panel = WeatherPanel(svc)
    assert panel.get_visible() and panel.get_text() == "\\u2601 15\\u00b0 \\u00b7 15\\u00b0/12\\u00b0", panel.get_text()
    svc.forecast = lambda: None
    svc.callbacks[0](svc)
    assert not panel.get_visible()
    mv.set_forecast(fc.daily)
    cells = {c.date: c for r in mv.week_rows for c in r.cells}
    assert cells[date(2026, 9, 25)].forecast.get_text() == "\\u2601 15\\u00b0/12\\u00b0"
    assert cells[date(2026, 9, 25)].forecast.get_visible()
    assert not cells[date(2026, 9, 24)].forecast.get_visible()
    assert cells[date(2026, 10, 1)].forecast.get_visible()
    assert not cells[date(2026, 10, 2)].forecast.get_visible()
    mv.show_month(2026, 10)                      # forecast follows the month
    cells = {c.date: c for r in mv.week_rows for c in r.cells}
    assert cells[date(2026, 10, 1)].forecast.get_visible() and not cells[date(2026, 10, 2)].forecast.get_visible()
    mv.set_forecast(None)
    assert not any(c.forecast.get_visible() for r in mv.week_rows for c in r.cells)
    assert count(mv) == before, (count(mv), before)

    geo = json.load(open("tests/fixtures/weather/geocoding.json"))
    picked = []
    page = PlaceSearchPage(picked.append, search=lambda q: client.parse_places(geo))
    page.entry.set_text("Springfield")
    page.run_search()
    ctx = GLib.MainContext.default()
    import time
    t = time.time()
    while page._results is None and time.time() - t < 5:
        ctx.iteration(False)
    assert page._results is not None
    row = page._results.listbox.get_row_at_index(0)
    page._results._on_activated(None, row)
    assert picked and picked[0].label == "Springfield, Missouri, United States"
    print("OK")
''')


@pytest.mark.gtk
def test_weather_widgets():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":41",
               CALPI_FAKE_NOW="2026-09-25T10:00:00", CALPI_TZ="UTC")
    subprocess.run("pgrep -f '^[g]tk4-broadwayd :41' >/dev/null || (setsid nohup gtk4-broadwayd :41 >/dev/null 2>&1 </dev/null & sleep 2)",
                   shell=True)
    r = subprocess.run(["timeout", "30", "/usr/bin/python3", "-c", SCRIPT], env=env,
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "OK" in r.stdout, r.stdout + r.stderr
