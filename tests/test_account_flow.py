"""US-25 GTK flow with a fake icloud.discover (no network, no real account)."""
import os
import subprocess
import tempfile
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = textwrap.dedent('''
    import sys
    sys.path.insert(0, ".")
    from gi.repository import GLib, Gtk
    from calpi import app as appmod
    from calpi.data import accounts
    from calpi.data.models import RemoteCalendar, Calendar
    from calpi.sync import icloud
    from calpi.sync.errors import SyncError, ErrorCode
    from calpi.widgets.settings import accounts as ui
    a = appmod.CalpiApp(appmod.parse_args(["--windowed", "--state-dir", sys.argv[1]]))
    MODE = {"err": None}
    def fake(user, secret, client=None):
        if MODE["err"]:
            raise SyncError(MODE["err"])
        return icloud.Discovery("https://p/1/principal/", "https://p/1/calendars/", "Me",
                                [RemoteCalendar("/a/", "Home", "#ff0000"), RemoteCalendar("/b/", "Work")])
    icloud.discover = fake
    def spin(ms, fn):
        GLib.timeout_add(ms, lambda: (fn(), False)[1])
    def run():
        w = a.window; nav = w.navigator
        a.store.upsert_calendar(Calendar(id="sample:x", remote_name="Sample"))
        nav.show("settings", section="accounts")
        st = nav.get("settings")
        sec = st._sections["accounts"]
        done = []
        flow = ui.SignInFlow(st._sections and __import__("calpi.widgets.settings.shell", fromlist=["x"]).SectionContext(
            app=a, window=w, push_page=lambda wd, t: st.push_page("accounts", wd, t),
            pop_page=lambda: st.pop_page("accounts")), on_finished=done.append)
        flow.start()
        flow.user_entry.set_text("bad"); flow._submit()
        assert flow.error_label.get_visible()
        flow.user_entry.set_text("Me@iCloud.com"); flow.pw_entry.set_text("wrong")
        flow._submit(); assert not flow.error_label.get_text().startswith("Signing")
        flow.pw_entry.set_text("ABCD EFGH IJKL MNOP")
        MODE["err"] = ErrorCode.AUTH_FAILED
        flow._submit()
        def step2():
            assert "Apple didn't accept" in flow.error_label.get_text(), flow.error_label.get_text()
            assert not w.blocking.is_open and not accounts.list_accounts(a.settings)
            MODE["err"] = None
            flow._submit()
            spin(600, step3)
        def step3():
            assert not w.blocking.is_open
            # deselect calendar B, then Done
            flow.selection_done.get_parent()
            g = flow.selection_done.get_prev_sibling()
            rows = g.rows
            row = rows.get_last_child()
            row.switch.set_active(False)
            flow.selection_done.emit("clicked")
            assert done and a.credentials.get(done[0].id).reveal() == "abcd-efgh-ijkl-mnop"
            cals = {c.remote_name: c for c in a.store.list_calendars()}
            assert cals["Home"].hidden is False and cals["Work"].hidden is True and "Sample" not in cals
            assert flow.pw_entry.get_text() == "" and flow.user_entry.get_text() == ""
            sec._refresh(); assert len(accounts.list_accounts(a.settings)) == 1
            # remove + reconcile
            a.store.upsert_calendar(Calendar(id="orph", remote_name="O", account_id="icloud-zzz"))
            a.reconcile_accounts()
            assert a.store.get_calendar("orph") is None
            sec._do_remove(done[0])
            assert not accounts.list_accounts(a.settings) and a.credentials.ids() == []
            assert a.store.list_calendars() == []
            print("OK", flush=True)
            a.quit()
        spin(600, step2)
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(500, run))
    a.run([])
''')


@pytest.mark.gtk
def test_signin_flow():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6")
    subprocess.run("pgrep -f 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run(["timeout", "60", "/usr/bin/python3", "-c", SCRIPT, d], env=env,
                           capture_output=True, text=True, cwd=ROOT)
    assert "OK" in r.stdout, r.stdout + r.stderr
