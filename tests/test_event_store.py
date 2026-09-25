import time as _time
import warnings
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from calpi.data import db
from calpi.data.event_store import EventStore
from calpi.data.models import Calendar, Event

BERLIN = ZoneInfo("Europe/Berlin")
NY = ZoneInfo("America/New_York")
UTC = timezone.utc


@pytest.fixture
def store(tmp_path):
    s = EventStore(tmp_path / "t.sqlite3")
    s.upsert_calendar(Calendar("c1", "One", remote_color="#AABBCC"))
    yield s
    s.close()


def timed(uid, start, end, cal="c1", summary=None, **kw):
    return Event(cal, uid, summary or uid, False, start.astimezone(UTC), end.astimezone(UTC), **kw)


def allday(uid, start, end, cal="c1", summary=None):
    return Event(cal, uid, summary or uid, True, start, end)


def uids(evs):
    return [e.uid for e in evs]


def L(y, m, d, h=0, mi=0, tz=UTC):
    return datetime(y, m, d, h, mi, tzinfo=tz)


def test_pragmas(store):
    c = store.conn
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("PRAGMA synchronous").fetchone()[0] == 1
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_migrations(tmp_path, monkeypatch):
    p = tmp_path / "m.sqlite3"
    c = db.connect(p)
    assert db.schema_version(c) == 1
    c.close()
    c = db.connect(p)
    assert db.schema_version(c) == 1
    c.close()
    calls = []

    def v2(conn):
        calls.append(1)
        conn.execute("CREATE TABLE extra(x)")

    monkeypatch.setattr(db, "MIGRATIONS", [*db.MIGRATIONS, v2])
    c = db.connect(p)
    assert db.schema_version(c) == 2 and calls == [1]
    c.close()
    db.connect(p).close()
    assert calls == [1]

    def v3(conn):
        conn.execute("CREATE TABLE half(x)")
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "MIGRATIONS", [*db.MIGRATIONS, v3])
    with pytest.raises(RuntimeError):
        db.connect(p)
    monkeypatch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:2])
    c = db.connect(p)
    assert db.schema_version(c) == 2
    assert c.execute("SELECT name FROM sqlite_master WHERE name='half'").fetchone() is None


def test_timed_overlap(store):
    d0, d1 = date(2026, 6, 10), date(2026, 6, 12)   # [10th 00:00, 12th 00:00) Berlin
    s, e = L(2026, 6, 10, tz=BERLIN), L(2026, 6, 12, tz=BERLIN)
    h = timedelta(hours=1)
    evs = [
        timed("before", s - 2 * h, s - h),
        timed("ends_at_start", s - h, s),
        timed("starts_at_end", e, e + h),
        timed("straddle_start", s - h, s + h),
        timed("straddle_end", e - h, e + h),
        timed("covers", s - h, e + h),
        timed("zero_at_start", s, s),
        timed("zero_before", s - h, s - h),
        timed("inside", s + 5 * h, s + 6 * h),
    ]
    store.replace_calendar_events("c1", evs)
    got = set(uids(store.events_for_days(d0, d1, BERLIN)))
    assert got == {"straddle_start", "straddle_end", "covers", "zero_at_start", "inside"}


def test_allday_overlap(store):
    store.replace_calendar_events("c1", [
        allday("first", date(2026, 6, 10), date(2026, 6, 11)),
        allday("day_before", date(2026, 6, 9), date(2026, 6, 10)),
        allday("multi_in", date(2026, 6, 8), date(2026, 6, 11)),
        allday("at_end", date(2026, 6, 12), date(2026, 6, 13)),
        allday("last", date(2026, 6, 11), date(2026, 6, 12)),
    ])
    got = set(uids(store.events_for_days(date(2026, 6, 10), date(2026, 6, 12), NY)))
    assert got == {"first", "multi_in", "last"}


