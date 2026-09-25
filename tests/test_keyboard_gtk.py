import os
import subprocess
import textwrap

import pytest

SCRIPT = textwrap.dedent('''
    import sys
    sys.path.insert(0, ".")
    from gi.repository import Gtk, GLib
    from calpi.data.keyboard_layouts import Key
    from calpi.widgets.keyboard import KeyboardDock, _focus_belongs_to, make_password_field
    win = Gtk.Window(); win.overlay = Gtk.Overlay()
    class Nav:
        current = None
        def show(self, *a, **k): pass
        def get(self, n): return None
    win.navigator = Nav()
    box = Gtk.Box(); win.overlay.set_child(box); win.set_child(win.overlay)
    email = Gtk.Entry(); pwbox, pw, _t = make_password_field(); pe = Gtk.PasswordEntry()
    for w in (email, pwbox, pe): box.append(w)
    dock = KeyboardDock(win)
    done = []
    dock.attach(email, "email", "Next"); dock.attach(pw, "password"); dock.attach(pe, "password")
    email.connect("activate", lambda *_: done.append(1))
    win.present()
    ctx = GLib.MainContext.default()
    def pump():
        for _ in range(50): ctx.iteration(False)
    pump()
    for ent in (email, pw):
        ent.grab_focus(); pump()
        assert dock.get_visible()
        assert _focus_belongs_to(win.get_focus(), ent)
        ent.set_text("")
        for k in (Key(insert="a"),) * 3: dock._apply(k)
        assert ent.get_text() == "aaa" and ent.get_position() == 3
        dock._apply(Key(action="backspace")); assert ent.get_text() == "aa"
        dock._apply(Key(action="shift")); dock._apply(Key(insert="a")); dock._apply(Key(insert="a"))
        assert ent.get_text() == "aaAa", ent.get_text()
        dock._apply(Key(action="left")); assert ent.get_position() == 3
        ent.select_region(0, -1); dock._apply(Key(insert="x")); assert ent.get_text() == "x"
        dock._apply(Key(action="clear")); assert ent.get_text() == ""
        assert _focus_belongs_to(win.get_focus(), ent)
    email.grab_focus(); pump()
    dock._apply(Key(action="done")); assert done
    assert dock.reserved_height >= 420
    pe.grab_focus(); pump()
    assert _focus_belongs_to(win.get_focus(), pe) and dock.get_visible()
    pe.emit("activate")
    dock._apply(Key(action="hide")); assert not dock.get_visible()
    print("OK")
''')


@pytest.mark.gtk
def test_keyboard_editing():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6")
    subprocess.run("pgrep -fx 'gtk4-broadwayd :6' >/dev/null || (setsid nohup gtk4-broadwayd :6 >/dev/null 2>&1 </dev/null & sleep 1)",
                   shell=True)
    r = subprocess.run(["timeout", "30", "/usr/bin/python3", "-c", SCRIPT], env=env,
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert "OK" in r.stdout, r.stdout + r.stderr
