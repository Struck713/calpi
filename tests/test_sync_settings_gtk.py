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
    from calpi.data.settings_store import K_SYNC_INTERVAL_MINUTES
    from calpi.logging_setup import setup_logging; setup_logging()
    a = appmod.CalpiApp(appmod.parse_args(["--windowed"]))
    toasts = []
    def run():
        w = a.window
        w.navigator.show("settings")
        st = w.navigator.get("settings")
        st.select("sync")
        sec = st._sections["sync"]
        assert sec._timer, "refresh timer should run while visible"
        assert sec.next_row.value.get_text() != "", "next update text"
        a.toast = lambda t, *_a, **_k: toasts.append(t)
        chooser = sec.chooser
        assert chooser.value.get_text() == "15 minutes", chooser.value.get_text()
        chooser._pick(30)
        assert a.settings.get(K_SYNC_INTERVAL_MINUTES) == 30
        assert chooser.value.get_text() == "30 minutes"
        assert toasts == ["Calendars will refresh every 30 minutes"], toasts
        calls = []
        a.trigger_manual_refresh = lambda: calls.append(1) or True
        sec.sync_now.button.emit("clicked")
        assert calls == [1], "Sync now row must call app.trigger_manual_refresh"
        w.navigator.back()
        assert not sec._timer, "timer must stop when hidden"
        print("OK", flush=True)
        a.quit()
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(800, run))
    a.run([])
''')


@pytest.mark.gtk
def test_sync_section_pick_interval():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":27")
    subprocess.run("pgrep -fx 'gtk4-broadwayd :27' >/dev/null || (setsid nohup gtk4-broadwayd :27 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    with tempfile.TemporaryDirectory() as d:
        env.update(CALPI_STATE_DIR=d, RUNTIME_DIRECTORY=d)
        r = subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", SCRIPT], env=env,
                           capture_output=True, text=True, cwd=ROOT)
    assert "OK" in r.stdout, r.stdout + r.stderr
