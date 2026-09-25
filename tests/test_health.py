import logging
import os
import subprocess
import sys
import time
from datetime import datetime

import pytest

from calpi import health, tasks
from calpi.health import HealthSample


def mk(rss=80.0, fds=20, **kw):
    d = dict(rss_mb=rss, fds=fds, threads_py=3, threads_os=5, sources=6, sync_procs=0, db_mb=1.2,
             wal_mb=0.1, journal_mb=18.0, uptime_s=3 * 86400 + 4 * 3600 + 5)
    d.update(kw)
    return HealthSample(**d)


def test_line_format_is_the_contract():
    line = health.format_line(mk(rss=87.3, fds=23, threads_os=3, sources=9))
    assert line == ("health: rss=87.3MB fds=23 threads=3 sources=9 sync_procs=0 db=1.2MB wal=0.1MB "
                    "journal=18MB uptime=3d04h")


def test_line_round_trip_and_no_journal():
    p = health.parse_line("prefix " + health.format_line(mk(journal_mb=None)))
    assert p["journal_mb"] is None and p["rss_mb"] == 80.0 and p["uptime_s"] == 3 * 86400 + 4 * 3600
    assert health.parse_line("health: minirun month_nav n=20") is None


def test_uptime_format():
    assert health.format_uptime(59) == "0d00h"
    assert health.format_uptime(86400 * 14 + 3600 * 23) == "14d23h"


@pytest.mark.parametrize("text,mb", [
    ("Archived and active journals take up 18.0M in the file system.", 18.0),
    ("Archived and active journals take up 1.5G in the file system.", 1536.0),
    ("Archived and active journals take up 512.0K in the file system.", 0.5),
    ("garbage", None)])
def test_parse_journal_usage(text, mb):
    assert health.parse_journal_usage(text) == mb


N = lambda h: datetime(2026, 1, 1, h, 30)


def test_valve_only_at_night_between_limits():
    assert health.check_limits(mk(rss=349), N(3)) is None
    assert health.check_limits(mk(rss=351), N(12)) is None            # daytime: leave it alone
    assert "rss=351MB" in health.check_limits(mk(rss=351), N(3))
    assert health.check_limits(mk(rss=351), N(1)) is None            # before 02:00
    assert health.check_limits(mk(rss=351), N(5)) is None            # from 05:00 no more
    assert health.check_limits(mk(fds=500), N(3)) is None
    assert "fds=501" in health.check_limits(mk(fds=501), N(2))
    assert health.check_limits(mk(fds=501), N(14)) is None


def test_valve_emergency_any_time():
    assert "450" in health.check_limits(mk(rss=451), N(14))
    assert health.check_limits(mk(rss=450), N(14)) is None


def test_real_sample_is_plausible():
    s = health.sample()
    assert 5 < s.rss_mb < 2000 and s.fds >= 3 and s.threads_os >= 1 and s.threads_py >= 1
    assert s.uptime_s >= 0 and s.zombies == 0


def test_child_processes_counts_children_and_zombies():
    base, _ = health.child_processes()
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    z = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            kids, zombies = health.child_processes()
            if zombies:
                break
            time.sleep(0.05)
        assert kids == base + 2 and zombies >= 1          # z exited, not yet waited for
        z.wait()
        assert health.child_processes()[0] == base + 1
    finally:
        p.kill()
        p.wait()


def test_db_and_wal_sizes(tmp_path, monkeypatch):
    from calpi import paths
    paths.set_state_dir_override(str(tmp_path))
    try:
        (tmp_path / "calpi.sqlite3").write_bytes(b"x" * 1048576)
        (tmp_path / "calpi.sqlite3-wal").write_bytes(b"x" * 524288)
        assert health.db_sizes() == (1.0, 0.5)
    finally:
        paths.set_state_dir_override(None)


# ---- the periodic registry (US-37 step 1)
@pytest.fixture
def clean_registry():
    saved = (dict(tasks._periodic), dict(tasks._periodic_interval))
    tasks._periodic.clear()
    tasks._periodic_interval.clear()
    yield
    tasks._periodic.clear()
    tasks._periodic_interval.clear()
    tasks._periodic.update(saved[0])
    tasks._periodic_interval.update(saved[1])


def test_registry_register_unregister_and_duplicate_warning(clean_registry, caplog):
    tasks.register_periodic("clock", 11, 60)
    with caplog.at_level(logging.WARNING, logger="calpi.tasks"):
        tasks.register_periodic("clock", 12)
    assert "registered twice" in caplog.text
    assert tasks.periodic_sources() == {"clock": 12}
    tasks.update_periodic("clock", 13)                       # re-armed: no warning
    assert tasks.periodic_sources() == {"clock": 13}
    tasks.unregister_periodic("clock")
    tasks.unregister_periodic("clock")                        # idempotent
    assert tasks.periodic_sources() == {}


def test_registry_add_and_remove_real_source(clean_registry):
    sid = tasks.add_periodic_seconds("x", 3600, lambda: True)
    assert tasks.periodic_sources() == {"x": sid}
    assert tasks.periodic_wakeups_per_hour() == {"x": 1.0}
    tasks.remove_periodic("x")
    assert tasks.periodic_sources() == {}


def test_periodic_sources_returns_a_copy(clean_registry):
    tasks.register_periodic("a", 1)
    tasks.periodic_sources()["b"] = 2
    assert "b" not in tasks.periodic_sources()


class FakeApp:
    exit_code = 0
    quit_called = False

    def quit(self):
        self.quit_called = True


def test_monitor_trip_exits_75_and_logs_error(caplog):
    app = FakeApp()
    mon = health.HealthMonitor(app)
    with caplog.at_level(logging.ERROR, logger="calpi.health"):
        mon.trip("rss=400MB > 350MB")
    assert app.exit_code == 75 and app.quit_called
    assert "health: resource limit exceeded (rss=400MB > 350MB), restarting" in caplog.text


def test_monitor_emit_logs_line_and_trips(monkeypatch, caplog):
    app = FakeApp()
    mon = health.HealthMonitor(app, now=lambda: datetime(2026, 1, 1, 3, 0))
    monkeypatch.setattr(health, "sample", lambda journal_mb=None: mk(rss=400.0, journal_mb=journal_mb))
    with caplog.at_level(logging.INFO, logger="calpi.health"):
        mon._emit(20.0, "hourly")
    assert "health: rss=400.0MB" in caplog.text and "journal=20MB" in caplog.text
    assert app.exit_code == 75
    app2 = FakeApp()
    mon2 = health.HealthMonitor(app2, now=lambda: datetime(2026, 1, 1, 15, 0))
    mon2._emit(None, "hourly")
    assert app2.exit_code == 0


def test_leak_tools_diff_and_census():
    import tracemalloc
    was = tracemalloc.is_tracing()
    tracemalloc.start(25)
    try:
        lt = health.LeakTools()
        assert "first snapshot" in lt.snapshot_lines()[0]
        keep = [bytes(1000) for _ in range(500)]
        lines = lt.snapshot_lines()
        assert lines[0].startswith("leak: top 30") and len(lines) > 1
        del keep
    finally:
        if not was:
            tracemalloc.stop()
    census = health.object_census(5)
    assert len(census) == 5 and all(isinstance(c, int) for _n, c in census)


def test_leakcheck_is_off_by_default(monkeypatch):
    import tracemalloc
    monkeypatch.delenv("CALPI_LEAKCHECK", raising=False)
    assert not health.leakcheck_enabled()
    was = tracemalloc.is_tracing()
    health.start_leakcheck()
    assert tracemalloc.is_tracing() == was
