from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest

from calpi.data import sample_data
from calpi.data.event_store import EventStore

TZ = ZoneInfo("Europe/Berlin")
TODAY = date(2026, 3, 18)   # a Wednesday


@pytest.fixture
def store(tmp_path):
    s = EventStore(tmp_path / "s.sqlite3")
    yield s
    s.close()


def test_load_twice_same(store):
    n1 = sample_data.load(store, TODAY, TZ)
    n2 = sample_data.load(store, TODAY, TZ, clear=True)
    n3 = sample_data.load(store, TODAY, TZ)
    assert n1 == n2 == n3 == store.count_events()
    assert len(store.list_calendars()) == 4


def test_cases_present(store):
    sample_data.load(store, TODAY, TZ)
    day = lambda d, e=None: store.events_for_days(d, e or d + timedelta(days=1), TZ)
    today = day(TODAY)
    assert sum(not e.all_day for e in today) >= 3
    assert any(e.all_day for e in today)
    assert "Old archived meeting" not in [e.summary for e in today]
    assert any(e.summary.startswith("Busy day") for e in day(TODAY + timedelta(days=2)))
    assert len([e for e in day(TODAY + timedelta(days=2)) if e.summary.startswith("Busy")]) == 9
    month = store.events_for_days(date(2026, 3, 1), date(2026, 4, 1), TZ)
    summ = {e.summary for e in month}
    assert {"Movie night", "Weekend at the lake", "School trip", "Release night"} <= summ
    assert any(len(e.summary) > 80 for e in month)
    trip = next(e for e in month if e.summary == "School trip")
    assert (trip.end - trip.start).days == 3 and trip.start.weekday() == 5
    lake = next(e for e in month if e.summary == "Weekend at the lake")
    assert (lake.end - lake.start) == timedelta(hours=42)
    night = next(e for e in month if e.summary == "Release night")
    assert night.start.astimezone(TZ).month == 3 and night.end.astimezone(TZ).month == 4
    assert store.events_for_days(date(2026, 2, 1), date(2026, 3, 1), TZ)
    assert store.events_for_days(date(2026, 4, 1), date(2026, 5, 1), TZ)
    weekly = store.events_for_days(date(2025, 12, 1), date(2026, 7, 1), TZ)
    assert sum(e.summary == "Football practice" for e in weekly) >= 20
    hidden = store.events_for_days(date(2026, 3, 1), date(2026, 4, 1), TZ, include_hidden=True)
    assert len(hidden) > len(month)


def test_cli(tmp_path, capsys):
    from calpi import paths
    try:
        assert sample_data.main(["--load", "--state-dir", str(tmp_path), "--today", "2026-03-18"]) == 0
        assert "loaded" in capsys.readouterr().out
    finally:
        paths.set_state_dir_override(None)
    assert (tmp_path / "calpi.sqlite3").exists()
