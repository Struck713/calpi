import importlib.util
import os
from datetime import datetime, timedelta

import pytest

from calpi import health

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("soak_analyze", os.path.join(ROOT, "scripts", "soak-analyze.py"))
sa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sa)

T0 = datetime(2026, 9, 1, 0, 5, 0)


def rows(hours=100, rss=lambda h: 90.0, fds=lambda h: 20, sources=lambda h: 6, threads=lambda h: 5,
         wal=lambda h: 0.2, db=lambda h: 1.2, sync_procs=lambda h: 0, uptime=lambda h: h * 3600, mini=None):
    out = []
    for h in range(hours):
        out.append({"kind": "sample", "ts": (T0 + timedelta(hours=h)).isoformat(timespec="seconds"),
                    "rss_mb": rss(h), "fds": fds(h), "threads": threads(h), "sources": sources(h),
                    "sync_procs": sync_procs(h), "db_mb": db(h), "wal_mb": wal(h), "journal_mb": 18,
                    "uptime_s": uptime(h), "p90_ms": ""})
        if mini and h % 6 == 0:
            out.append({"kind": "minirun", "ts": (T0 + timedelta(hours=h, minutes=1)).isoformat(timespec="seconds"),
                        "p90_ms": mini(h)})
    return out


def failed(res):
    return [n for n, ok, _d in res["checks"] if ok is False]


def test_slope_is_least_squares_per_day():
    xs = [0, 1, 2, 3]
    assert sa.slope_per_day(xs, [10, 12, 14, 16]) == pytest.approx(2.0)
    assert sa.slope_per_day(xs, [5, 5, 5, 5]) == 0.0
    assert sa.slope_per_day([1], [3]) == 0.0


def test_flat_run_passes():
    res = sa.analyze(rows(mini=lambda h: 100.0))
    assert failed(res) == [] and res["ok"]
    assert res["metrics"]["rss_mb"]["slope_per_day"] == pytest.approx(0.0, abs=1e-9)


def test_rss_leak_detected():
    res = sa.analyze(rows(rss=lambda h: 90 + h * 0.05))          # 1.2 MB/day
    assert any("rss slope" in n for n in failed(res))
    assert not res["ok"]


def test_warmup_growth_is_ignored():
    res = sa.analyze(rows(rss=lambda h: 90 + min(h, 10) * 3.0))      # grows only during the first 12 h
    assert failed(res) == []


def test_rss_over_150_fails():
    assert any("rss max" in n for n in failed(sa.analyze(rows(rss=lambda h: 151.0))))


