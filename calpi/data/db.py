"""SQLite connection factory, write transactions and versioned migrations. No gi imports."""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from calpi import paths

log = logging.getLogger("calpi.db")
DB_NAME = "calpi.sqlite3"


def default_path() -> Path:
    return paths.state_dir() / DB_NAME


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection (one per thread/process; never share). Autocommit; use write_txn() for writes."""
    conn = sqlite3.connect(str(path or default_path()), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


@contextmanager
def write_txn(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE ... COMMIT, bumping meta.revision inside the transaction."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'revision'")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def exec_many(conn: sqlite3.Connection, sql: str) -> None:
    """Run several statements without executescript (which would COMMIT our transaction).

    Splits on ';', so migration SQL must not contain ';' inside literals or comments.
    """
    for stmt in sql.split(";"):
        if stmt.strip():
            conn.execute(stmt)


def _v1(conn: sqlite3.Connection) -> None:
    exec_many(conn, """
    INSERT OR IGNORE INTO meta(key, value) VALUES ('revision', '0');
    CREATE TABLE calendars(
        id            TEXT PRIMARY KEY,
        account_id    TEXT,
        remote_href   TEXT,
        remote_name   TEXT NOT NULL,
        remote_color  TEXT,
        user_name     TEXT,
        user_color    TEXT,
        hidden        INTEGER NOT NULL DEFAULT 0,
        sort_order    INTEGER NOT NULL DEFAULT 0,
        ctag          TEXT,
        sync_token    TEXT,
        window_start  INTEGER,
        window_end    INTEGER
    );
    CREATE INDEX calendars_account ON calendars(account_id);
    CREATE TABLE events(
        id            INTEGER PRIMARY KEY,
        calendar_id   TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
        uid           TEXT NOT NULL,
        recurrence_id TEXT NOT NULL DEFAULT '',
        summary       TEXT NOT NULL DEFAULT '',
        location      TEXT NOT NULL DEFAULT '',
        description   TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'CONFIRMED',
        all_day       INTEGER NOT NULL,
        start_utc     INTEGER,
        end_utc       INTEGER,
        start_date    TEXT,
        end_date      TEXT,
        tzid          TEXT,
        UNIQUE(calendar_id, uid, recurrence_id),
        CHECK ((all_day = 0 AND start_utc IS NOT NULL AND end_utc IS NOT NULL)
            OR (all_day = 1 AND start_date IS NOT NULL AND end_date IS NOT NULL))
    );
    CREATE INDEX events_timed  ON events(start_utc, end_utc) WHERE all_day = 0;
    CREATE INDEX events_allday ON events(start_date, end_date) WHERE all_day = 1;
    CREATE INDEX events_cal    ON events(calendar_id)
    """)


# Append-only: index 0 is schema version 1.
MIGRATIONS = [_v1]


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row and int(row[0]) >= len(MIGRATIONS):
        return
    for version in range(1, len(MIGRATIONS) + 1):
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Re-read under the lock: another process may have migrated already.
            row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row and int(row[0]) >= version:
                conn.execute("COMMIT")
                continue
            log.info("migrating database to schema v%d", version)
            MIGRATIONS[version - 1](conn)
            conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(version),))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row[0]) if row else 0


def _prune_corrupt_sets(path: Path, keep: int = 2) -> None:
    stamps = sorted({int(p.name.split(".corrupt-")[1].split("-")[0])
                     for p in path.parent.glob(path.name + ".corrupt-*")
                     if p.name.split(".corrupt-")[1].split("-")[0].isdigit()})
    for ts in stamps[:-keep] if keep else stamps:
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(f"{path}.corrupt-{ts}{suffix}").unlink()
            except FileNotFoundError:
                pass


def recover_if_corrupt(path: Path | str | None = None) -> bool:
    """PRAGMA quick_check; on failure move the database aside (keep the 2 newest sets).

    Returns True if the database was reset (a fresh one is created on next connect()).
    Call before the store is opened for real (US-12 D8).
    """
    path = Path(path) if path else default_path()
    if not path.exists():
        return False
    ok = False
    try:
        conn = sqlite3.connect(str(path), timeout=5.0)
        try:
            ok = conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        ok = False
    if ok:
        return False
    ts = int(time.time())
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            os.replace(p, Path(f"{path}.corrupt-{ts}{suffix}"))
    _prune_corrupt_sets(path, keep=2)
    log.error("event database failed integrity check; moved aside as %s.corrupt-%d", path.name, ts)
    return True
