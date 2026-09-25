"""US-37 criterion 6: the UI never pins the WAL (no open read transaction), and the worker can truncate it."""
import os
import sqlite3
from datetime import date

from calpi.data import db, sample_data, timeutil
from calpi.data.event_store import EventStore


def _wal(path):
    try:
        return os.stat(str(path) + "-wal").st_size
    except OSError:
        return 0


def test_wal_stays_small_while_ui_reads_and_worker_writes(tmp_path):
    path = tmp_path / "t.sqlite3"
    ui = EventStore(path)
    writer = EventStore(path)
    tz = timeutil.display_tz()
    sample_data.load(writer, timeutil.today(), tz)
    first, end = date(2026, 1, 1), date(2026, 2, 12)
    big = 0
    for i in range(1000):
        ui.events_for_days(first, end, tz)                   # a reader fetches everything right away
        with db.write_txn(writer.conn):
            writer.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('soak', ?)", (str(i),))
        big = max(big, _wal(path))
    # SQLite auto-checkpoints at 1000 pages (~4 MB); with no pinned snapshot it can always reset the log
    assert big < 6 * 1024 * 1024, big
    assert ui.conn.in_transaction is False


def test_ui_query_helpers_leave_no_open_transaction(tmp_path):
    ui = EventStore(tmp_path / "t.sqlite3")
    tz = timeutil.display_tz()
    sample_data.load(ui, timeutil.today(), tz)
    for fn in (lambda: ui.list_calendars(), lambda: ui.count_events(), lambda: ui.revision(),
               lambda: ui.events_for_days(date(2026, 1, 1), date(2026, 3, 1), tz)):
        fn()
        assert ui.conn.in_transaction is False


def test_a_pinned_reader_grows_the_wal_and_a_checkpoint_cannot_truncate(tmp_path):
    """Documents the failure mode the rule prevents (an unfinished SELECT holds a snapshot)."""
    path = tmp_path / "t.sqlite3"
    w = EventStore(path)
    r = sqlite3.connect(str(path), isolation_level=None)
    cur = r.execute("SELECT * FROM meta")
    cur.fetchone()                                            # statement left un-reset: a snapshot is pinned
    for i in range(300):
        with db.write_txn(w.conn):
            w.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, 'x')", (f"k{i}",))
    assert _wal(path) > 0
    cur.close()


def test_checkpoint_if_large_truncates_only_over_the_limit(tmp_path):
    path = tmp_path / "t.sqlite3"
    w = EventStore(path)
    w.conn.execute("PRAGMA wal_autocheckpoint=0")             # let it grow
    for i in range(400):
        with db.write_txn(w.conn):
            w.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (f"k{i}", "y" * 3000))
    size = _wal(path)
    assert size > 100_000
    assert db.wal_bytes(w.conn) == size
    assert db.checkpoint_if_large(w.conn, limit=size + 1) is False and _wal(path) == size
    assert db.checkpoint_if_large(w.conn, limit=size - 1) is True
    assert _wal(path) == 0


def test_checkpoint_helpers_never_raise_on_memory_db():
    conn = sqlite3.connect(":memory:")
    assert db.wal_bytes(conn) == 0
    assert db.checkpoint_if_large(conn) is False
