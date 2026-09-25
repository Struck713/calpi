"""Pure agenda building (US-40): upcoming events grouped by day. No gi imports.

Horizon is [now, today + days) in the display zone. Events that already ended are dropped;
ongoing timed events come first under today; multi-day events appear once (on their first
visible day) with a range text; the total is capped.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from calpi.data import formatting
from calpi.data.layout import covered_days
from calpi.data.models import Event

AGENDA_DAYS = 30
AGENDA_MAX_ITEMS = 200

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class AgendaItem:
    event: Event
    day: date
    kind: str                 # "ongoing" | "upcoming" | "allday" | "multiday"
    time_text: str
    range_text: str | None
    is_next: bool = False


@dataclass(frozen=True)
class Agenda:
    groups: list[tuple[date, list[AgendaItem]]]
    more_after: date | None = None      # set when the cap dropped items after this day


def heading_text(day: date, today: date) -> str:
    """'Today' / 'Tomorrow' / 'Thursday 17 September'."""
    word = formatting.relative_day_word(day, today)
    if word in ("Today", "Tomorrow"):
        return word
    return f"{_WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]}"


def _short(day: date, with_month: bool) -> str:
    text = f"{_WEEKDAYS[day.weekday()][:3]} {day.day}"
    return f"{text} {_MONTHS[day.month - 1][:3]}" if with_month else text


def _range_text(first: date, last: date, shown: date) -> str:
    if first < shown:
        return f"until {_short(last, last.month != shown.month)}"
    month = first.month != last.month
    return f"{_short(first, month)} – {_short(last, True if month else last.month != shown.month)}"


def build_agenda_full(events: list[Event], now: datetime, tz: ZoneInfo,
                      days: int = AGENDA_DAYS, cap: int = AGENDA_MAX_ITEMS) -> Agenda:
    now = now.astimezone(tz)
    today = now.date()
    horizon = today + timedelta(days=days)
    rows: list[tuple[tuple, AgendaItem]] = []
    for e in events:
        first, last = covered_days(e, tz)
        if last < today or first >= horizon:
            continue
        day = max(first, today)
        multi = last > first
        rng = _range_text(first, last, day) if multi else None
        if e.all_day:
            kind, order = ("multiday" if multi else "allday"), (1, 0)
        else:
            if e.end > e.start:
                if e.end <= now:
                    continue
            elif e.start < now:
                continue
            if e.start <= now:
                kind, order = "ongoing", (0, e.start.timestamp())
            else:
                kind, order = ("multiday" if multi else "upcoming"), (2, e.start.timestamp())
        rows.append(((day, order, e.summary.casefold()),
                     AgendaItem(e, day, kind, formatting.time_range_text(e, day, tz), rng)))
    rows.sort(key=lambda r: r[0])
    more_after = None
    if len(rows) > cap:
        more_after = rows[cap - 1][1].day
        rows = rows[:cap]
    items = [r[1] for r in rows]
    for i, it in enumerate(items):
        if it.kind in ("upcoming", "multiday") and not it.event.all_day:
            items[i] = AgendaItem(it.event, it.day, it.kind, it.time_text, it.range_text, True)
            break
    groups: list[tuple[date, list[AgendaItem]]] = []
    for it in items:
        if groups and groups[-1][0] == it.day:
            groups[-1][1].append(it)
        else:
            groups.append((it.day, [it]))
    return Agenda(groups, more_after)


def build_agenda(events: list[Event], now: datetime, tz: ZoneInfo,
                 days: int = AGENDA_DAYS, cap: int = AGENDA_MAX_ITEMS
                 ) -> list[tuple[date, list[AgendaItem]]]:
    return build_agenda_full(events, now, tz, days, cap).groups
