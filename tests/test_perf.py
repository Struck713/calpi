import os

from calpi import perf
from calpi.data import sample_data, timeutil
from datetime import date


def setup_function(_):
    perf.reset()


def test_percentiles_nearest_rank():
    v = list(range(1, 101))
    assert perf.percentile(v, 50) == 50
    assert perf.percentile(v, 90) == 90
    assert perf.percentile(v, 100) == 100
    assert perf.percentile([], 90) == 0.0
    assert perf.percentile([7], 90) == 7


def test_record_stats_and_skip():
    for i in range(1, 11):
        perf.record("x", i * 10.0)
    s = perf.stats("x")
    assert (s["n"], s["p50"], s["p90"], s["max"], s["min"]) == (10, 50.0, 90.0, 100.0, 10.0)
    assert perf.stats("x", skip=5)["min"] == 60.0
    assert perf.stats("missing")["n"] == 0
    assert "x" in perf.report()


def test_samples_are_bounded():
    for i in range(perf.MAX_SAMPLES * 3):
        perf.record("b", 1.0)
    assert perf.stats("b")["n"] == perf.MAX_SAMPLES


def test_span_records():
    with perf.span("s"):
        pass
    assert perf.stats("s")["n"] == 1


def test_listener_and_no_paint():
    seen = []
    fn = lambda n, ms: seen.append(n)
    perf.add_listener(fn)
    perf.record("l", 1.0)
    perf.remove_listener(fn)
    perf.record("l", 1.0)
    assert seen == ["l"]
    perf.record_no_paint("np")
    assert perf.report()["np"]["no_paint"] == 1


def test_boot_and_process_start_marks():
    assert perf.since_boot_ms() > 0
    start = perf.process_start_since_boot_ms()
    assert start is not None and 0 < start < perf.since_boot_ms()
    assert perf.cpu_ticks() is not None and perf.rss_mb() > 0


def test_sample_data_scale():
    tz = timeutil.display_tz()
    d = date(2026, 9, 15)
    one = sample_data.scaled_events(d, tz, 1)
    five = sample_data.scaled_events(d, tz, 5)
    assert len(five) == 5 * len(one)
    ids = {(e.uid, e.recurrence_id) for e in five}
    assert len(ids) == len(five)
    assert [e.uid for e in one] == [e.uid for e in sample_data.sample_events(d, tz)]


def test_report_table_and_verdicts():
    from calpi.devtools import report
    d = {"scenarios": {"month_nav": {"month_change": {"n": 50, "p50": 90, "p90": 200, "max": 250}},
                       "idle": {"total_cpu_pct": 1.0}},
         "meta": {"rss_mb_start": 80, "rss_mb_end": 120}}
    rows = {r[0]: r[3] for r in report.evaluate(d)}
    assert rows["Month change p90"] == "MISS"
    assert rows["Month change max"] == "OK"
    assert rows["Idle CPU (app + parent)"] == "OK"
    assert rows["Open day detail p90"] == "--"
    assert report.main.__name__ == "main"
    assert report.load('x\nCALPI_BENCH_RESULT {"a": 1}')["a"] == 1
    assert "Month change p90" in report.format_table(d)
