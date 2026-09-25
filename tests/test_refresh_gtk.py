import os
import subprocess
import time
import textwrap

import pytest

SCRIPT = textwrap.dedent('''
    import sys, time
    sys.path.insert(0, ".")
    from types import SimpleNamespace
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import GLib, Gtk
    from calpi.tasks import CallbackList
    from calpi.widgets.sync_indicator import SyncIndicator
    from calpi.widgets.refresh_button import RefreshButton

    def pump(ms):
        end = time.monotonic() + ms / 1000
        ctx = GLib.MainContext.default()
        while time.monotonic() < end:
            ctx.iteration(False)
            time.sleep(0.01)

    eng = SimpleNamespace(state_callbacks=CallbackList(), result_callbacks=CallbackList(),
                          is_running=False, last_success_wall=None)
    asked = []
    app = SimpleNamespace(sync=eng, trigger_manual_refresh=lambda: asked.append(1))
    ind = SyncIndicator(eng)
    ind.MIN_RUNNING_S = 0.3
    btn = RefreshButton(app)
    win = Gtk.Window(); box = Gtk.Box(); box.append(ind); box.append(btn); win.set_child(box); win.present()
    pump(200)
    assert len(eng.state_callbacks) == 2       # indicator + button (subscribed on realize)
    btn.emit("clicked"); assert asked == [1]
    eng.is_running = True; eng.state_callbacks.call(True)
    assert not btn.get_sensitive() and ind.get_text() == "Updating\\u2026"
    eng.is_running = False
    eng.result_callbacks.call({"status": "done", "reason": "manual", "accounts": [{"account_id": "a", "error": None}]})
    eng.state_callbacks.call(False)
    assert btn.get_sensitive()
    assert ind.get_text() == "Updating\\u2026"          # held for the minimum time
    pump(500)
    assert ind.get_text() == "Updated just now" and ind.has_css_class("ok"), ind.get_text()
    ind.show_transient("Couldn't update: offline", "error", 1)
    assert ind.has_css_class("error")
    pump(1300)
    assert not ind.has_css_class("error") and ind.get_text() != "Couldn't update: offline"
    win.destroy(); pump(100)
    assert len(eng.state_callbacks) == 1, len(eng.state_callbacks)
    print("OK")
''')


@pytest.mark.gtk
def test_refresh():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":19", GSK_RENDERER="cairo")
    if subprocess.run(["pgrep", "-f", "[g]tk4-broadwayd :19"], capture_output=True).returncode != 0:
        subprocess.Popen(["gtk4-broadwayd", ":19"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1)
    r = subprocess.run(["timeout", "60", "/usr/bin/python3", "-c", SCRIPT], env=env,
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "OK" in r.stdout, r.stdout + r.stderr
