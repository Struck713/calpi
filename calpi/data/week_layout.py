"""Pure week-timeline layout (US-39). No gi imports.

Times are LOCAL wall-clock minutes since local midnight in the display zone (D3). The widget
only draws what this module computes: block rectangles, earlier/later counts, all-day strip.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from calpi.data import layout as month_layout
from calpi.data.models import Event
from calpi.data.monthmath import MONTH_NAMES

DAY_MIN = 1440
ALLDAY_CAPACITY = 3
MARKER_H = 26.0            # px: height of the "earlier" / "later" marker hit area


@dataclass(frozen=True)
class Segment:
    event: Event
    day_index: int
    start_min: int          # local minutes since midnight, clipped to this day
    end_min: int            # exclusive; 1440 = end of day
    cont_before: bool = False   # event started on an earlier day
    cont_after: bool = False


@dataclass(frozen=True)
class Geometry:
    gutter: float
    day_w: float
    top: float
    hour_px: float
    start_h: int = 7
    end_h: int = 22
    gap: float = 2.0
    min_h: float = 26.0

    @property
    def bottom(self) -> float:
        return self.top + (self.end_h - self.start_h) * self.hour_px

    def x_of_day(self, i: int) -> float:
        return self.gutter + i * self.day_w

    def y_of_min(self, minute: float) -> float:
        return self.top + (minute - self.start_h * 60) / 60.0 * self.hour_px


@dataclass(frozen=True)
class Block:
    segment: Segment
    x: float
    y: float
    w: float
    h: float
    col: int
    ncols: int
    clipped_top: bool
    clipped_bottom: bool


@dataclass
class WeekLayout:
    week_dates: list[date]
    geom: Geometry
    blocks: list[Block] = field(default_factory=list)
    earlier: list[int] = field(default_factory=lambda: [0] * 7)
    later: list[int] = field(default_factory=lambda: [0] * 7)
    allday: month_layout.WeekLayout | None = None


# ---- week arithmetic --------------------------------------------------------

def week_start_of(d: date, week_start: int) -> date:
    """First day of the week containing d (week_start: 0 = Monday)."""
    return d - timedelta(days=(d.weekday() - week_start) % 7)


def week_dates(first: date) -> list[date]:
    return [first + timedelta(days=i) for i in range(7)]


def week_title(dates: list[date]) -> str:
    """'14 - 20 September 2026', '28 Sep - 4 Oct 2026', '29 Dec 2026 - 4 Jan 2027' (en dashes)."""
    a, b = dates[0], dates[-1]
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day} – {b.day} {MONTH_NAMES[a.month - 1]} {a.year}"
    if a.year == b.year:
        return f"{a.day} {MONTH_NAMES[a.month - 1][:3]} – {b.day} {MONTH_NAMES[b.month - 1][:3]} {a.year}"
    return (f"{a.day} {MONTH_NAMES[a.month - 1][:3]} {a.year} – "
            f"{b.day} {MONTH_NAMES[b.month - 1][:3]} {b.year}")


# ---- segments ---------------------------------------------------------------

def split_timed(events: list[Event], dates: list[date], tz: ZoneInfo) -> list[Segment]:
    """Per-day pieces of timed events (multi-day events split at local midnight)."""
    out: list[Segment] = []
    first_day, last_day = dates[0], dates[-1]
    for e in events:
        if e.all_day:
            continue
        cov_first, cov_last = month_layout.covered_days(e, tz)
        if cov_last < first_day or cov_first > last_day:
            continue
        s = e.start.astimezone(tz)
        en = e.end.astimezone(tz)
        for i, d in enumerate(dates):
            if d < cov_first or d > cov_last:
                continue
            before = s.date() < d
            after = cov_last > d
            start = 0 if before else s.hour * 60 + s.minute
            if after:
                end = DAY_MIN
            else:
                end = en.hour * 60 + en.minute
                if en.date() > d:              # ends exactly at the next midnight
                    end = DAY_MIN
                end = max(end, start)
            out.append(Segment(e, i, start, end, before, after))
    return out


def assign_columns(segments: list[Segment], min_minutes: float = 0.0
                   ) -> list[tuple[Segment, int, int]]:
    """D2: cluster transitively overlapping segments; lowest free column; ncols per cluster.

    `min_minutes` is the minimum drawn duration, so short blocks that would visually collide
    also get separate columns. Returns (segment, col, ncols) in start order.
    """
    def eff_end(s: Segment) -> float:
        return max(s.end_min, s.start_min + min_minutes)

    order = sorted(segments, key=lambda s: (s.start_min, -(s.end_min - s.start_min)))
    result: list[tuple[Segment, int, int]] = []
    cluster: list[tuple[Segment, int]] = []
    col_ends: list[float] = []
    cluster_end = -1.0

    def flush():
        n = (max(c for _, c in cluster) + 1) if cluster else 0
        result.extend((s, c, n) for s, c in cluster)
        cluster.clear()
        col_ends.clear()

    for s in order:
        if cluster and s.start_min >= cluster_end:
            flush()
        for col, end in enumerate(col_ends):
            if end <= s.start_min:
                break
        else:
            col = len(col_ends)
            col_ends.append(0.0)
        col_ends[col] = eff_end(s)
        cluster.append((s, col))
        cluster_end = max(cluster_end, eff_end(s)) if len(cluster) > 1 else eff_end(s)
    flush()
    return result


# ---- build ------------------------------------------------------------------

def build(dates: list[date], events: list[Event], tz: ZoneInfo, geom: Geometry) -> WeekLayout:
    lay = WeekLayout(list(dates), geom)
    lay.allday = month_layout.layout_week(dates, [e for e in events if e.all_day], tz,
                                          ALLDAY_CAPACITY)
    lo, hi = geom.start_h * 60, geom.end_h * 60
    min_minutes = geom.min_h / geom.hour_px * 60.0 if geom.hour_px > 0 else 0.0
    per_day: list[list[Segment]] = [[] for _ in range(7)]
    for seg in split_timed(events, dates, tz):
        if seg.end_min <= lo and not (seg.start_min == seg.end_min and seg.start_min >= lo):
            lay.earlier[seg.day_index] += 1
        elif seg.start_min >= hi:
            lay.later[seg.day_index] += 1
        else:
            per_day[seg.day_index].append(seg)
    for i, segs in enumerate(per_day):
        for seg, col, ncols in assign_columns(segs, min_minutes):
            s_min = max(seg.start_min, lo)
            e_min = min(seg.end_min, hi)
            y = geom.y_of_min(s_min)
            h = max(geom.min_h, (e_min - s_min) / 60.0 * geom.hour_px)
            h = min(h, geom.bottom - y) if y + h > geom.bottom else h
            cw = geom.day_w / ncols
            lay.blocks.append(Block(seg, geom.x_of_day(i) + col * cw, y, cw - geom.gap, h, col, ncols,
                                    seg.start_min < lo, seg.end_min > hi))
    return lay


def hit_test(lay: WeekLayout, x: float, y: float) -> tuple[str, date] | None:
    """('event' | 'earlier' | 'later', date) for a point in timeline coordinates, else None."""
    g = lay.geom
    for b in reversed(lay.blocks):
        if b.x <= x < b.x + b.w and b.y <= y < b.y + b.h:
            return "event", lay.week_dates[b.segment.day_index]
    if x < g.gutter:
        return None
    i = int((x - g.gutter) // g.day_w)
    if not 0 <= i < 7:
        return None
    if lay.earlier[i] and g.top <= y < g.top + MARKER_H:
        return "earlier", lay.week_dates[i]
    if lay.later[i] and g.bottom - MARKER_H <= y < g.bottom:
        return "later", lay.week_dates[i]
    return None


def column_at(geom: Geometry, x: float) -> int | None:
    """Day column index (0..6) for an x in widget coordinates, or None (gutter/out of range)."""
    if x < geom.gutter or geom.day_w <= 0:
        return None
    i = int((x - geom.gutter) // geom.day_w)
    return i if 0 <= i < 7 else None
