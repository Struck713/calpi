"""The sync process: `python3 -m calpi.sync.worker` (US-16). No gi imports.

Protocol: exactly one stdout line, `CALPI_SYNC_RESULT {json}`; every log line goes to stderr.
Exit code: 0 finished (even with account errors), 3 another sync holds the lock, 1 crashed.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable

if __package__ in (None, ""):                       # run as a plain script: make `calpi` importable
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from calpi import paths
from calpi.data import timeutil
from calpi.data.accounts import list_accounts
from calpi.data.settings_store import K_SYNC_WINDOW_BACK, K_SYNC_WINDOW_FORWARD, K_TIMEZONE
from calpi.sync.fetch import AccountResult, compute_window, sync_account

log = logging.getLogger("calpi.sync.worker")

RESULT_PREFIX = "CALPI_SYNC_RESULT "
LOCK_NAME = "sync.lock"
EXIT_OK, EXIT_CRASHED, EXIT_BUSY = 0, 1, 3


@dataclass
class Deps:
    """Factories, so tests can inject a temporary state directory and a fake transport."""
    settings: Callable[[], object]
    store: Callable[[], object]
    credentials: Callable[[], object]
    client: Callable[[object], object] = lambda acc: None      # None -> sync_account builds its own

    @classmethod
    def default(cls) -> "Deps":
        def settings():
            from calpi.data.settings_store import SettingsStore
            return SettingsStore()

        def store():
            from calpi.data.event_store import EventStore
            return EventStore()

        def creds():
            from calpi.data.credentials import CredentialStore
            return CredentialStore()
        return cls(settings, store, creds)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _err(v) -> str | None:
    return getattr(v, "value", v)


def _serialize(res: AccountResult) -> dict:
    return {"account_id": res.account_id, "error": _err(res.error), "detail": res.detail,
            "retry_after": None,
            "calendars": [{"calendar_id": c.calendar_id, "name": c.name, "status": c.status,
                           "events": c.events, "error": _err(c.error), "detail": c.detail,
                           "duration_ms": c.duration_ms,
                           "parse_errors": c.stats.parse_errors if c.stats else 0}
                          for c in res.calendars]}


def _account_error(acc_id: str, code: str, detail: str) -> dict:
    return {"account_id": acc_id, "error": code, "detail": detail, "retry_after": None, "calendars": []}


def _parse_range(s: str | None) -> tuple[date, date] | None:
    if not s:
        return None
    a, b = s.split(":")
    return date.fromisoformat(a), date.fromisoformat(b)


def _record_status(store, acc: dict, now: int) -> None:
    """US-18: persist one account's outcome (own small transactions; never fails the sync)."""
    from calpi.data import sync_status
    conn, aid = store.conn, acc["account_id"]
    try:
        if acc.get("error"):
            sync_status.record_account(conn, aid, at=now, error=acc["error"], detail=acc.get("detail", ""))
            for cal in store.calendars_for_account(aid):
                sync_status.record_calendar(conn, cal.id, at=now, status="error", error=acc["error"],
                                            detail=acc.get("detail", ""), inherited=True)
            return
        sync_status.record_account(conn, aid, at=now)
        for c in acc.get("calendars", []):
            sync_status.record_calendar(
                conn, c["calendar_id"], at=now, status=c["status"], error=c.get("error"),
                detail=c.get("detail", ""), events=None if c["status"] == "unchanged" else c.get("events"),
                duration_ms=c.get("duration_ms"), parse_errors=c.get("parse_errors", 0))
    except sqlite3.Error as e:
        log.warning("could not record sync status for %s: %s", aid, e)


