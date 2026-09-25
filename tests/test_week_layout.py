from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from calpi.data import week_layout as wl
from calpi.data.models import Event

UTC = ZoneInfo("UTC")
BERLIN = ZoneInfo("Europe/Berlin")
MON = date(2026, 9, 14)
DATES = wl.week_dates(MON)
GEOM = wl.Geometry(gutter=80, day_w=250, top=0, hour_px=55, start_h=7, end_h=22)


def timed(summary, day, s, e, tz=UTC, end_day=None):
    st = datetime.combine(day, s, tz).astimezone(timezone.utc)
    en = datetime.combine(end_day or day, e, tz).astimezone(timezone.utc)
    return Event("c", summary, summary, False, st, en)


def T(h, m=0):
    return time(h, m)


def test_week_start_and_title():
    assert wl.week_start_of(date(2026, 9, 16), 0) == MON
    assert wl.week_start_of(date(2026, 9, 20), 6) == date(2026, 9, 20)
    assert wl.week_start_of(date(2026, 9, 19), 6) == date(2026, 9, 13)
    assert wl.week_title(DATES) == "14 – 20 September 2026"
    assert wl.week_title(wl.week_dates(date(2026, 9, 28))) == "28 Sep – 4 Oct 2026"
    assert wl.week_title(wl.week_dates(date(2026, 12, 28))) == "28 Dec 2026 – 3 Jan 2027"


def test_no_overlap_single_columns():
    evs = [timed("a", MON, T(9), T(10)), timed("b", MON, T(11), T(12))]
    lay = wl.build(DATES, evs, UTC, GEOM)
    assert [(b.col, b.ncols) for b in lay.blocks] == [(0, 1), (0, 1)]
    assert lay.blocks[0].y == (9 - 7) * 55 and lay.blocks[0].h == 55


def test_overlap_columns():
    segs = wl.split_timed([timed("A", MON, T(9), T(10)), timed("B", MON, T(9, 30), T(11)),
                           timed("C", MON, T(10), T(10, 30))], DATES, UTC)
    got = {s.event.summary: (c, n) for s, c, n in wl.assign_columns(segs)}
    assert got == {"A": (0, 2), "B": (1, 2), "C": (0, 2)}


def test_chain_and_separate_clusters():
    evs = [timed("A", MON, T(8), T(9)), timed("B", MON, T(8, 30), T(9, 30)),
           timed("C", MON, T(9, 15), T(10)), timed("D", MON, T(12), T(13))]
    got = {s.event.summary: (c, n) for s, c, n in wl.assign_columns(wl.split_timed(evs, DATES, UTC))}
    assert got["A"] == (0, 2) and got["B"] == (1, 2) and got["C"] == (0, 2)
    assert got["D"] == (0, 1)


def test_block_geometry_columns():
    lay = wl.build(DATES, [timed("A", MON, T(9), T(10)), timed("B", MON, T(9), T(10))], UTC, GEOM)
    a, b = lay.blocks
    assert a.w == b.w == 125 - GEOM.gap and b.x == a.x + 125


def test_zero_length_min_height_and_column():
    evs = [timed("z", MON, T(9), T(9)), timed("y", MON, T(9, 5), T(10))]
    lay = wl.build(DATES, evs, UTC, GEOM)
    assert lay.blocks[0].h == GEOM.min_h
    assert {b.ncols for b in lay.blocks} == {2}     # short block would collide with the next


def test_midnight_split():
    evs = [timed("m", MON, T(22, 30), T(1), end_day=MON + timedelta(days=1))]
    segs = wl.split_timed(evs, DATES, UTC)
    assert [(s.day_index, s.start_min, s.end_min) for s in segs] == [(0, 1350, 1440), (1, 0, 60)]
    lay = wl.build(DATES, evs, UTC, GEOM)
    # day 0: 22:30 is after 22:00 -> later; day 1: 00:00-01:00 -> earlier
    assert lay.later[0] == 1 and lay.earlier[1] == 1 and not lay.blocks


def test_ends_at_midnight_and_week_edges():
    e = timed("x", MON + timedelta(days=6), T(21), T(0), end_day=MON + timedelta(days=7))
    segs = wl.split_timed([e], DATES, UTC)
    assert [(s.day_index, s.end_min) for s in segs] == [(6, 1440)]
    lay = wl.build(DATES, [e], UTC, GEOM)
    assert lay.blocks[0].clipped_bottom and not lay.blocks[0].clipped_top
    assert lay.blocks[0].y + lay.blocks[0].h <= GEOM.bottom


def test_earlier_later_and_clipping():
    evs = [timed("e1", MON, T(5), T(6)), timed("e2", MON, T(6), T(7)),
           timed("l1", MON, T(22), T(23)), timed("edge", MON, T(6), T(8)),
           timed("edge2", MON, T(21, 30), T(23))]
    lay = wl.build(DATES, evs, UTC, GEOM)
    assert lay.earlier[0] == 2 and lay.later[0] == 1
    by = {b.segment.event.summary: b for b in lay.blocks}
    assert by["edge"].clipped_top and by["edge"].y == 0 and by["edge"].h == 55
    assert by["edge2"].clipped_bottom


def test_dst_day_wall_time():
    day = date(2026, 3, 29)                       # Berlin springs forward 02:00 -> 03:00
    dates = wl.week_dates(date(2026, 3, 23))
    e = timed("d", day, T(9), T(10), tz=BERLIN)
    seg = wl.split_timed([e], dates, BERLIN)[0]
    assert (seg.day_index, seg.start_min, seg.end_min) == (6, 540, 600)


def test_allday_excluded_from_timeline_and_multiday_timed_not_in_strip():
    ad = Event("c", "ad", "ad", True, MON, MON + timedelta(days=2))
    md = timed("md", MON, T(18), T(12), end_day=MON + timedelta(days=2))
    lay = wl.build(DATES, [ad, md], UTC, GEOM)
    assert [(b.start_col, b.end_col) for b, _, _ in lay.allday.bars] == [(0, 1)]
    assert {b.segment.day_index for b in lay.blocks} == {0, 1, 2}


def test_hit_test():
    evs = [timed("A", MON, T(9), T(10)), timed("e", MON + timedelta(days=1), T(5), T(6)),
           timed("l", MON + timedelta(days=2), T(22, 30), T(23))]
    lay = wl.build(DATES, evs, UTC, GEOM)
    assert wl.hit_test(lay, 80 + 10, 2 * 55 + 5) == ("event", MON)
    assert wl.hit_test(lay, 80 + 250 + 5, 3) == ("earlier", MON + timedelta(days=1))
    assert wl.hit_test(lay, 80 + 500 + 5, GEOM.bottom - 3) == ("later", MON + timedelta(days=2))
    assert wl.hit_test(lay, 80 + 10, 500) is None
    assert wl.hit_test(lay, 10, 10) is None
    assert wl.column_at(GEOM, 79) is None and wl.column_at(GEOM, 81) == 0
    assert wl.column_at(GEOM, 80 + 7 * 250) is None