def test_all_day_floating_across_timezones(store):
    store.replace_calendar_events("c1", [allday("a", date(2026, 3, 5), date(2026, 3, 6))])
    for tz in (BERLIN, NY, ZoneInfo("Pacific/Auckland")):
        assert uids(store.events_for_days(date(2026, 3, 5), date(2026, 3, 6), tz)) == ["a"]
        assert store.events_for_days(date(2026, 3, 6), date(2026, 3, 7), tz) == []


def test_dst(store):
    # Berlin DST starts 2026-03-29 (02:00 -> 03:00)
    store.replace_calendar_events("c1", [
        timed("next_day_0230", L(2026, 3, 30, 2, 30, BERLIN), L(2026, 3, 30, 3, 0, BERLIN)),
        timed("change_day", L(2026, 3, 29, 0, 30, BERLIN), L(2026, 3, 29, 1, 30, BERLIN)),
        timed("late_prev", L(2026, 3, 28, 23, 30, BERLIN), L(2026, 3, 28, 23, 59, BERLIN)),
    ])
    day = lambda d: uids(store.events_for_days(date(2026, 3, d), date(2026, 3, d + 1), BERLIN))
    assert day(30) == ["next_day_0230"]
    assert day(29) == ["change_day"]
    assert day(28) == ["late_prev"]
    assert len(store.events_for_days(date(2026, 3, 1), date(2026, 4, 1), BERLIN)) == 3


def test_sort_order(store):
    store.upsert_calendar(Calendar("c2", "Two", sort_order=-1))
    store.replace_calendar_events("c1", [
        timed("t_late", L(2026, 6, 10, 12), L(2026, 6, 10, 13), summary="b"),
        timed("t_early_short", L(2026, 6, 10, 9), L(2026, 6, 10, 10), summary="z"),
        timed("t_early_long", L(2026, 6, 10, 9), L(2026, 6, 10, 11), summary="z"),
        allday("ad_short", date(2026, 6, 10), date(2026, 6, 11), summary="a"),
        allday("ad_long", date(2026, 6, 10), date(2026, 6, 13), summary="z"),
    ])
    store.replace_calendar_events("c2", [
        timed("t_early_short_c2", L(2026, 6, 10, 9), L(2026, 6, 10, 10), cal="c2", summary="z"),
    ])
    got = uids(store.events_for_days(date(2026, 6, 10), date(2026, 6, 11), UTC))
    assert got == ["ad_long", "ad_short", "t_early_long", "t_early_short_c2", "t_early_short", "t_late"]


def test_hidden(store):
    store.upsert_calendar(Calendar("h", "Hidden", hidden=True))
    store.replace_calendar_events("h", [allday("x", date(2026, 6, 10), date(2026, 6, 11), cal="h")])
    args = (date(2026, 6, 10), date(2026, 6, 11), UTC)
    assert store.events_for_days(*args) == []
    assert uids(store.events_for_days(*args, include_hidden=True)) == ["x"]


def test_upsert_keeps_overrides(store):
    store.set_calendar_overrides("c1", user_name="Mine", user_color="#112233", hidden=True, sort_order=5)
    store.upsert_calendar(Calendar("c1", "Renamed", remote_color="#000000", user_name="X",
                                   hidden=False, sort_order=0))
    c = store.get_calendar("c1")
    assert (c.remote_name, c.remote_color) == ("Renamed", "#000000")
    assert (c.user_name, c.user_color, c.hidden, c.sort_order) == ("Mine", "#112233", True, 5)
    assert c.name == "Mine" and c.color == "#112233"
    store.set_calendar_overrides("c1", hidden=False)
    c = store.get_calendar("c1")
    assert c.hidden is False and c.user_name == "Mine" and c.sort_order == 5


def test_color_normalised(store):
    assert store.get_calendar("c1").remote_color == "#aabbcc"


