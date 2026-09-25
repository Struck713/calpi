import json
import os
import subprocess
import tempfile
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FRESH = textwrap.dedent('''
    import sys
    sys.path.insert(0, ".")
    from gi.repository import GLib
    from calpi import app as appmod
    from calpi.data.settings_store import K_SETUP_COMPLETED, K_WIZARD_STEP
    from calpi.logging_setup import setup_logging; setup_logging()
    a = appmod.CalpiApp(appmod.parse_args(["--windowed"]))
    def run():
        w = a.window; nav = w.navigator
        wz = nav.get("wizard")
        assert nav.current == "wizard", nav.current
        assert wz.current == "welcome" and not wz.back_btn.get_visible() and not wz.skip_btn.get_visible()
        assert wz.next_btn.get_label() == "Start"
        wz.go_next()
        assert wz.current == "wifi" and wz.progress_label.get_text().startswith("Step 1 of ")
        assert a.settings.get(K_WIZARD_STEP) == "wifi"
        assert wz.back_btn.get_visible() and wz.skip_btn.get_visible()
        wz.on_key("Escape", 0)
        assert wz.current == "welcome"
        wz.on_key("Escape", 0)
        assert wz.current == "welcome"
        wz.go_next()
        # footer hides while the keyboard is up
        wz.on_keyboard_visible(True); assert not wz.footer.get_visible()
        wz.on_keyboard_visible(False); assert wz.footer.get_visible()
        # a sub-page: Back pops it before leaving the step
        from gi.repository import Gtk
        wz.ctx.push_page(Gtk.Label(label="x"), "Sub")
        assert not wz.next_btn.get_visible() and wz.host_pages("wifi") == 1
        wz.back(); assert wz.host_pages("wifi") == 0 and wz.current == "wifi"
        seen = [wz.current]
        while wz.current != "done":
            wz.skip(); seen.append(wz.current)
        assert seen[:5] == ["wifi", "preferences", "account", "refresh", "overnight"], seen
        assert wz.title.get_text() == "All set" and wz.progress_label.get_text() == ""
        assert wz.results.get("account") == "skipped"
        assert wz.next_btn.get_label() == "Show calendar" and not wz.skip_btn.get_visible()
        wz.go_next()
        assert nav.current == "calendar"
        assert a.settings.get(K_SETUP_COMPLETED) is True and a.settings.get(K_WIZARD_STEP) is None
        # run again from About
        nav.show("settings"); st = nav.get("settings"); st.select("about")
        about = st._sections["about"]
        about._start_setup()
        assert nav.current == "wizard" and a.settings.get(K_SETUP_COMPLETED) is False
        assert nav.get("wizard").current == "welcome"
        print("OK", flush=True)
        a.quit()
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(800, run))
    a.run([])
''')

RESUME = textwrap.dedent('''
    import sys
    sys.path.insert(0, ".")
    from gi.repository import GLib
    from calpi import app as appmod
    from calpi.logging_setup import setup_logging; setup_logging()
    a = appmod.CalpiApp(appmod.parse_args(["--windowed"]))
    def run():
        nav = a.window.navigator
        assert nav.current == "wizard", nav.current
        assert nav.get("wizard").current == "refresh", nav.get("wizard").current
        print("OK", flush=True)
        a.quit()
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(800, run))
    a.run([])
''')

MIGRATE = textwrap.dedent('''
    import sys
    sys.path.insert(0, ".")
    from gi.repository import GLib
    from calpi import app as appmod
    from calpi.data.settings_store import K_SETUP_COMPLETED
    from calpi.logging_setup import setup_logging; setup_logging()
    a = appmod.CalpiApp(appmod.parse_args(["--windowed"]))
    def run():
        assert a.window.navigator.current == "calendar", a.window.navigator.current
        assert a.settings.get(K_SETUP_COMPLETED) is True
        print("OK", flush=True)
        a.quit()
        return False
    a.connect("activate", lambda *_: GLib.timeout_add(800, run))
    a.run([])
''')

ACCOUNT = {"id": "a1", "provider": "icloud", "username": "me@icloud.com", "display_name": "me",
           "server_url": "", "principal_url": "", "calendar_home_url": "", "created_at": "2026-01-01"}


def _run(script, settings, env_extra=None):
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":32",
               CALPI_NO_SYSTEM_TZ="1", CALPI_TZ="UTC", CALPI_FAKE_WIFI="1", CALPI_SKIP_SETUP="0", **(env_extra or {}))
    subprocess.run("pgrep -fx 'gtk4-broadwayd :32' >/dev/null || "
                   "(setsid nohup gtk4-broadwayd :32 >/dev/null 2>&1 </dev/null & sleep 1)", shell=True)
    with tempfile.TemporaryDirectory() as d:
        if settings is not None:
            with open(os.path.join(d, "settings.json"), "w") as f:
                json.dump(dict(schema_version=1, **settings), f)
        env.update(CALPI_STATE_DIR=d, RUNTIME_DIRECTORY=d)
        r = subprocess.run(["timeout", "60", "/usr/bin/python3", "-c", script], env=env,
                           capture_output=True, text=True, cwd=ROOT)
    return r


@pytest.mark.gtk
def test_fresh_flow_skip_all_and_run_again():
    r = _run(FRESH, None)
    assert "OK" in r.stdout, r.stdout + r.stderr
    assert "setup: start screen=wizard" in r.stdout + r.stderr


@pytest.mark.gtk
def test_resume_saved_step():
    r = _run(RESUME, {"wizard_step": "refresh"})
    assert "OK" in r.stdout, r.stdout + r.stderr


@pytest.mark.gtk
def test_existing_accounts_migrate():
    r = _run(MIGRATE, {"accounts": [ACCOUNT]})
    assert "OK" in r.stdout, r.stdout + r.stderr
