"""Pure month-grid layout for one week row (lanes, capacity, '+N more'). No gi imports.

All layout decisions live here; the widgets only place what this module computes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from calpi.data.models import Event


@dataclass(frozen=True)
class Bar:
    event: Event
    start_col: int          # 0..6 within the week
    end_col: int            # inclusive
    continues_before: bool  # event started before this week
    continues_after: bool
    lane: int = -1


@dataclass(frozen=True)
class Line:
    event: Event
    col: int
    local_start: datetime   # display zone, for the time label


@dataclass
class DayLayout:
    placed_lines: list[tuple[int, Line]] = field(default_factory=list)   # (slot, line)
    hidden_count: int = 0            # N of "+N more" (0 = no overflow label)
    more_slot: int | None = None     # slot of the "+N more" label
    total: int = 0                   # all items covering the day
    visible_bars: int = 0


@dataclass
class WeekLayout:
    bars: list[tuple[Bar, int, int]]   # (bar, first_col, last_col) segments to draw
    days: list[DayLayout]              # 7 entries


def covered_days(e: Event, tz: ZoneInfo) -> tuple[date, date]:
    """Inclusive (first_day, last_day) the event occupies in the display zone (D2)."""
    if e.all_day:
        return e.start, max(e.start, e.end - timedelta(days=1))
    s = e.start.astimezone(tz)
    if e.end > e.start:
        last = (e.end - timedelta(microseconds=1)).astimezone(tz).date()
    else:
        last = s.date()
    return s.date(), max(s.date(), last)


def _assign_lanes(bars: list[Bar]) -> list[Bar]:
    order = sorted(range(len(bars)),
                   key=lambda i: (bars[i].start_col, -(bars[i].end_col - bars[i].start_col), i))
    lanes: list[list[tuple[int, int]]] = []     # per lane: occupied (start, end) spans
    out: dict[int, Bar] = {}
    for i in order:
        b = bars[i]
        for lane, spans in enumerate(lanes):
            if all(b.end_col < s or b.start_col > e for s, e in spans):
                break
        else:
            lane = len(lanes)
            lanes.append([])
        lanes[lane].append((b.start_col, b.end_col))
        out[i] = replace(b, lane=lane)
    return [out[i] for i in range(len(bars))]


def layout_week(week_dates: list[date], events: list[Event], tz: ZoneInfo,
                capacity: int) -> WeekLayout:
    """Lay out `events` (store order) into one week row of 7 columns."""
    week_first, week_last = week_dates[0], week_dates[6]
    bars: list[Bar] = []
    lines: list[Line] = []
    for e in events:
        first, last = covered_days(e, tz)
        if last < week_first or first > week_last:
            continue
        if e.all_day or last > first:
            bars.append(Bar(e, max(0, (first - week_first).days), min(6, (last - week_first).days),
                            first < week_first, last > week_last))
        else:
            lines.append(Line(e, (first - week_first).days, e.start.astimezone(tz)))
    bars = _assign_lanes(bars)

    days = [DayLayout() for _ in range(7)]
    visible_lane_limit = [capacity] * 7
    for col in range(7):
        day_bars = [b for b in bars if b.start_col <= col <= b.end_col]
        day_lines = [ln for ln in lines if ln.col == col]
        total = len(day_bars) + len(day_lines)
        d = days[col]
        d.total = total
        for limit in (capacity, max(capacity - 1, 0)):
            vis = [b for b in day_bars if b.lane < limit]
            slot = max((b.lane for b in vis), default=-1) + 1
            placed = []
            for ln in day_lines:
                if slot >= limit:
                    break
                placed.append((slot, ln))
                slot += 1
            hidden = total - len(vis) - len(placed)
            if hidden == 0:
                break
        d.placed_lines = placed
        d.visible_bars = len(vis)
        visible_lane_limit[col] = limit
        if hidden:
            d.hidden_count = hidden
            d.more_slot = limit
    segments: list[tuple[Bar, int, int]] = []
    for b in bars:
        run_start = None
        for col in range(b.start_col, b.end_col + 2):
            visible = col <= b.end_col and b.lane < visible_lane_limit[col]
            if visible and run_start is None:
                run_start = col
            elif not visible and run_start is not None:
                segments.append((b, run_start, col - 1))
                run_start = None
    return WeekLayout(segments, days)
