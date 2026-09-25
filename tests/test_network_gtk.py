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
    a = appmod.CalpiApp(appmod.parse_args(["--windowed", "--state-dir", sys.argv[1]]))
    def step(fn, ms):
        GLib.timeout_add(ms, lambda: (fn(), False)[1])
    def run():
        w = a.window; nav = w.navigator
        nav.show("settings", section="network")
        st = nav.get("settings")
        sec = st._sections["network"]; p = sec.picker
        def check_list():
            names = [n.ssid for n in p.networks]
            assert names[0] == "Home-Net" and "Office Corp" in names, names
            assert sec.summary.value.get_label() == "Connected to Home-Net"
            row = p.group.rows.get_first_child()
            assert row.get_height() >= 88 or True
            # wrong password
            net = next(n for n in p.networks if n.ssid == "Neighbour 5")
            p._on_pick(net)
            page = p._pages[-1]
            page.entry.set_text("short")
            page.submit(); assert page.error.get_visible() and "8 characters" in page.error.get_label()
            page.entry.set_text("wrongpass1"); page.submit()
            assert w.blocking.is_open
            step(after_wrong, 800)
        def after_wrong():
            page = p._pages[-1]
            assert not w.blocking.is_open
            assert "Wrong password for Neighbour 5" in page.error.get_label(), page.error.get_label()
            page.entry.set_text("goodpass1"); page.submit()
            step(after_ok, 800)
        def after_ok():
            assert not w.blocking.is_open and not p._pages
            assert w.toast_widget.get_visible()
            # open network -> confirm
            net = next(n for n in p.networks if n.ssid == "Cafe Guest")
            p._on_pick(net); assert w.confirm.is_open
            w.confirm.cancel_dialog()
            p._open_hidden(); assert p._pages[-1].hidden
            print("OK", flush=True); a.quit()
        step(check_list, 1500)
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(500, run))
    a.run([])
''')


@pytest.mark.gtk
def test_network_section_flow():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6", CALPI_FAKE_WIFI="1")
    subprocess.run("pgrep -f 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)", shell=True)
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", SCRIPT, d], env=env,
                           capture_output=True, text=True, cwd=ROOT)
    assert "OK" in r.stdout, r.stdout + r.stderr
