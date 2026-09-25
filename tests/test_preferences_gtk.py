import json
import os
import subprocess
import tempfile
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = textwrap.dedent('''
    import sys
    sys.path.insert(0, ".")
    from gi.repository import GLib
    from calpi import app as appmod
    from calpi.data import formatting, timeutil
    from calpi.data.settings_store import K_TIMEZONE, K_WEEK_START, K_TIME_FORMAT
    from calpi.logging_setup import setup_logging; setup_logging()
    a = appmod.CalpiApp(appmod.parse_args(["--windowed"]))
    def run():
        w = a.window; mv = w.month_view
        assert a.week_start == 6 and formatting.time_format() == "12h"
        assert timeutil.display_tz().key == "UTC"
        assert (mv.year, mv.month) == (2026, 9), (mv.year, mv.month)
        w.navigator.show("settings")
        st = w.navigator.get("settings")
        st.select("preferences")
        panel = st._sections["preferences"].widget
        panel._pick("Europe/Paris", 0)          # what tapping a city does
        assert timeutil.display_tz().key == "Europe/Paris"
        assert (mv.year, mv.month) == (2026, 10), (mv.year, mv.month)
        a.settings.set(K_WEEK_START, 0)
        a.settings.set(K_TIME_FORMAT, "24h")
        assert formatting.time_format() == "24h"
        print("OK", flush=True)
        a.quit()
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(500, run))
    a.run([])
''')


@pytest.mark.gtk
def test_regional_settings_end_to_end():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":28",
               CALPI_FAKE_NOW="2026-09-30T23:30:00+00:00", CALPI_NO_SYSTEM_TZ="1", CALPI_TZ="UTC")
    subprocess.run("pgrep -f 'gtk4-broadwayd :28' >/dev/null || (setsid nohup gtk4-broadwayd :28 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "settings.json"), "w") as f:
            json.dump({"schema_version": 1, "timezone": "UTC", "week_start": 6, "time_format": "12h"}, f)
        env.update(CALPI_STATE_DIR=d, RUNTIME_DIRECTORY=d)
        r = subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", SCRIPT, d], env=env,
                           capture_output=True, text=True, cwd=ROOT)
    assert "OK" in r.stdout, r.stdout + r.stderr
