import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.gtk
def test_bench_driver_runs_and_reports(tmp_path):
    disp = os.environ.get("BROADWAY_DISPLAY", ":6")
    subprocess.run(f"pgrep -f '[g]tk4-broadwayd {disp}' >/dev/null || "
                   f"(setsid nohup gtk4-broadwayd {disp} >/dev/null 2>&1 </dev/null & sleep 1)", shell=True)
    state, run = tmp_path / "st", tmp_path / "rt"
    subprocess.run([sys.executable, "-m", "calpi.data.sample_data", "--load", "--scale", "2",
                    "--state-dir", str(state)], cwd=ROOT, check=True, capture_output=True)
    env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=disp, GSK_RENDERER="cairo",
               STATE_DIRECTORY=str(state), RUNTIME_DIRECTORY=str(run), CALPI_SKIP_SETUP="1",
               CALPI_BENCH="1", CALPI_BENCH_SCENARIOS="startup,month_nav,day_open,idle",
               CALPI_BENCH_N="0.1", CALPI_BENCH_STEP_MS="100", CALPI_BENCH_IDLE_S="1")
    r = subprocess.run(["timeout", "120", "/usr/bin/python3", "run.py", "--windowed"], env=env, cwd=ROOT,
                       capture_output=True, text=True)
    line = [x for x in r.stdout.splitlines() if x.startswith("CALPI_BENCH_RESULT ")]
    assert line, r.stdout[-2000:] + r.stderr[-2000:]
    d = json.loads(line[0].split(" ", 1)[1])
    sc = d["scenarios"]
    assert "error" not in json.dumps({k: v for k, v in sc.items() if isinstance(v, dict) and "error" in v})
    assert sc["month_nav"]["month_change_sync"]["n"] > 0
    assert "app_cpu_pct" in sc["idle"]
    assert d["meta"]["events"] > 0
    assert (run / "bench.json").exists() and (run / "bench.done").exists()
    # the marker stops a second run (systemd restart) from benchmarking again
    r2 = subprocess.run(["timeout", "20", "/usr/bin/python3", "run.py", "--windowed", "--exit-after", "3"],
                        env=env, cwd=ROOT, capture_output=True, text=True)
    assert "CALPI_BENCH_RESULT" not in r2.stdout
