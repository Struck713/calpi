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
    a = appmod.CalpiApp(appmod.parse_args(["--windowed", "--sample-data", "--state-dir", sys.argv[1]]))
    def run():
        w = a.window
        w.navigator.show("settings", section="calendars")
        sec = w.navigator.get("settings")._sections["calendars"]
        cals = a.store.list_calendars()
        assert sec.widget.get_first_child() is not None
        fam = next(c for c in cals if c.id == "sample:Family")
        before = w.month_view.colors.css_class(fam.id)
        sec._open(fam.id)
        page = sec._page
        page.entry.set_text("  Household  ")
        page.save_name()
        assert a.store.get_calendar(fam.id).user_name == "Household"
        page.swatches[1].emit("clicked")                 # green
        assert a.store.get_calendar(fam.id).color == "#3ecf8e"
        assert page.reset_row.button.get_sensitive()
        page.reset()
        c = a.store.get_calendar(fam.id)
        assert (c.user_name, c.user_color) == (None, None)
        assert not page.reset_row.button.get_sensitive()
        page.entry.set_text("   ")
        page.save_name()
        assert a.store.get_calendar(fam.id).user_name is None
        rev = a.store.revision()
        page.visible_row.switch.set_active(False)
        assert a.store.get_calendar(fam.id).hidden and a.store.revision() > rev
        page.visible_row.switch.set_active(True)
        assert not a.store.get_calendar(fam.id).hidden
        print("CALENDARS OK", flush=True)
        a.quit()
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(800, run))
    a.run([])
''')


@pytest.mark.gtk
def test_calendars_section_flow():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6")
    subprocess.run("pgrep -fx 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", SCRIPT, d], env=env,
                           capture_output=True, text=True, cwd=ROOT)
    assert "CALENDARS OK" in r.stdout, r.stdout + r.stderr
