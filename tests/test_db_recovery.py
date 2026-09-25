import os

import pytest

from calpi.data import db
from calpi.data.event_store import EventStore


def _make(path):
    conn = db.connect(path)
    with db.write_txn(conn):
        conn.execute("INSERT INTO calendars(id, remote_name) VALUES ('c1', 'x')")
        conn.execute("CREATE TABLE junk(a BLOB)")
        for _ in range(200):
            conn.execute("INSERT INTO junk VALUES (?)", (os.urandom(500),))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()


def test_missing_and_healthy(tmp_path):
    p = tmp_path / "calpi.sqlite3"
    assert db.recover_if_corrupt(p) is False
    _make(p)
    assert db.recover_if_corrupt(p) is False
    assert p.exists()


def test_empty_file_is_valid(tmp_path):
    p = tmp_path / "calpi.sqlite3"
    p.write_bytes(b"")
    assert db.recover_if_corrupt(p) is False


@pytest.mark.parametrize("how", ["garbage", "truncate", "header"])
def test_corrupt_is_moved_aside(tmp_path, how):
    p = tmp_path / "calpi.sqlite3"
    _make(p)
    size = p.stat().st_size
    if how == "garbage":
        with open(p, "r+b") as f:
            f.seek(0)
            f.write(os.urandom(size))
    elif how == "truncate":
        os.truncate(p, 100)
    else:
        with open(p, "r+b") as f:
            f.write(b"NOT A SQLITE DATABASE!")
    (tmp_path / "calpi.sqlite3-wal").write_bytes(b"junk")
    assert db.recover_if_corrupt(p) is True
    assert not p.exists()
    assert list(tmp_path.glob("calpi.sqlite3.corrupt-*"))
    store = EventStore(p)
    assert store.integrity_ok()
    store.close()


def test_keeps_only_two_sets(tmp_path):
    p = tmp_path / "calpi.sqlite3"
    for ts in (100, 200, 300):
        (tmp_path / f"calpi.sqlite3.corrupt-{ts}").write_bytes(b"x")
        (tmp_path / f"calpi.sqlite3.corrupt-{ts}-wal").write_bytes(b"x")
    p.write_bytes(b"NOT A SQLITE DATABASE!" * 200)
    assert db.recover_if_corrupt(p)
    names = sorted(x.name for x in tmp_path.glob("calpi.sqlite3.corrupt-*") if not x.name.endswith("-wal"))
    assert len(names) == 2 and "calpi.sqlite3.corrupt-100" not in names
