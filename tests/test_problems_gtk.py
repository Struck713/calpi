import os
import subprocess
import textwrap
import time

import pytest

SCRIPT = textwrap.dedent('''
    import sys, time
    sys.path.insert(0, ".")
    from datetime import timedelta
    from types import SimpleNamespace
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import GLib, Gtk
    from calpi.data import timeutil
    from calpi.data.sync_status import AccountStatus, StatusSnapshot
    from calpi.tasks import CallbackList
    from calpi.widgets.month_view import MonthView
    from calpi.widgets.problem_banner import ProblemController
    from calpi.widgets.sync_indicator import SyncIndicator

    def pump(ms):
        end = time.monotonic() + ms / 1000
        ctx = GLib.MainContext.default()
        while time.monotonic() < end:
            ctx.iteration(False); time.sleep(0.01)

    class S:
        d = {}
        def get(self, k): return [] if k == "accounts" else dict(self.d)
        def set(self, k, v): self.d = v; return True

    shown = []
    nav = SimpleNamespace(current="calendar", changed_callbacks=[],
                          show=lambda *a, **k: shown.append((a, k)), get=lambda n: None)
    mv = MonthView()
    eng = SimpleNamespace(state_callbacks=CallbackList(), result_callbacks=CallbackList(),
                          is_running=False, last_success_wall=None, offline=False)
    ind = SyncIndicator(eng)
    now = timeutil.now()
    t = now - timedelta(hours=1)
    app = SimpleNamespace(settings=S(), status_callbacks=[], network=None, clock_trust=None, sync=eng,
                          sync_status=None, startup_notices=[], safe_mode=False,
                          window=SimpleNamespace(navigator=nav, month_view=mv))
    win = Gtk.Window(); box = Gtk.Box(); box.append(ind); box.append(mv); win.set_child(box); win.present()
    ctl = ProblemController(app, mv.problem_banner, ind)
    pump(100)
    assert not mv.problem_banner.get_visible() and mv.weekday_row.get_visible()
    st = AccountStatus("a", now, t, "AUTH_FAILED", "x", now, 2, failing_since=now - timedelta(minutes=5))
    app.sync_status = StatusSnapshot(accounts=(st,))
    for cb in app.status_callbacks: cb(app.sync_status)
    assert mv.problem_banner.get_visible() and not mv.weekday_row.get_visible()
    assert "needs you to sign in again" in mv.problem_banner.text.get_text()
    assert mv.problem_banner.fix_button.get_label() == "Update password"
    assert ind.get_text() == "Sign-in problem" and ind.has_css_class("error")
    mv.problem_banner.fix_button.emit("clicked")
    assert shown[-1] == (("settings",), {"section": "accounts"}), shown
    mv.problem_banner.dismiss_button.emit("clicked")
    assert not mv.problem_banner.get_visible() and mv.weekday_row.get_visible()
    assert ind.get_text() == "Sign-in problem"             # header stays
    assert app.settings.d, "dismissal not persisted"
    nav.current = "wizard"; ctl.refresh()
    assert ind.get_text() != "Sign-in problem"
    print("OK")
''')


@pytest.mark.gtk
def test_problem_banner_and_header():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":38", GSK_RENDERER="cairo")
    if subprocess.run(["pgrep", "-f", "^gtk4-broadwayd :38$"], capture_output=True).returncode != 0:
        subprocess.Popen(["gtk4-broadwayd", ":38"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        time.sleep(1)
    r = subprocess.run(["timeout", "40", "/usr/bin/python3", "-c", SCRIPT], env=env, capture_output=True,
                       text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "OK" in r.stdout, r.stdout + r.stderr
