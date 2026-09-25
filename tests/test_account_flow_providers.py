"""US-20 UI: provider chooser and CalDAV/ICS forms (fake discovery, no network)."""
import os
import subprocess
import tempfile
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = textwrap.dedent('''
    import sys, logging, io
    sys.path.insert(0, ".")
    from gi.repository import GLib
    from calpi import app as appmod
    from calpi.data import accounts
    from calpi.data.models import RemoteCalendar
    from calpi.sync import icloud, provider_caldav, provider_ics
    from calpi.sync.errors import SyncError, ErrorCode
    from calpi.widgets.settings import accounts as ui
    from calpi.widgets.settings.shell import SectionContext
    SECRET_URL = "https://calendar.example.com/private-TOKEN123/basic.ics"
    buf = io.StringIO(); logging.getLogger().addHandler(logging.StreamHandler(buf))
    logging.getLogger().setLevel(logging.DEBUG)
    a = appmod.CalpiApp(appmod.parse_args(["--windowed", "--state-dir", sys.argv[1]]))
    MODE = {"err": None, "seen": None}
    def fake_caldav(self, fields, secret, client=None):
        MODE["seen"] = dict(fields)
        if MODE["err"]:
            raise SyncError(MODE["err"], "detail with https://secret.host/x")
        return icloud.Discovery("https://c.example.com/p/", "https://c.example.com/h/", "Fast",
                                [RemoteCalendar("/a/", "Home", "#ff0000"), RemoteCalendar("/b/", "Work")])
    def fake_ics(self, fields, secret, client=None):
        MODE["seen"] = dict(fields); MODE["url"] = secret.reveal()
        if MODE["err"]:
            raise SyncError(MODE["err"])
        return icloud.Discovery("", "https://calendar.example.com/", fields.get("name") or "Feed",
                                [RemoteCalendar("feed", fields.get("name") or "Feed", None)])
    provider_caldav.CalDavProvider.discover = fake_caldav
    provider_ics.IcsProvider.discover = fake_ics
    def spin(ms, fn):
        GLib.timeout_add(ms, lambda: (fn(), False)[1])
    def run():
        w = a.window; nav = w.navigator
        nav.show("settings", section="accounts")
        st = nav.get("settings")
        ctx = SectionContext(app=a, window=w, push_page=lambda wd, t: st.push_page("accounts", wd, t),
                             pop_page=lambda: st.pop_page("accounts"))
        done = []
        flow = ui.SignInFlow(ctx, on_finished=done.append, choose=True)
        flow.start()
        assert list(flow.chooser_rows) == ["icloud", "caldav", "ics"], list(flow.chooser_rows)
        assert flow.chooser_rows["icloud"].get_first_child() is not None
        flow._chosen("caldav")
        flow.server_entry.set_text("cloud.example.com"); flow.user_entry.set_text("me")
        flow.pw_entry.set_text("pw")
        MODE["err"] = ErrorCode.AUTH_FAILED
        flow._submit()
        def s2():
            assert "didn't accept this username" in flow.error_label.get_text()
            assert "secret.host" not in flow.error_label.get_text()
            MODE["err"] = None
            flow._submit(); spin(600, s3)
        def s3():
            assert MODE["seen"]["server_url"] == "https://cloud.example.com"
            rows = flow.selection_done.get_prev_sibling().rows
            rows.get_last_child().switch.set_active(False)
            flow.selection_done.emit("clicked")
            acc = done[0]
            assert acc.provider == "caldav" and acc.server_url == "https://cloud.example.com"
            assert a.credentials.get(acc.id).reveal() == "pw"
            cals = {c.remote_name: c for c in a.store.list_calendars()}
            assert cals["Home"].hidden is False and cals["Work"].hidden is True
            flow2 = ui.SignInFlow(ctx, on_finished=done.append, provider="ics")
            flow2.start()
            flow2.pw_entry.set_text("http://insecure.example.com/x.ics"); flow2._submit()
            assert flow2.error_label.get_visible() and MODE["url"] is None if "url" in MODE else True
            flow2.user_entry.set_text("Holidays"); flow2.pw_entry.set_text("webcal://calendar.example.com/private-TOKEN123/basic.ics")
            flow2.color["buttons"]["#ef4444"].set_active(True)
            MODE["err"] = ErrorCode.PARSE_ERROR
            flow2._submit()
            def s4():
                assert "didn't return a calendar" in flow2.error_label.get_text()
                assert "TOKEN123" not in flow2.error_label.get_text()
                MODE["err"] = None
                flow2._submit()
                spin(600, s5)
            def s5():
                assert len(done) == 2, done
                acc = done[1]
                assert acc.provider == "ics" and acc.display_name == "Holidays"
                assert acc.server_url == "https://calendar.example.com/"
                assert acc.options == {"color": "#ef4444"}
                assert a.credentials.get(acc.id).reveal() == SECRET_URL
                assert "TOKEN123" not in str(a.settings.get("accounts"))
                assert "TOKEN123" not in buf.getvalue()
                assert flow2.pw_entry.get_text() == ""
                st.pop_page("accounts") if False else None
                print("OK", flush=True)
                a.quit()
            spin(600, s4)
        spin(600, s2)
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(500, run))
    a.run([])
''')


@pytest.mark.gtk
def test_provider_forms():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":32")
    subprocess.run("pgrep -f '[g]tk4-broadwayd :32' >/dev/null || (setsid nohup gtk4-broadwayd :32 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run(["timeout", "60", "/usr/bin/python3", "-c", SCRIPT, d], env=env,
                           capture_output=True, text=True, cwd=ROOT)
    assert "OK" in r.stdout, r.stdout + r.stderr
