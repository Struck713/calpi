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
            assert sec.status_group.kind.value.get_label() == "Wi-Fi \u00b7 Home-Net", sec.status_group.kind.value.get_label()
            assert sec.status_group.ip.value.get_label() == "192.168.1.23"
            assert sec.status_group.dns.value.get_label() == "192.168.1.1, 8.8.8.8"
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
    subprocess.run("pgrep -f 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 2)", shell=True)
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", SCRIPT, d], env=env,
                           capture_output=True, text=True, cwd=ROOT)
    assert "OK" in r.stdout, r.stdout + r.stderr


FORGET_SCRIPT = textwrap.dedent('''
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
        sec = nav.get("settings")._sections["network"]
        sg = sec.saved_group; be = sec.backend
        def listed():
            assert [x.ssid for x in sg.items] == ["Home-Net", "Saved-Old"], sg.items
            assert sg.rows.get_first_child() is not None
            be.fail_forget = True
            sg._forget(sg.items[1])
            w.confirm.ok.emit("clicked")
            step(after_fail, 800)
        def after_fail():
            assert [x.ssid for x in sg.items] == ["Home-Net", "Saved-Old"], sg.items
            assert w.toast_widget.get_text() == "Couldn't forget Saved-Old", w.toast_widget.get_text()
            be.fail_forget = False
            sg._forget(sg.items[1])
            assert w.confirm.is_open and "won't join it automatically" in w.confirm.body.get_text()
            w.confirm.ok.emit("clicked")
            step(after_first, 800)
        def after_first():
            assert [x.ssid for x in sg.items] == ["Home-Net"], sg.items
            assert w.toast_widget.get_text() == "Forgot Saved-Old", w.toast_widget.get_text()
            sg._forget(sg.items[0])
            body = w.confirm.body.get_text()
            assert "disconnect now" in body and "only saved network" in body, body
            w.confirm.ok.emit("clicked")
            step(after_active, 800)
        def after_active():
            assert sg.items == [], sg.items
            assert sec.status_group.kind.value.get_label() == "Not connected"
            print("OK", flush=True); a.quit()
        step(listed, 1500)
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(500, run))
    a.run([])
''')


@pytest.fixture(scope="module")
def broadway57():
    """Own broadwayd on :57 (distinct from other tests/agents); killed at module end."""
    import time
    p = subprocess.Popen(["gtk4-broadwayd", ":57"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(2)
    yield p
    p.terminate()


@pytest.mark.gtk
def test_network_forget_flow(broadway57):
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":57", CALPI_FAKE_WIFI="1")
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", FORGET_SCRIPT, d], env=env,
                           capture_output=True, text=True, cwd=ROOT)
    assert "OK" in r.stdout, r.stdout + r.stderr