def _record_run(store, out: list, reason: str, started: datetime, duration_ms: int, changed: bool) -> None:
    from calpi.data import sync_status
    failed = sum(1 for a in out if a.get("error") or any(c.get("error") for c in a.get("calendars", [])))
    try:
        sync_status.record_run(store.conn, started_at=int(started.timestamp()),
                               finished_at=int(time.time()), reason=reason, status="done",
                               duration_ms=duration_ms, ok=len(out) - failed, failed=failed,
                               changed=changed)
    except sqlite3.Error as e:
        log.warning("could not record sync run: %s", e)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="calpi.sync.worker")
    p.add_argument("--reason", default="manual")
    p.add_argument("--force", action="store_true")
    p.add_argument("--extra-range", type=_parse_range, default=None, metavar="YYYY-MM-DD:YYYY-MM-DD")
    p.add_argument("--account", default=None)
    return p.parse_args(argv)


def run(args, deps: Deps) -> dict:
    settings = deps.settings()
    timeutil.set_display_tz(settings.get(K_TIMEZONE))
    tz = timeutil.display_tz()
    store, creds = deps.store(), deps.credentials()
    try:
        window = compute_window(timeutil.today(), tz, settings.get(K_SYNC_WINDOW_BACK),
                                settings.get(K_SYNC_WINDOW_FORWARD), extra=args.extra_range)
        t0, started = time.monotonic(), datetime.now(timezone.utc)
        rev0 = store.revision()
        unreadable = creds.status() == "unreadable"
        out = []
        for acc in list_accounts(settings):
            if args.account and acc.id != args.account:
                continue
            secret = None if unreadable else creds.get(acc.id)
            if secret is None:                                     # D5: no network call
                out.append(_account_error(acc.id, "CREDENTIALS_UNREADABLE", "no readable credentials"))
                _record_status(store, out[-1], int(time.time()))
                continue
            out.append(_serialize(sync_account(acc, secret, store, window, force=args.force,
                                               client=deps.client(acc), tz=tz)))
            _record_status(store, out[-1], int(time.time()))
        rev1 = store.revision()
        _record_run(store, out, args.reason, started, int((time.monotonic() - t0) * 1000), rev1 != rev0)
    finally:
        try:
            from calpi.data import db
            db.checkpoint_if_large(store.conn)             # US-37: keep the WAL bounded
        except Exception:
            log.warning("wal checkpoint skipped", exc_info=True)
        store.close()
    return {"v": 1, "status": "done", "reason": args.reason, "started": _utc(started),
            "finished": _utc(datetime.now(timezone.utc)),
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "changed": rev1 != rev0, "revision_before": rev0, "revision_after": rev1,
            "window": [_utc(window[0]), _utc(window[1])], "accounts": out}


def _acquire_lock():
    f = open(paths.runtime_dir() / LOCK_NAME, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def main(argv=None, deps: Deps | None = None) -> int:
    real_out = sys.stdout
    sys.stdout = sys.stderr                     # stray prints can never corrupt the protocol line

    def emit(obj: dict) -> None:
        real_out.write(RESULT_PREFIX + json.dumps(obj, separators=(",", ":")) + "\n")
        real_out.flush()

    from calpi.logging_setup import setup_logging
    from calpi.data.credentials import install_log_redaction
    setup_logging(stream=sys.stderr)
    install_log_redaction()                     # US-13
    args = parse_args(argv)
    lock = _acquire_lock()
    if lock is None:
        log.info("another sync holds the lock")
        emit({"v": 1, "status": "busy", "reason": args.reason})
        return EXIT_BUSY
    try:
        emit(run(args, deps or Deps.default()))
        return EXIT_OK
    except sqlite3.DatabaseError as e:          # US-12: a damaged database ends the process
        log.error("sync worker: database error, exiting: %s", e)
        emit({"v": 1, "status": "crashed", "reason": args.reason, "detail": "DatabaseError"})
        return EXIT_CRASHED
    except Exception as e:
        log.exception("sync worker crashed")
        emit({"v": 1, "status": "crashed", "reason": args.reason, "detail": type(e).__name__})
        return EXIT_CRASHED
    finally:
        lock.close()
        sys.stdout = real_out


if __name__ == "__main__":
    raise SystemExit(main())
