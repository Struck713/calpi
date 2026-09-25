import time

import pytest

from calpi.data import db, sync_status as ss
from calpi.data.credentials import _REDACTOR
from calpi.data.event_store import EventStore
from calpi.data.models import Calendar
from calpi.sync import worker

from test_worker import env, make_deps  # noqa: F401
from test_fetch import ACC, Fake, WORK, HOMECAL


@pytest.fixture
def store(tmp_path):
    s = EventStore(tmp_path / "s.sqlite3")
    s.upsert_calendar(Calendar(id="c1", account_id="a1", remote_name="Family"))
    return s


def cal_row(store, cid="c1"):
    return ss.snapshot(store.conn).calendars[[c.calendar_id for c in ss.snapshot(store.conn).calendars].index(cid)]


def test_upgrade_from_v1_keeps_data(tmp_path, monkeypatch):
    p = tmp_path / "u.sqlite3"
    monkeypatch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:1])
    s = EventStore(p)
    s.upsert_calendar(Calendar(id="c1", account_id="a1", remote_name="Family"))
    s.close()
    monkeypatch.undo()
    s = EventStore(p)
    assert [c.id for c in s.list_calendars()] == ["c1"]
    tables = {r[0] for r in s.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"account_sync_status", "calendar_sync_status", "sync_runs"} <= tables


def test_failure_success_cycle(store):
    c = store.conn
    ss.record_calendar(c, "c1", at=100, status="ok", events=5, duration_ms=30)
    for i in range(3):
        ss.record_calendar(c, "c1", at=200 + i, status="error", error="TIMEOUT", detail="slow")
    r = cal_row(store)
    assert r.consecutive_failures == 3 and r.last_success_at.timestamp() == 100
    assert r.last_error_code == "TIMEOUT" and r.last_status == "error" and r.last_event_count == 5
    ss.record_calendar(c, "c1", at=300, status="unchanged")
    r = cal_row(store)
    assert r.consecutive_failures == 0 and r.last_error_code is None and r.last_error_detail is None
    assert r.last_success_at.timestamp() == 300 and r.last_status == "unchanged"
    assert r.last_event_count == 5 and r.name == "Family" and not r.hidden


def test_account_status(store):
    c = store.conn
    ss.record_account(c, "a1", at=10)
    ss.record_account(c, "a1", at=20, error="AUTH_FAILED", detail="401")
    ss.record_account(c, "a1", at=30, error="AUTH_FAILED", detail="401")
    a = ss.snapshot(c).account("a1")
    assert a.consecutive_failures == 2 and a.last_success_at.timestamp() == 10
    assert a.last_error_at.timestamp() == 30 and a.last_attempt_at.timestamp() == 30
    ss.record_account(c, "a1", at=40)
    a = ss.snapshot(c).account("a1")
    assert a.consecutive_failures == 0 and a.last_error_code is None
    assert ss.snapshot(c).account("zzz") is None


def test_runs_pruned_and_ordered(store):
    for i in range(120):
        ss.record_run(store.conn, started_at=i, finished_at=i + 1, reason="interval", status="done",
                      duration_ms=5, ok=1, failed=0, changed=False)
    n = store.conn.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0]
    assert n == 100
    snap = ss.snapshot(store.conn)
    assert len(snap.runs) == 20 and snap.last_run().started_at.timestamp() == 119


def test_cascade_and_forget(store):
    ss.record_calendar(store.conn, "c1", at=1, status="ok")
    ss.record_account(store.conn, "a1", at=1)
    store.delete_calendar("c1")
    assert store.conn.execute("SELECT COUNT(*) FROM calendar_sync_status").fetchone()[0] == 0
    ss.forget_account(store.conn, "a1")
    assert ss.snapshot(store.conn).accounts == ()


def test_sanitize_detail():
    _REDACTOR.register("hunter2-secret")
    try:
        t = ss.sanitize_detail("bad\n  hunter2-secret  Authorization: Basic dXNlcjpwYXNz tail")
        assert "hunter2-secret" not in t and "dXNlcjpwYXNz" not in t and "\n" not in t
        assert "Basic dXNlcjpwYXNz" not in ss.sanitize_detail("sent Basic dXNlcjpwYXNz")
    finally:
        _REDACTOR._values.discard("hunter2-secret")
    assert len(ss.sanitize_detail("x" * 1000)) == 300


def test_status_writes_do_not_bump_revision(store):
    rev = store.revision()
    ss.record_calendar(store.conn, "c1", at=1, status="ok")
    ss.record_account(store.conn, "a1", at=1)
    ss.record_run(store.conn, started_at=1, finished_at=2, reason="x", status="done",
                  duration_ms=1, ok=1, failed=0, changed=False)
    ss.forget_account(store.conn, "a1")
    assert store.revision() == rev


