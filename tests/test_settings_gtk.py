import os
import subprocess
import tempfile
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = textwrap.dedent('''
    import sys, resource
    sys.path.insert(0, ".")
    from gi.repository import GLib, Gtk
    from calpi import app as appmod
    from calpi.logging_setup import setup_logging; setup_logging()
    a = appmod.CalpiApp(appmod.parse_args(["--windowed", "--state-dir", sys.argv[1]]))
    def count(w):
        n, c = 1, w.get_first_child()
        while c:
            n += count(c); c = c.get_next_sibling()
        return n
    def run():
        w = a.window; nav = w.navigator
        nav.show("settings")
        assert nav.current == "settings"
        st = nav.get("settings")
        if "devrows" in st._sections or True:
            pass
        before = None
        for i in range(100):
            nav.show("settings"); nav.reset("calendar")
            if i == 1: before = count(w)
        after = count(w)
        assert after == before, (before, after)
        # escape from settings returns to calendar
        nav.show("settings")
        st.on_key("Escape", None)
        assert nav.current == "calendar", nav.current
        # toast + confirm
        a.toast("hi"); assert w.toast_widget.get_visible()
        w.confirm.ask("t", "b", "OK", lambda: None); assert w.confirm.is_open
        w.confirm.cancel_dialog(); assert not w.confirm.is_open
        print("OK", flush=True)
        a.quit()
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(500, run))
    a.run([])
''')


def _run(env_extra):
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6", **env_extra)
    subprocess.run("pgrep -f 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    with tempfile.TemporaryDirectory() as d:
        return subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", SCRIPT, d], env=env,
                              capture_output=True, text=True, cwd=ROOT)


@pytest.mark.gtk
def test_settings_open_close_no_growth():
    r = _run({})
    assert "OK" in r.stdout, r.stdout + r.stderr
    assert "section about shown" in r.stdout + r.stderr


@pytest.mark.gtk
def test_bad_section_placeholder_does_not_crash():
    r = _run({"CALPI_TEST_BAD_SECTION": "1"})
    assert "OK" in r.stdout, r.stdout + r.stderr
    assert "failed to build" in r.stdout + r.stderr
