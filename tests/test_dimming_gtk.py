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
    from calpi.logging_setup import setup_logging; setup_logging()
    a = appmod.CalpiApp(appmod.parse_args(["--windowed", "--state-dir", sys.argv[1]]))
    def run():
        w = a.window
        assert a.dimming.state == "DAY"
        cfg = dict(a.settings.get("dim_schedule"), enabled=True, start="00:00", end="23:30")
        a.settings.set("dim_schedule", cfg)
        assert a.dimming.state == "NIGHT" and w.wake_catcher.get_visible()
        assert a.brightness.override == 10
        assert w.overlay.get_last_child() is w.wake_catcher, "catcher must be topmost"
        w.navigator.show("settings", section="display")
        panel = w.navigator.get("settings")._sections["display"].widget.get_last_child()
        assert type(panel).__name__ == "DimSchedulePanel", type(panel)
        assert panel.start_row.value.get_label() == "00:00"
        w.wake_catcher.on_wake()
        assert a.dimming.state == "NIGHT_AWAKE" and a.brightness.override is None
        a.dimming._on_idle()
        assert a.dimming.state == "NIGHT"
        a.settings.set("dim_schedule", dict(cfg, enabled=False))
        assert a.dimming.state == "DAY" and not w.wake_catcher.get_visible()
        print("DIMMING OK", flush=True)
        a.quit()
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(800, run))
    a.run([])
''')


@pytest.mark.gtk
def test_dimming_controller_and_panel():
    d = tempfile.mkdtemp()
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6",
               CALPI_DIM_BOOT_DELAY_S="0", CALPI_STATE_DIR=d, CALPI_FAKE_NOW="2026-01-15T12:00:00")
    subprocess.run("pgrep -f 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    r = subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", SCRIPT, d], env=env,
                       capture_output=True, text=True, cwd=ROOT)
    assert "DIMMING OK" in r.stdout, r.stdout + r.stderr