@pytest.mark.parametrize("key,fn,needle", [
    ("fds", lambda h: 20 + h // 20, "fds flat"),
    ("threads", lambda h: 5 + h // 20, "threads flat"),
    ("sources", lambda h: 6 + h // 20, "sources flat")])
def test_growing_counts_detected(key, fn, needle):
    res = sa.analyze(rows(**{key: fn}))
    assert any(needle in n for n in failed(res))


def test_counts_within_two_pass():
    assert failed(sa.analyze(rows(fds=lambda h: 20 + (h % 3)))) == []


def test_wal_over_8mb_fails_even_during_warmup():
    res = sa.analyze(rows(wal=lambda h: 9.0 if h == 2 else 0.1))
    assert any("wal" in n for n in failed(res))


def test_db_growth_and_stuck_sync_process():
    assert any("db size" in n for n in failed(sa.analyze(rows(db=lambda h: 1.0 + h * 0.05))))
    assert any("sync process" in n for n in failed(sa.analyze(rows(sync_procs=lambda h: 1 if 20 < h < 30 else 0))))
    assert failed(sa.analyze(rows(sync_procs=lambda h: 1 if h in (30, 60) else 0))) == []     # a sync running at sample time


def test_render_time_regression():
    res = sa.analyze(rows(mini=lambda h: 100.0 if h < 30 else 130.0))
    assert any("p90" in n for n in failed(res))
    assert failed(sa.analyze(rows(mini=lambda h: 100.0 + h * 0.1))) == []


def test_restart_detected_from_uptime_reset():
    res = sa.analyze(rows(uptime=lambda h: (h % 50) * 3600))
    assert any("no restarts" in n for n in failed(res))


def test_journal_checks():
    journal = "\n".join(f"2026-09-{d:02d}T00:00:01 clock: day changed" for d in range(1, 5))
    res = sa.analyze(rows(hours=24 * 4), journal_text=journal)
    assert failed(res) == []
    bad = sa.analyze(rows(hours=24 * 4), journal_text=journal + "\nWatchdog timeout\nSAFE MODE")
    assert "journal has no 'Watchdog timeout'" in failed(bad) and "journal has no 'SAFE MODE'" in failed(bad)
    missing = sa.analyze(rows(hours=24 * 4), journal_text="clock: day changed")
    assert "midnight rollover every day" in failed(missing)


def test_no_samples_fails():
    assert not sa.analyze([])["ok"]


def test_journal_to_csv_round_trip(tmp_path):
    line = health.format_line(health.HealthSample(87.3, 23, 3, 3, 9, 0, 1.2, 0.1, 18.0, 3 * 86400 + 4 * 3600))
    text = (f"2026-09-25T10:00:03+0200 calpi calpi-kiosk[123]: INFO calpi.health: {line}\n"
            "2026-09-25T10:00:09+0200 calpi calpi-kiosk[123]: INFO calpi.soak: health: minirun month_nav n=17 p50=80.0ms p90=112.5ms\n"
            "2026-09-25T10:00:10+0200 other line\n")
    rows_ = sa.journal_to_rows(text)
    assert [r["kind"] for r in rows_] == ["sample", "minirun"]
    assert rows_[0]["rss_mb"] == "87.3" and rows_[0]["uptime_s"] == 3 * 86400 + 4 * 3600
    assert rows_[1]["p90_ms"] == "112.5"
    p = tmp_path / "x.csv"
    sa.write_csv(rows_, str(p))
    assert sa.read_csv(str(p))[0]["fds"] == "23"


def test_cli_exit_codes_and_markdown(tmp_path):
    p = tmp_path / "ok.csv"
    sa.write_csv(rows(mini=lambda h: 100.0), str(p))
    md = tmp_path / "s.md"
    assert sa.main(["analyze", str(p), "--markdown", str(md)]) == 0
    assert "| rss_mb |" in md.read_text() and "PASS" in md.read_text()
    q = tmp_path / "bad.csv"
    sa.write_csv(rows(rss=lambda h: 90 + h), str(q))
    assert sa.main(["analyze", str(q)]) == 1
    assert sa.main(["analyze", str(tmp_path / "nope.csv")]) == 2


# ---- the driver's pure scheduler
def test_scheduler_runs_due_entries_once_and_survives_errors():
    from calpi.devtools.soak import Entry, Scheduler
    ran = []

    def boom():
        raise RuntimeError("x")
    s = Scheduler([Entry("a", 10, lambda: ran.append("a")), Entry("b", 30, boom)], now=0.0, stagger=False)
    assert s.run_due(9) == []
    assert s.run_due(10) == ["a"] and s.run_due(11) == []
    assert s.run_due(30) == ["a", "b"] and s.errors == 1
    s.call_later(30, 5, lambda: ran.append("later"))
    s.run_due(34)
    assert "later" not in ran
    s.run_due(35)
    assert ran[-1] == "later"


def test_scheduler_staggers_first_runs():
    from calpi.devtools.soak import Entry, Scheduler
    s = Scheduler([Entry(str(i), 60, lambda: None) for i in range(5)], now=0.0)
    firsts = sorted(e.next_due for e in s.entries)
    assert len(set(firsts)) == 5 and all(0 < t < 60 for t in firsts)