def test_snapshot_fast(tmp_path):
    s = EventStore(tmp_path / "f.sqlite3")
    for i in range(20):
        s.upsert_calendar(Calendar(id=f"c{i}", account_id="a1", remote_name=f"Cal {i}"))
        ss.record_calendar(s.conn, f"c{i}", at=1, status="ok", events=3, duration_ms=9)
    ss.record_account(s.conn, "a1", at=1)
    for i in range(100):
        ss.record_run(s.conn, started_at=i, finished_at=i, reason="x", status="done", duration_ms=1,
                      ok=1, failed=0, changed=False)
    t = time.perf_counter()
    snap = ss.snapshot(s.conn)
    assert time.perf_counter() - t < 0.05
    assert len(snap.calendars) == 20 and len(snap.calendars_of("a1")) == 20


# --- worker integration ---

def test_worker_records_and_recovers(env):
    fake = Fake(reports={WORK: (503, {}, b"<html>busy secret body</html>"), HOMECAL: Fake().reports[HOMECAL],
                         **{k: v for k, v in Fake().reports.items() if k not in (WORK, HOMECAL)}})
    deps = make_deps(env, fake)
    worker.run(worker.parse_args(["--reason", "t"]), deps)
    s = EventStore(env / "w.sqlite3")
    snap = ss.snapshot(s.conn)
    a = snap.account(ACC.id)
    assert a.last_attempt_at and a.last_success_at and a.consecutive_failures == 0
    cals = {c.name: c for c in snap.calendars}
    assert cals["Work"].last_status == "error" and cals["Work"].consecutive_failures == 1
    assert cals["Work"].last_error_code and not cals["Work"].inherited
    assert cals["Home"].last_status == "ok" and cals["Home"].last_event_count is not None
    assert snap.last_run().reason == "t" and snap.last_run().accounts_failed == 1
    s.close()
    worker.run(worker.parse_args([]), make_deps(env))                # healthy transport now
    s = EventStore(env / "w.sqlite3")
    snap = ss.snapshot(s.conn)
    w = {c.name: c for c in snap.calendars}["Work"]
    assert w.last_status == "ok" and w.consecutive_failures == 0 and w.last_error_code is None
    assert w.last_success_at is not None and len(snap.runs) == 2
    worker.run(worker.parse_args([]), make_deps(env))
    s2 = ss.snapshot(s.conn)
    assert {c.name: c for c in s2.calendars}["Work"].last_status == "unchanged"


def test_worker_account_error_inherits_to_calendars(env):
    fake = Fake(propfind=(401, {}, b"nope"))
    deps = make_deps(env, Fake())
    worker.run(worker.parse_args([]), deps)                          # populate calendars first
    worker.run(worker.parse_args([]), make_deps(env, fake))
    s = EventStore(env / "w.sqlite3")
    snap = ss.snapshot(s.conn)
    a = snap.account(ACC.id)
    assert a.last_error_code == "AUTH_FAILED" and a.consecutive_failures == 1 and a.last_success_at
    cs = snap.calendars_of(ACC.id)
    assert cs and all(c.inherited and c.last_error_code == "AUTH_FAILED" for c in cs)
    assert all(c.last_success_at is not None for c in cs)


def test_worker_unreadable_credentials_recorded(env):
    worker.run(worker.parse_args([]), make_deps(env, creds=False))
    s = EventStore(env / "w.sqlite3")
    assert ss.snapshot(s.conn).account(ACC.id).last_error_code == "CREDENTIALS_UNREADABLE"


def test_status_write_failure_never_fails_sync(env, monkeypatch):
    import sqlite3

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(ss, "record_account", boom)
    monkeypatch.setattr(ss, "record_run", boom)
    r = worker.run(worker.parse_args([]), make_deps(env))
    assert r["status"] == "done" and r["accounts"][0]["error"] is None


@pytest.mark.gtk
def test_app_account_status_text(store):
    pytest.importorskip("gi")
    from types import SimpleNamespace
    from calpi import app as appmod
    fake = SimpleNamespace(sync_status=None, _provider_names=lambda: {})
    text = lambda: appmod.CalpiApp.account_status_text(fake, "a1")   # noqa: E731
    assert text() == "Added"
    ss.record_account(store.conn, "a1", at=int(time.time()))
    fake.sync_status = ss.snapshot(store.conn)
    assert text().startswith("Synced ")
    ss.record_account(store.conn, "a1", at=int(time.time()), error="AUTH_FAILED", detail="x")
    fake.sync_status = ss.snapshot(store.conn)
    from calpi.data import messages          # US-38: catalogue wording, never the raw code
    assert text() == messages.describe("AUTH_REVOKED", context="banner", provider="iCloud").title
    assert "AUTH_FAILED" not in text()


def test_failing_since_tracks_streak_start(tmp_path):
    from calpi.data import db, sync_status as ss
    conn = db.connect(tmp_path / "x.sqlite3")
    ss.record_account(conn, "a", at=10, error="TIMEOUT")
    ss.record_account(conn, "a", at=20, error="TIMEOUT")
    a = ss.snapshot(conn).account("a")
    assert a.consecutive_failures == 2 and a.failing_since.timestamp() == 10
    ss.record_account(conn, "a", at=30)
    assert ss.snapshot(conn).account("a").failing_since is None
    ss.record_account(conn, "a", at=40, error="AUTH_FAILED")
    assert ss.snapshot(conn).account("a").failing_since.timestamp() == 40
