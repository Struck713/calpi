import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run(tmp_path, *extra, env=None):
    e = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":6",
             RUNTIME_DIRECTORY=str(tmp_path / "rt"), **(env or {}))
    return subprocess.run([sys.executable, "run.py", "--windowed", "--state-dir", str(tmp_path / "st"),
                           "--exit-after", "1", *extra], cwd=ROOT, env=e, capture_output=True,
                          text=True, timeout=30)


@pytest.mark.gtk
def test_crash_loop_enters_safe_mode(tmp_path):
    subprocess.run([str(ROOT / "scripts/smoke.sh")], capture_output=True)   # ensures broadwayd on :6
    for _ in range(4):
        r = _run(tmp_path, env={"CALPI_TEST_CRASH": "render"})
        assert r.returncode == 1
    r = _run(tmp_path, env={"CALPI_TEST_CRASH": "render"})
    assert r.returncode == 0 and "SAFE MODE" in r.stdout + r.stderr


@pytest.mark.gtk
def test_corrupt_db_is_reset_and_app_starts(tmp_path):
    subprocess.run([str(ROOT / "scripts/smoke.sh")], capture_output=True)
    (tmp_path / "st").mkdir()
    (tmp_path / "st" / "calpi.sqlite3").write_bytes(os.urandom(4000))
    r = _run(tmp_path)
    assert r.returncode == 0 and "integrity check" in r.stdout + r.stderr
    assert list((tmp_path / "st").glob("calpi.sqlite3.corrupt-*"))
