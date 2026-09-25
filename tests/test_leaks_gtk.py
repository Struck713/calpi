"""US-37 leak hunting: run the whole app under the soak driver on virtual time (CALPI_SOAK_SELFTEST) and
compare a census taken after a warm-up with one taken after many more cycles of the same activity
(month navigation, day detail, Settings tour, OSK, syncs, dim preview, mini benchmark).

Flat by construction: widget counts per screen, every callback list, settings observers, timer names,
open fds, threads, GTK object types. (RSS is NOT compared: Broadway buffers frames when no browser is
attached, which grows any GTK app; the Pi's RSS is checked by the multi-day soak.)
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_selftest(tmp_path, ticks, only=None):
    disp = os.environ.get("BROADWAY_DISPLAY", ":6")
    subprocess.run(f"pgrep -fx 'gtk4-broadwayd {disp}' >/dev/null || "
                   f"(setsid nohup gtk4-broadwayd {disp} >/dev/null 2>&1 </dev/null & sleep 1)", shell=True)
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=disp, GSK_RENDERER="cairo",
               STATE_DIRECTORY=str(tmp_path / "st"), RUNTIME_DIRECTORY=str(tmp_path / "rt"),
               CALPI_SKIP_SETUP="1", CALPI_SAMPLE_DATA="1", CALPI_SOAK="1", CALPI_SOAK_SELFTEST=str(ticks))
    if only:
        env["CALPI_SOAK_ONLY"] = only
    (tmp_path / "st").mkdir()
    (tmp_path / "rt").mkdir()
    r = subprocess.run(["timeout", "170", sys.executable, "run.py", "--windowed"], env=env, cwd=ROOT,
                       capture_output=True, text=True)
    lines = [x for x in r.stdout.splitlines() if x.startswith("SOAK_SELFTEST ")]
    assert lines, r.stdout[-2000:] + r.stderr[-3000:]
    assert "Traceback" not in r.stderr, r.stderr[-3000:]
    return json.loads(lines[0].split(" ", 1)[1])


def _assert_flat(res):
    a, b = res["before"], res["after"]
    assert res["errors"] == 0
    assert a["widgets"] == b["widgets"], "widget count changed per screen"
    assert a["window_widgets"] == b["window_widgets"]
    growth = {k: (a["lists"][k], b["lists"][k]) for k in a["lists"]
              if k != "navigator.history" and a["lists"][k] != b["lists"][k]}
    assert not growth, f"callback lists / subscriptions changed: {growth}"
    assert b["lists"]["navigator.history"] <= 10
    ignore = {"sync-schedule"}                                 # armed only between syncs
    assert set(a["sources"]) - ignore == set(b["sources"]) - ignore, (a["sources"], b["sources"])
    assert b["perf_listeners"] == a["perf_listeners"] == 0
    assert abs(b["fds"] - a["fds"]) <= 2, (a["fds"], b["fds"])
    assert abs(b["threads"] - a["threads"]) <= 2, (a["threads"], b["threads"])
    gtk = {k: (a["gtk_objects"].get(k, 0), v) for k, v in b["gtk_objects"].items()
           if v > a["gtk_objects"].get(k, 0) + 3}
    assert not gtk, f"GTK object types growing: {gtk}"
    assert b["py_objects"] < a["py_objects"] * 1.03, (a["py_objects"], b["py_objects"])


@pytest.mark.gtk
def test_soak_cycles_leave_no_growth(tmp_path):
    res = _run_selftest(tmp_path, 260)
    for name in ("sync", "month_nav", "day", "settings", "osk", "dim"):
        assert res["counts"].get(name, 0) >= 3, res["counts"]
    _assert_flat(res)
