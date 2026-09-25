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
        w.navigator.show("settings", section="display")
        sec = w.navigator.get("settings")._sections["display"]
        a.brightness.set_override(10)
        def later():
            assert a.brightness.backend_name in ("software", "backlight", "ddc")
            if a.brightness.backend_name == "software":
                assert w.dim_layer.get_visible() and abs(w.dim_layer.get_opacity() - 0.75) < 0.01
            assert sec.note.get_label()
            sec.presets.buttons[50].emit("clicked")
            assert a.settings.get("brightness") == 50
            a.brightness.set_override(None)
            print("DISPLAY OK", flush=True)
            a.quit()
            return False
        GLib.timeout_add(2500, later)
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(500, run))
    a.run([])
''')


@pytest.mark.gtk
def test_display_section_and_dim_layer():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6")
    subprocess.run("pgrep -fx 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", SCRIPT, d], env=env,
                           capture_output=True, text=True, cwd=ROOT)
    assert "DISPLAY OK" in r.stdout, r.stdout + r.stderr
