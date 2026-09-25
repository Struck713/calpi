"""EventStore: the hand-off point between syncing (writes) and display (reads). No gi imports."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from calpi.data import db
from calpi.data.models import Calendar, Event

log = logging.getLogger("calpi.event_store")

_UNSET = object()
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")

_EVENT_COLS = ("calendar_id, uid, recurrence_id, summary, location, description, status, "
               "all_day, start_utc, end_utc, start_date, end_date, tzid")


def _norm_color(c: str | None) -> str | None:
    if not c:
        return None
    m = _HEX.match(c.strip())
    return "#" + m.group(1).lower() if m else None


def _row_to_calendar(r) -> Calendar:
    return Calendar(id=r["id"], remote_name=r["remote_name"], account_id=r["account_id"],
                    remote_href=r["remote_href"], remote_color=r["remote_color"],
                    user_name=r["user_name"], user_color=r["user_color"],
                    hidden=bool(r["hidden"]), sort_order=r["sort_order"])


def _row_to_event(r) -> Event:
    if r["all_day"]:
        start = date.fromisoformat(r["start_date"])
        end = date.fromisoformat(r["end_date"])
    else:
        start = datetime.fromtimestamp(r["start_utc"], tz=timezone.utc)
        end = datetime.fromtimestamp(r["end_utc"], tz=timezone.utc)
    return Event(calendar_id=r["calendar_id"], uid=r["uid"], recurrence_id=r["recurrence_id"],
                 summary=r["summary"], location=r["location"], description=r["description"],
                 status=r["status"], all_day=bool(r["all_day"]), start=start, end=end,
                 tzid=r["tzid"])


def _event_to_row(e: Event, calendar_id: str | None = None) -> tuple:
    if e.all_day:
        times = (None, None, e.start.isoformat(), e.end.isoformat())
    else:
        times = (int(e.start.timestamp()), int(e.end.timestamp()), None, None)
    return (calendar_id or e.calendar_id, e.uid, e.recurrence_id, e.summary, e.location, e.description,
            e.status, 1 if e.all_day else 0, *times, e.tzid)


def _sort_key(e: Event, cal_sort: int):
    if e.all_day:
        return (0, -(e.end - e.start).days, cal_sort, e.summary.casefold())
    return (1, int(e.start.timestamp()), -int((e.end - e.start).total_seconds()),
            cal_sort, e.summary.casefold())


class EventStore:
    def __init__(self, path: Path | str | None = None):
        self.conn = db.connect(path)

    # --- calendars ---
    def list_calendars(self, include_hidden: bool = True) -> list[Calendar]:
        sql = "SELECT * FROM calendars"
        if not include_hidden:
            sql += " WHERE hidden = 0"
        sql += " ORDER BY sort_order, COALESCE(user_name, remote_name) COLLATE NOCASE, id"
        return [_row_to_calendar(r) for r in self.conn.execute(sql)]

    def get_calendar(self, calendar_id: str) -> Calendar | None:
        r = self.conn.execute("SELECT * FROM calendars WHERE id = ?", (calendar_id,)).fetchone()
        return _row_to_calendar(r) if r else None

    def upsert_calendar(self, cal: Calendar) -> None:
        """Insert, or update remote_* only. Never touches user_* / hidden / sort_order of existing rows."""
        with db.write_txn(self.conn):
            self.conn.execute(
                "INSERT INTO calendars(id, account_id, remote_href, remote_name, remote_color,"
                " user_name, user_color, hidden, sort_order) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET remote_name=excluded.remote_name,"
                " remote_color=excluded.remote_color, remote_href=excluded.remote_href,"
                " account_id=excluded.account_id",
                (cal.id, cal.account_id, cal.remote_href, cal.remote_name,
                 _norm_color(cal.remote_color), cal.user_name, _norm_color(cal.user_color),
                 1 if cal.hidden else 0, cal.sort_order))

    def set_calendar_overrides(self, calendar_id: str, *, user_name=_UNSET, user_color=_UNSET,
                               hidden=_UNSET, sort_order=_UNSET) -> None:
        """Only the keyword arguments actually passed are changed (None clears a name/colour)."""
        sets, args = [], []
        if user_name is not _UNSET:
            sets.append("user_name = ?"); args.append(user_name or None)
        if user_color is not _UNSET:
            sets.append("user_color = ?"); args.append(_norm_color(user_color))
        if hidden is not _UNSET:
            sets.append("hidden = ?"); args.append(1 if hidden else 0)
        if sort_order is not _UNSET:
            sets.append("sort_order = ?"); args.append(int(sort_order))
        if not sets:
            return
        with db.write_txn(self.conn):
            self.conn.execute(f"UPDATE calendars SET {', '.join(sets)} WHERE id = ?",
                              (*args, calendar_id))

    def delete_calendar(self, calendar_id: str) -> None:
        with db.write_txn(self.conn):
            self.conn.execute("DELETE FROM calendars WHERE id = ?", (calendar_id,))

    def delete_calendars_for_account(self, account_id: str) -> None:
        with db.write_txn(self.conn):
            self.conn.execute("DELETE FROM calendars WHERE account_id = ?", (account_id,))

    def delete_sample_data(self) -> None:
        with db.write_txn(self.conn):
            self.conn.execute("DELETE FROM calendars WHERE id LIKE 'sample:%'")

    # --- events ---
    def replace_calendar_events(self, calendar_id: str, events: Iterable[Event],
                                window: tuple[datetime, datetime] | None = None) -> int:
        """Atomically replace every occurrence of a calendar. Returns the number stored.

        Duplicate (uid, recurrence_id) identities: the last one wins.
        """
        with db.write_txn(self.conn):
            unique: dict[tuple[str, str], Event] = {}
            total = 0
            for e in events:            # a generator may raise midway: the txn rolls back
                total += 1
                unique[(e.uid, e.recurrence_id)] = e
            if total != len(unique):
                log.debug("dropped %d duplicate occurrences for %s", total - len(unique), calendar_id)
            self.conn.execute("DELETE FROM events WHERE calendar_id = ?", (calendar_id,))
            self.conn.executemany(
                f"INSERT INTO events({_EVENT_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [_event_to_row(e, calendar_id) for e in unique.values()])
            if window:
                self.conn.execute("UPDATE calendars SET window_start=?, window_end=? WHERE id=?",
                                  (int(window[0].timestamp()), int(window[1].timestamp()), calendar_id))
        return len(unique)

    def events_for_days(self, first_day: date, end_day: date, tz: ZoneInfo,
                        include_hidden: bool = False) -> list[Event]:
        """Occurrences overlapping local days [first_day, end_day) in tz, sorted per D6."""
        start_utc = int(datetime.combine(first_day, time.min, tz).timestamp())
        end_utc = int(datetime.combine(end_day, time.min, tz).timestamp())
        rows = self.conn.execute(
            "SELECT e.*, c.sort_order AS cal_sort FROM events e JOIN calendars c ON c.id = e.calendar_id "
            "WHERE (:inc OR c.hidden = 0) AND ("
            " (e.all_day = 0 AND e.start_utc < :end_utc AND (e.end_utc > :start_utc"
            "   OR (e.end_utc = e.start_utc AND e.start_utc >= :start_utc)))"
            " OR (e.all_day = 1 AND e.start_date < :end_date AND e.end_date > :start_date))",
            {"inc": 1 if include_hidden else 0, "start_utc": start_utc, "end_utc": end_utc,
             "start_date": first_day.isoformat(), "end_date": end_day.isoformat()}).fetchall()
        out = [(_row_to_event(r), r["cal_sort"]) for r in rows]
        out.sort(key=lambda p: _sort_key(*p))
        return [e for e, _ in out]

    def count_events(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    # --- housekeeping ---
    def revision(self) -> int:
        return int(self.conn.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])

    def integrity_ok(self) -> bool:
        try:
            return self.conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        except Exception:
            log.exception("integrity check failed")
            return False

    def close(self) -> None:
        self.conn.close()
