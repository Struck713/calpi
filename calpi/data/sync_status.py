"""Persistent sync status (US-18). No gi imports.

Written by the sync process (record_*), read by the UI process (snapshot). Data only: plain-language
text for these codes belongs to US-38. Times are Unix seconds UTC in the database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from calpi.data import db

DETAIL_MAX = 300
RUNS_KEEP = 100

_AUTH_RE = re.compile(r"(?i)(authorization|proxy-authorization)\s*[:=]\s*\S+(\s+\S+)?")
_SCHEME_RE = re.compile(r"(?i)\b(basic|bearer)\s+[A-Za-z0-9+/=._~-]{6,}")


def sanitize_detail(text) -> str:
    """Collapse whitespace, drop Authorization headers, redact registered secrets, cap length."""
    from calpi.data.credentials import _REDACTOR
    t = " ".join(str(text or "").split())
    t = _AUTH_RE.sub(r"\1: ***", t)
    t = _SCHEME_RE.sub(r"\1 ***", t)
    t = _REDACTOR.redact(t)
    return t[:DETAIL_MAX]


def _dt(v) -> datetime | None:
    return datetime.fromtimestamp(v, timezone.utc) if v is not None else None


def _code(v) -> str | None:
    v = getattr(v, "value", v)
    return str(v) if v else None


@dataclass(frozen=True)
class AccountStatus:
    account_id: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None
    last_error_detail: str | None
    last_error_at: datetime | None
    consecutive_failures: int


@dataclass(frozen=True)
class CalendarStatus:
    calendar_id: str
    account_id: str | None
    name: str
    hidden: bool
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_status: str | None            # ok | unchanged | error
    last_error_code: str | None
    last_error_detail: str | None
    last_error_at: datetime | None
    inherited: bool
    consecutive_failures: int
    last_event_count: int | None
    last_duration_ms: int | None
    last_parse_errors: int


@dataclass(frozen=True)
class RunRecord:
    id: int
    started_at: datetime
    finished_at: datetime
    reason: str | None
    status: str | None
    duration_ms: int | None
    accounts_ok: int
    accounts_failed: int
    changed: bool


@dataclass(frozen=True)
class StatusSnapshot:
    accounts: tuple[AccountStatus, ...] = ()
    calendars: tuple[CalendarStatus, ...] = ()
    runs: tuple[RunRecord, ...] = ()          # newest first

    def account(self, account_id: str) -> AccountStatus | None:
        return next((a for a in self.accounts if a.account_id == account_id), None)

    def calendars_of(self, account_id: str) -> tuple[CalendarStatus, ...]:
        return tuple(c for c in self.calendars if c.account_id == account_id)

    def last_run(self) -> RunRecord | None:
        return self.runs[0] if self.runs else None


# --- writes (sync process) ------------------------------------------------------------------

def record_account(conn, account_id: str, *, at: int, error=None, detail: str = "") -> None:
    code = _code(error)
    with db.write_txn(conn, bump_revision=False):
        conn.execute("""
            INSERT INTO account_sync_status(account_id, last_attempt_at, last_success_at,
                last_error_code, last_error_detail, last_error_at, consecutive_failures)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
              last_attempt_at = excluded.last_attempt_at,
              last_success_at = COALESCE(excluded.last_success_at, account_sync_status.last_success_at),
              last_error_code = excluded.last_error_code,
              last_error_detail = excluded.last_error_detail,
              last_error_at = excluded.last_error_at,
              consecutive_failures = CASE WHEN excluded.last_error_code IS NULL THEN 0
                                     ELSE account_sync_status.consecutive_failures + 1 END
            """, (account_id, at, None if code else at, code,
                  sanitize_detail(detail) if code else None, at if code else None,
                  1 if code else 0))


def record_calendar(conn, calendar_id: str, *, at: int, status: str, error=None, detail: str = "",
                    events: int | None = None, duration_ms: int | None = None,
                    parse_errors: int = 0, inherited: bool = False) -> None:
    """status: ok | unchanged | error. ok and unchanged both count as success."""
    code = _code(error)
    if status == "error" and not code:
        code = "UNKNOWN"
    failed = bool(code) or status == "error"
    with db.write_txn(conn, bump_revision=False):
        conn.execute("""
            INSERT INTO calendar_sync_status(calendar_id, last_attempt_at, last_success_at,
                last_status, last_error_code, last_error_detail, last_error_at, inherited,
                consecutive_failures, last_event_count, last_duration_ms, last_parse_errors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(calendar_id) DO UPDATE SET
              last_attempt_at = excluded.last_attempt_at,
              last_success_at = COALESCE(excluded.last_success_at, calendar_sync_status.last_success_at),
              last_status = excluded.last_status,
              last_error_code = excluded.last_error_code,
              last_error_detail = excluded.last_error_detail,
              last_error_at = excluded.last_error_at,
              inherited = excluded.inherited,
              consecutive_failures = CASE WHEN excluded.last_error_code IS NULL THEN 0
                                     ELSE calendar_sync_status.consecutive_failures + 1 END,
              last_event_count = COALESCE(excluded.last_event_count, calendar_sync_status.last_event_count),
              last_duration_ms = COALESCE(excluded.last_duration_ms, calendar_sync_status.last_duration_ms),
              last_parse_errors = excluded.last_parse_errors
            """, (calendar_id, at, None if failed else at, status,
                  code if failed else None, sanitize_detail(detail) if failed else None,
                  at if failed else None, 1 if (inherited and failed) else 0,
                  1 if failed else 0, events, duration_ms, parse_errors))


def record_run(conn, *, started_at: int, finished_at: int, reason: str, status: str,
               duration_ms: int, ok: int, failed: int, changed: bool, keep: int = RUNS_KEEP) -> None:
    with db.write_txn(conn, bump_revision=False):
        conn.execute("""INSERT INTO sync_runs(started_at, finished_at, reason, status, duration_ms,
                        accounts_ok, accounts_failed, changed) VALUES (?,?,?,?,?,?,?,?)""",
                     (started_at, finished_at, reason, status, duration_ms, ok, failed, int(bool(changed))))
        conn.execute("DELETE FROM sync_runs WHERE id NOT IN "
                     "(SELECT id FROM sync_runs ORDER BY id DESC LIMIT ?)", (keep,))


def forget_account(conn, account_id: str) -> None:
    """Delete the account's status row (calendar rows go with their calendars, by cascade)."""
    with db.write_txn(conn, bump_revision=False):
        conn.execute("DELETE FROM account_sync_status WHERE account_id = ?", (account_id,))


# --- reads (UI process) ---------------------------------------------------------------------

def snapshot(conn, runs: int = 20) -> StatusSnapshot:
    accounts = tuple(AccountStatus(r[0], _dt(r[1]), _dt(r[2]), r[3], r[4], _dt(r[5]), r[6])
                     for r in conn.execute(
        "SELECT account_id, last_attempt_at, last_success_at, last_error_code, last_error_detail, "
        "last_error_at, consecutive_failures FROM account_sync_status ORDER BY account_id"))
    cals = tuple(CalendarStatus(
        r[0], r[1], r[2], bool(r[3]), _dt(r[4]), _dt(r[5]), r[6], r[7], r[8], _dt(r[9]), bool(r[10]),
        r[11], r[12], r[13], r[14] or 0)
        for r in conn.execute(
        "SELECT s.calendar_id, c.account_id, COALESCE(c.user_name, c.remote_name), c.hidden, "
        "s.last_attempt_at, s.last_success_at, s.last_status, s.last_error_code, s.last_error_detail, "
        "s.last_error_at, s.inherited, s.consecutive_failures, s.last_event_count, "
        "s.last_duration_ms, s.last_parse_errors "
        "FROM calendar_sync_status s JOIN calendars c ON c.id = s.calendar_id "
        "ORDER BY c.account_id, c.sort_order, COALESCE(c.user_name, c.remote_name), s.calendar_id"))
    rr = tuple(RunRecord(r[0], _dt(r[1]), _dt(r[2]), r[3], r[4], r[5], r[6] or 0, r[7] or 0, bool(r[8]))
               for r in conn.execute(
        "SELECT id, started_at, finished_at, reason, status, duration_ms, accounts_ok, "
        "accounts_failed, changed FROM sync_runs ORDER BY id DESC LIMIT ?", (runs,)))
    return StatusSnapshot(accounts, cals, rr)