def test_replace_atomic(store, tmp_path):
    a = [allday("old1", date(2026, 6, 1), date(2026, 6, 2)), allday("old2", date(2026, 6, 2), date(2026, 6, 3))]
    store.replace_calendar_events("c1", a)
    other = EventStore(tmp_path / "t.sqlite3")

    def gen():
        yield allday("new1", date(2026, 6, 1), date(2026, 6, 2))
        assert uids(other.events_for_days(date(2026, 6, 1), date(2026, 7, 1), UTC)) == ["old1", "old2"]
        raise RuntimeError("stop")

    with pytest.raises(RuntimeError):
        store.replace_calendar_events("c1", gen())
    assert uids(other.events_for_days(date(2026, 6, 1), date(2026, 7, 1), UTC)) == ["old1", "old2"]
    # Mid-transaction visibility after real deletes/inserts
    rev = store.revision()
    orig = store.conn.executemany

    class Spy:
        def __init__(s, c): s.c = c
        def __getattr__(s, n): return getattr(s.c, n)
        def executemany(s, *a, **k):
            r = s.c.executemany(*a, **k)
            assert uids(other.events_for_days(date(2026, 6, 1), date(2026, 7, 1), UTC)) == ["old1", "old2"]
            return r

    real = store.conn
    store.conn = Spy(real)
    try:
        store.replace_calendar_events("c1", [allday("new", date(2026, 6, 3), date(2026, 6, 4))])
    finally:
        store.conn = real
    assert uids(other.events_for_days(date(2026, 6, 1), date(2026, 7, 1), UTC)) == ["new"]
    assert store.revision() == rev + 1
    other.close()


def test_duplicates_last_wins(store):
    n = store.replace_calendar_events("c1", [
        allday("u", date(2026, 6, 1), date(2026, 6, 2), summary="first"),
        allday("u", date(2026, 6, 1), date(2026, 6, 2), summary="last"),
    ])
    assert n == 1
    assert [e.summary for e in store.events_for_days(date(2026, 6, 1), date(2026, 6, 2), UTC)] == ["last"]


def test_cascade(store):
    store.replace_calendar_events("c1", [allday("u", date(2026, 6, 1), date(2026, 6, 2))])
    store.delete_calendar("c1")
    assert store.count_events() == 0


def test_delete_for_account_and_sample(store):
    store.upsert_calendar(Calendar("acc:1", "A", account_id="acc"))
    store.upsert_calendar(Calendar("sample:X", "S"))
    store.delete_sample_data()
    assert store.get_calendar("sample:X") is None
    store.delete_calendars_for_account("acc")
    assert [c.id for c in store.list_calendars()] == ["c1"]


def test_revision_increments(store):
    r = store.revision()
    store.upsert_calendar(Calendar("c2", "Two"))
    assert store.revision() == r + 1
    store.set_calendar_overrides("c2", hidden=True)
    assert store.revision() == r + 2
    store.replace_calendar_events("c2", [])
    assert store.revision() == r + 3
    store.delete_calendar("c2")
    assert store.revision() == r + 4


def test_integrity(store):
    assert store.integrity_ok() is True


def test_event_validation():
    with pytest.raises(ValueError):
        Event("c", "u", "s", False, datetime(2026, 1, 1), datetime(2026, 1, 2))
    with pytest.raises(ValueError):
        Event("c", "u", "s", True, datetime(2026, 1, 1, tzinfo=UTC), date(2026, 1, 2))
    with pytest.raises(ValueError):
        Event("c", "u", "s", True, date(2026, 1, 2), date(2026, 1, 1))


def test_performance(store):
    base = L(2025, 6, 1)
    evs = [timed(f"e{i}", base + timedelta(hours=i * 3 + 1), base + timedelta(hours=i * 3 + 2))
           for i in range(4000)]
    evs += [allday(f"a{i}", date(2025, 6, 1) + timedelta(days=i % 700), date(2025, 6, 2) + timedelta(days=i % 700))
            for i in range(1000)]
    assert store.replace_calendar_events("c1", evs) == 5000
    store.events_for_days(date(2025, 8, 1), date(2025, 9, 1), UTC)   # warm up
    t = _time.perf_counter()
    got = store.events_for_days(date(2025, 8, 1), date(2025, 9, 1), UTC)
    ms = (_time.perf_counter() - t) * 1000
    assert got
    if ms > 20:
        warnings.warn(f"month query took {ms:.1f} ms (target 20)")
    assert ms < 200
