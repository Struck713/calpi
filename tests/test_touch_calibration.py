import os
import subprocess
import sys
import textwrap
import time

import pytest

from calpi.system import touchcal as tc

W, H = 1920, 1080


def test_targets_nine_points():
    t = tc.targets(W, H)
    assert len(t) == 9 and t[0] == (60, 60) and t[4] == (960, 540) and t[8] == (1860, 1020)


def test_offset_and_summary():
    t = tc.targets(W, H)
    dx, dy, d = tc.offset((63, 56), t)
    assert (dx, dy) == (3, -4) and d == pytest.approx(5)
    s = tc.summarize([5, 11.9])
    assert s["ok"] and s["max"] == 11.9
    assert not tc.summarize([13])["ok"]
    assert not tc.summarize([])["ok"]


def _measure(matrix_inv, tgts):
    return [(t, tc.apply(matrix_inv, t, W, H)) for t in tgts]


def test_fit_identity():
    pts = [(t, t) for t in tc.targets(W, H)]
    m = tc.fit_calibration(pts, W, H)
    assert m == pytest.approx(tc.IDENTITY, abs=1e-9)


def test_fit_scale_offset():
    # panel reports x = 0.97*t + 20, y = 1.02*t - 10 (px); the fit must undo that
    tg = tc.targets(W, H)
    pts = [(t, (0.97 * t[0] + 20, 1.02 * t[1] - 10)) for t in tg]
    m = tc.fit_calibration(pts, W, H)
    for t, meas in pts:
        x, y = tc.apply(m, meas, W, H)
        assert abs(x - t[0]) < 1e-6 and abs(y - t[1]) < 1e-6


def test_fit_mirrored_is_rotate_180():
    tg = tc.targets(W, H)
    pts = [(t, (W - t[0], H - t[1])) for t in tg]
    m = tc.fit_calibration(pts, W, H)
    assert m == pytest.approx(tc.ROTATE_180, abs=1e-9)


def test_fit_with_noise_within_tolerance():
    tg = tc.targets(W, H)
    noise = [(2, -1), (-2, 1), (1, 2), (-1, -2), (0, 0), (2, 2), (-2, -2), (1, -1), (-1, 1)]
    pts = [(t, (t[0] * 1.03 + 15 + n[0], t[1] * 0.98 + 5 + n[1])) for t, n in zip(tg, noise)]
    m = tc.fit_calibration(pts, W, H)
    dists = [tc.offset(tc.apply(m, meas, W, H), tg)[2] for _t, meas in pts]
    assert tc.summarize(dists)["ok"]


def test_compose_matches_sequential():
    cur, new = tc.ROTATE_180, (0.98, 0, 0.01, 0, 1.02, -0.02)
    p = (300.0, 700.0)
    seq = tc.apply(new, tc.apply(cur, p, W, H), W, H)
    both = tc.apply(tc.compose(new, cur), p, W, H)
    assert both == pytest.approx(seq)


def test_udev_rule():
    r = tc.udev_rule("ILITEK ILITEK-TP", "-1 0 1 0 -1 1")
    assert r == ('ACTION=="add|change", KERNEL=="event*", ATTRS{name}=="ILITEK ILITEK-TP", '
                 'ENV{LIBINPUT_CALIBRATION_MATRIX}="-1 0 1 0 -1 1"')
    with pytest.raises(ValueError):
        tc.udev_rule('bad"name', "1 0 0 0 1 0")
    with pytest.raises(ValueError):
        tc.udev_rule("x", "1 0 0")
    assert tc.format_matrix(tc.ROTATE_180) == "-1 0 1 0 -1 1"


def test_touchcal_has_no_gi():
    r = subprocess.run([sys.executable, "-c",
                        "import sys; import calpi.system.touchcal; assert 'gi' not in sys.modules"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


SCRIPT = textwrap.dedent('''
    import sys
    sys.path.insert(0, ".")
    from gi.repository import Gtk, GLib
    from calpi.widgets.dev_touch_test import DevTouchTest
    win = Gtk.Window(); win.set_default_size(1920, 1080)
    w = DevTouchTest(); win.set_child(w); win.present()
    ctx = GLib.MainContext.default()
    for _ in range(50): ctx.iteration(False)
    w._on_pressed(None, 1, 63, 56); w._on_pressed(None, 1, 500, 500)
    for _ in range(20): ctx.iteration(False)
    assert len(w.touches) == 2 and w.touches[0][4] == 5.0 and not w.summary()["ok"]
    w.clear(); assert w.touches == []
    print("OK")
''')


@pytest.mark.skipif(os.environ.get("CALPI_GTK_TESTS") != "1", reason="GTK tests off")
def test_dev_touch_screen_runs():
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":34", GSK_RENDERER="cairo")
    if subprocess.run(["pgrep", "-f", "[g]tk4-broadwayd :34"],
                      capture_output=True).returncode != 0:
        subprocess.Popen(["gtk4-broadwayd", ":34"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1)
    r = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True,
                       timeout=60, env=env)
    assert "OK" in r.stdout, r.stdout + r.stderr
