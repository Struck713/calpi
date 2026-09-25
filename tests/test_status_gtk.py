import os
import subprocess
import tempfile
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = textwrap.dedent('''
    import sys
    sys.path.insert(0, ".")
    from datetime import datetime, timezone
    from gi.repository import GLib
    from calpi import app as appmod
    from calpi.data import sync_status as ss
    from calpi.system import device_info as di
    from calpi.logging_setup import setup_logging; setup_logging()
    a = appmod.CalpiApp(appmod.parse_args(["--windowed"]))
    def count(w):
        n, c = 0, w.get_first_child()
        while c is not None:
            n += 1 + count(c); c = c.get_next_sibling()
        return n
    def run():
        w = a.window
        w.navigator.show("settings", section="status")
        st = w.navigator.get("settings")
        sec = st._sections["status"]
        assert st._selected == "status"
        sec._device = di.DeviceInfo(di.decode_throttled(0), True, 45.0, 10 * 1024**3)
        sec._render()
        assert sec.last_verdict.level == "warn" and "No calendar account" in sec.last_verdict.text, sec.last_verdict
        # with an account that fails auth
        from calpi.data import accounts
        class Acc: id="a1"; display_name="me@icloud.com"; username="me"; provider="icloud"
        accounts.list_accounts = lambda s: [Acc()]
        now = datetime.now(timezone.utc)
        a.sync_status = ss.StatusSnapshot(
            (ss.AccountStatus("a1", now, None, "AUTH_FAILED", "x", now, 2),), (), ())
        a.startup_notices = []
        a.network.state = type(a.network.state).ONLINE
        sec._render()
        assert sec.last_verdict.level == "bad" and sec.last_verdict.fix_section == "accounts", sec.last_verdict
        assert sec.verdict_fix.get_visible() and sec.verdict.has_css_class("verdict-bad")
        # ok state
        a.sync_status = ss.StatusSnapshot((ss.AccountStatus("a1", now, now, None, None, None, 0),), (), ())
        sec._render()
        assert sec.last_verdict.level in ("ok", "warn"), sec.last_verdict
        # no rebuild when nothing changed
        before = count(sec.widget)
        first = sec.accounts_box.get_first_child()
        sec._render(); sec._render()
        assert count(sec.widget) == before and sec.accounts_box.get_first_child() is first
        # undervoltage -> red power verdict
        sec._device = di.DeviceInfo(di.decode_throttled("0x50005"), True, 45.0, 10 * 1024**3)
        sec._render()
        assert sec.last_verdict.level == "bad" and "power supply" in sec.last_verdict.text
        # nothing subscribed while hidden
        assert sec._subs and sec._timer
        w.navigator.show("calendar")
        assert not sec._subs and not sec._timer
        assert sec._on_event not in a.status_callbacks
        # header tap target
        w.navigator.show("calendar")
        c, ind = w.month_view.header.end_slot.get_first_child(), None
        while c is not None:
            if "sync-status" in c.get_css_classes():
                ind = c
            c = c.get_next_sibling()
        assert ind is not None
        from gi.repository import Gtk
        ctl = ind.observe_controllers()
        assert any(isinstance(ctl.get_item(i), Gtk.GestureClick) for i in range(ctl.get_n_items()))
        print("OK", flush=True)
        a.quit()
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(500, run))
    a.run([])
''')


@pytest.mark.gtk
def test_status_section():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":33", CALPI_FAKE_WIFI="1",
               CALPI_NO_SYSTEM_TZ="1")
    subprocess.run("pgrep -f '[g]tk4-broadwayd :33' >/dev/null || (setsid nohup gtk4-broadwayd :33 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    with tempfile.TemporaryDirectory() as d:
        env.update(CALPI_STATE_DIR=d, RUNTIME_DIRECTORY=d)
        r = subprocess.run(["timeout", "60", "/usr/bin/python3", "-c", SCRIPT], env=env,
                           capture_output=True, text=True, cwd=ROOT)
    assert "OK" in r.stdout, r.stdout + r.stderr[-3000:]
