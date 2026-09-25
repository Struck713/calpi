"""Deterministic sample calendars/events for development, plus a CLI loader. No gi imports.

    python3 -m calpi.data.sample_data --load [--clear] [--state-dir DIR] [--today YYYY-MM-DD] [--scale N]
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from calpi.data import timeutil
from calpi.data.event_store import EventStore
from calpi.data.models import Calendar, Event

log = logging.getLogger("calpi.sample_data")

FAMILY, WORK, SCHOOL, ARCHIVE = "sample:Family", "sample:Work", "sample:School", "sample:Archive"


def sample_calendars() -> list[Calendar]:
    return [
        Calendar(FAMILY, "Family", remote_color="#4f9dff", sort_order=0),
        Calendar(WORK, "Work", remote_color="#3ecf8e", sort_order=1),
        Calendar(SCHOOL, "School", remote_color="#ffb020", sort_order=2),
        Calendar(ARCHIVE, "Archive", remote_color="#9aa4ae", hidden=True, sort_order=3),
    ]


def sample_events(today: date, tz: ZoneInfo) -> list[Event]:
    out: list[Event] = []
    n = 0
    tzid = getattr(tz, "key", None)

    def timed(cal, summary, day, start: time, end_day, end: time, **kw):
        nonlocal n
        n += 1
        s = datetime.combine(day, start, tz).astimezone(timezone.utc)
        e = datetime.combine(end_day, end, tz).astimezone(timezone.utc)
        out.append(Event(cal, f"sample-{n}@calpi", summary, False, s, e, tzid=tzid, **kw))

    def allday(cal, summary, day, days=1, **kw):
        nonlocal n
        n += 1
        out.append(Event(cal, f"sample-{n}@calpi", summary, True, day, day + timedelta(days=days), **kw))

    d = timedelta(days=1)
    # Several timed events today, plus an all-day event
    timed(FAMILY, "Breakfast with grandparents", today, time(8, 0), today, time(9, 0))
    timed(WORK, "Team stand-up", today, time(9, 30), today, time(10, 0))
    timed(WORK, "Project review", today, time(14, 0), today, time(15, 30), location="Room 4")
    timed(SCHOOL, "Parent-teacher meeting", today, time(17, 30), today, time(18, 15), status="TENTATIVE")
    allday(FAMILY, "Emma's birthday", today)
    # 3-day all-day event crossing a week boundary: starts on the coming Saturday (or today)
    sat = today + timedelta(days=(5 - today.weekday()) % 7)
    allday(SCHOOL, "School trip", sat, 3)
    # 2-day timed event: Friday 18:00 -> Sunday 12:00
    fri = today + timedelta(days=(4 - today.weekday()) % 7)
    timed(FAMILY, "Weekend at the lake", fri, time(18, 0), fri + 2 * d, time(12, 0))
    # Crosses midnight
    timed(FAMILY, "Movie night", today + d, time(22, 30), today + 2 * d, time(1, 0))
    # A day with 9 events (overflow)
    busy = today + 2 * d
    for i in range(9):
        cal = (WORK, FAMILY, SCHOOL)[i % 3]
        timed(cal, f"Busy day item {i + 1}", busy, time(7 + i, 0), busy, time(7 + i, 45))
    # Crosses the month boundary
    first_next = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    last = first_next - d
    timed(WORK, "Release night", last, time(20, 0), first_next, time(2, 0))
    allday(FAMILY, "Month-end holiday", last, 2)
    # Very long title
    timed(WORK, "Quarterly planning workshop with the extended leadership team and all "
                "regional partners, including catering and travel logistics review",
          today + 3 * d, time(11, 0), today + 3 * d, time(12, 30))
    # Overlapping trio + one early event for the week view (US-39)
    ov = today + 4 * d
    timed(WORK, "Design review", ov, time(9, 0), ov, time(10, 0))
    timed(FAMILY, "Dentist (kids)", ov, time(9, 30), ov, time(11, 0))
    timed(SCHOOL, "Pick-up", ov, time(10, 0), ov, time(10, 30))
    timed(WORK, "Early flight check-in", ov, time(6, 0), ov, time(6, 30))
    # Previous and next months
    prev = today.replace(day=1) - timedelta(days=10)
    timed(FAMILY, "Dentist", prev, time(16, 0), prev, time(16, 45))
    nxt = first_next + timedelta(days=9)
    timed(WORK, "Offsite", nxt, time(10, 0), nxt, time(16, 0))
    allday(SCHOOL, "Sports day", first_next + timedelta(days=14))
    # Hidden calendar: must never show
    timed(ARCHIVE, "Old archived meeting", today, time(12, 0), today, time(13, 0))
    allday(ARCHIVE, "Archived all-day", today + d)
    # Weekly recurring (pre-expanded) for +-3 months: Wednesdays 18:00
    wed = today + timedelta(days=(2 - today.weekday()) % 7)
    for k in range(-13, 14):
        day = wed + timedelta(weeks=k)
        orig = datetime.combine(day, time(18, 0), tz)
        s = orig.astimezone(timezone.utc)
        out.append(Event(FAMILY, "sample-weekly@calpi", "Football practice", False, s,
                         s + timedelta(hours=1, minutes=30), recurrence_id=orig.isoformat(),
                         tzid=tzid))
    return out


def scaled_events(today: date, tz: ZoneInfo, scale: int = 1) -> list[Event]:
    """The sample events repeated `scale` times (US-36 stress data). Copy k is shifted by 3k days and
    20k minutes, with a suffixed uid and title, so days get busier but stay plausible."""
    base = sample_events(today, tz)
    out = list(base)
    for k in range(1, max(1, scale)):
        dd, dm = timedelta(days=3 * k), timedelta(minutes=20 * k)
        for e in base:
            shift = dd if e.all_day else dd + dm
            out.append(dataclasses.replace(
                e, uid=f"{e.uid[:-len('@calpi')]}-x{k}@calpi", summary=f"{e.summary} #{k}",
                start=e.start + shift, end=e.end + shift,
                recurrence_id=(e.recurrence_id + f"+{k}") if e.recurrence_id else ""))
    return out


def load(store: EventStore, today: date, tz: ZoneInfo, clear: bool = False, scale: int = 1) -> int:
    if clear:
        store.delete_sample_data()
    for c in sample_calendars():
        store.upsert_calendar(c)
    by_cal: dict[str, list[Event]] = defaultdict(list)
    for e in scaled_events(today, tz, scale):
        by_cal[e.calendar_id].append(e)
    return sum(store.replace_calendar_events(cid, evs) for cid, evs in by_cal.items())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="calpi.data.sample_data")
    p.add_argument("--load", action="store_true", required=True)
    p.add_argument("--clear", action="store_true")
    p.add_argument("--state-dir")
    p.add_argument("--today", help="YYYY-MM-DD (default: real today)")
    p.add_argument("--scale", type=int, default=1, metavar="N",
                   help="generate about N times as many events (stress data, US-36)")
    a = p.parse_args(argv)
    from calpi import paths
    paths.set_state_dir_override(a.state_dir)
    tz = timeutil.display_tz()
    today = date.fromisoformat(a.today) if a.today else timeutil.today()
    store = EventStore()
    n = load(store, today, tz, clear=a.clear, scale=a.scale)
    print(f"loaded {n} sample events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
