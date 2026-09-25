import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from calpi.data.layout import covered_days, layout_week
from calpi.data.models import Event

UTC = ZoneInfo("UTC")
MON = date(2026, 9, 7)
WEEK = [MON + timedelta(days=i) for i in range(7)]


def timed(day, h, m, end_day, eh, em, tz=UTC, summary="t", cal="c"):
    s = datetime.combine(day, time(h, m), tz).astimezone(timezone.utc)
    e = datetime.combine(end_day, time(eh, em), tz).astimezone(timezone.utc)
    return Event(cal, summary + str(id(object())), summary, False, s, e)


def line(col, h=9, summary="t"):
    d = WEEK[col]
    return timed(d, h, 0, d, h, 30, summary=summary)


def allday(col, days=1, summary="a"):
    d = WEEK[0] + timedelta(days=col)
    return Event("c", summary, summary, True, d, d + timedelta(days=days))


def test_single_timed_line():
    wl = layout_week(WEEK, [line(2)], UTC, 4)
    assert not wl.bars
    assert [(s, ln.col) for s, ln in wl.days[2].placed_lines] == [(0, 2)]


def test_three_day_bar():
    wl = layout_week(WEEK, [allday(1, 3)], UTC, 4)
    (bar, c0, c1), = wl.bars
    assert (bar.start_col, bar.end_col, bar.lane, (c0, c1)) == (1, 3, 0, (1, 3))


def test_single_day_allday_is_bar():
    wl = layout_week(WEEK, [allday(4)], UTC, 4)
    assert len(wl.bars) == 1 and wl.bars[0][0].lane == 0


def test_lanes():
    evs = [allday(0, 3, "x"), allday(1, 3, "y"), allday(4, 2, "z")]
    lanes = {b.event.summary: b.lane for b, _, _ in layout_week(WEEK, evs, UTC, 4).bars}
    assert lanes == {"x": 0, "y": 1, "z": 0}


def test_continuation():
    evs = [Event("c", "a", "a", True, WEEK[0] - timedelta(days=2), WEEK[0] + timedelta(days=2)),
           Event("c", "b", "b", True, WEEK[5], WEEK[6] + timedelta(days=3))]
    bars = {b.event.summary: b for b, _, _ in layout_week(WEEK, evs, UTC, 4).bars}
    assert (bars["a"].start_col, bars["a"].end_col) == (0, 1)
    assert bars["a"].continues_before and not bars["a"].continues_after
    assert (bars["b"].start_col, bars["b"].end_col) == (5, 6)
    assert bars["b"].continues_after and not bars["b"].continues_before


def test_midnight_crossing_and_exact_midnight():
    cross = timed(WEEK[1], 22, 30, WEEK[2], 1, 0)
    wl = layout_week(WEEK, [cross], UTC, 4)
    assert [(b.start_col, b.end_col) for b, _, _ in wl.bars] == [(1, 2)]
    full = timed(WEEK[1], 0, 0, WEEK[2], 0, 0)
    wl = layout_week(WEEK, [full], UTC, 4)
    assert not wl.bars and wl.days[1].placed_lines and not wl.days[2].placed_lines
    ends = timed(WEEK[1], 20, 0, WEEK[2], 0, 0)
    assert covered_days(ends, UTC) == (WEEK[1], WEEK[1])


def test_local_day_not_utc_day():
    tz = ZoneInfo("Pacific/Auckland")
    e = timed(WEEK[3], 1, 0, WEEK[3], 2, 0, tz=tz)     # 13:00 UTC the previous day
    assert covered_days(e, tz) == (WEEK[3], WEEK[3])


def test_overflow_lines():
    wl = layout_week(WEEK, [line(2, 8 + i) for i in range(9)], UTC, 4)
    d = wl.days[2]
    assert [s for s, _ in d.placed_lines] == [0, 1, 2]
    assert (d.hidden_count, d.more_slot) == (6, 3)


def test_overflow_with_bars():
    evs = [allday(2, 1, f"b{i}") for i in range(4)] + [allday(1, 1, "t0"), allday(1, 1, "t1")]
    evs += [line(2, 9), line(2, 10)]
    wl = layout_week(WEEK, evs, UTC, 4)
    wed = wl.days[2]
    assert wed.visible_bars == 3 and not wed.placed_lines
    assert (wed.hidden_count, wed.more_slot) == (3, 3)
    assert wl.days[1].hidden_count == 0


def test_hidden_bar_splits_segments():
    evs = [allday(0, 3, f"w{i}") for i in range(3)]          # lanes 0-2 across Mon-Wed
    evs.append(allday(0, 3, "long"))                         # lane 3
    evs += [line(1, 8 + i) for i in range(3)]                # Tue: 4 items already + lines
    wl = layout_week(WEEK, evs, UTC, 4)
    segs = [(c0, c1) for b, c0, c1 in wl.bars if b.event.summary == "long"]
    assert segs == [(0, 0), (2, 2)]
    assert wl.days[1].hidden_count == 4 + 3 - 3


def test_dst_one_day():
    tz = ZoneInfo("Europe/Berlin")
    d = date(2026, 3, 29)
    e = timed(d, 1, 30, d, 3, 30, tz=tz)
    assert covered_days(e, tz) == (d, d)


def test_property_hidden_count_exact():
    rnd = random.Random(7)
    tz = ZoneInfo("Europe/Berlin")
    for _ in range(1000):
        evs = []
        for _ in range(rnd.randint(0, 14)):
            s = rnd.randint(-2, 8)
            if rnd.random() < 0.4:
                evs.append(Event("c", "u", "s", True, WEEK[0] + timedelta(days=s),
                                 WEEK[0] + timedelta(days=s + rnd.randint(0, 4))))
            else:
                a = datetime.combine(WEEK[0] + timedelta(days=s), time(rnd.randint(0, 23)), tz)
                evs.append(Event("c", "u", "s", False, a.astimezone(timezone.utc),
                                 (a + timedelta(hours=rnd.choice([0, 1, 5, 30, 60]))).astimezone(timezone.utc)))
        cap = rnd.choice([2, 3, 4])
        wl = layout_week(WEEK, evs, tz, cap)
        for col, d in enumerate(wl.days):
            shown_bars = sum(1 for b, c0, c1 in wl.bars if c0 <= col <= c1)
            assert shown_bars == d.visible_bars
            assert shown_bars + len(d.placed_lines) + d.hidden_count == d.total
            slots = [b.lane for b, c0, c1 in wl.bars if c0 <= col <= c1] + [s for s, _ in d.placed_lines]
            assert len(set(slots)) == len(slots)
            limit = cap - 1 if d.hidden_count else cap
            assert all(s < limit for s in slots)
