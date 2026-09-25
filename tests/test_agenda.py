from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from calpi.data import agenda
from calpi.data.models import Event

UTC = timezone.utc
BER = ZoneInfo("Europe/Berlin")


def timed(d, h, m, ed, eh, em, summary="t", tz=UTC):
    return Event("c", summary + str(d) + str(h), summary, False,
                 datetime(d.year, d.month, d.day, h, m, tzinfo=tz),
                 datetime(ed.year, ed.month, ed.day, eh, em, tzinfo=tz))


def allday(d, ed, summary="a"):
    return Event("c", summary, summary, True, d, ed)


NOW = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
D = date


def test_ended_excluded_ongoing_first_next_marked():
    evs = [timed(D(2026, 9, 15), 8, 0, D(2026, 9, 15), 9, 0, "done"),
           timed(D(2026, 9, 15), 9, 30, D(2026, 9, 15), 10, 30, "now"),
           timed(D(2026, 9, 15), 12, 0, D(2026, 9, 15), 13, 0, "later"),
           timed(D(2026, 9, 15), 15, 0, D(2026, 9, 15), 16, 0, "last"),
           allday(D(2026, 9, 15), D(2026, 9, 16), "holiday")]
    g = agenda.build_agenda(evs, NOW, UTC)
    assert [d for d, _ in g] == [D(2026, 9, 15)]
    items = g[0][1]
    assert [i.event.summary for i in items] == ["now", "holiday", "later", "last"]
    assert [i.kind for i in items] == ["ongoing", "allday", "upcoming", "upcoming"]
    assert [i.is_next for i in items] == [False, False, True, False]
    assert items[1].time_text == "All day"


def test_multiday_once_under_today():
    e = timed(D(2026, 9, 14), 9, 0, D(2026, 9, 16), 17, 0, "trip")
    g = agenda.build_agenda([e], NOW, UTC)
    assert len(g) == 1 and g[0][0] == D(2026, 9, 15)
    assert g[0][1][0].kind == "ongoing"
    assert g[0][1][0].range_text == "until Wed 16"
    a = allday(D(2026, 9, 14), D(2026, 9, 17), "camp")
    it = agenda.build_agenda([a], NOW, UTC)[0][1][0]
    assert it.kind == "multiday" and it.range_text == "until Wed 16"
    f = allday(D(2026, 9, 20), D(2026, 9, 23), "later")
    g = agenda.build_agenda([f], NOW, UTC)
    assert g[0][0] == D(2026, 9, 20) and g[0][1][0].range_text == "Sun 20 – Tue 22"


def test_horizon_and_cap():
    far = timed(D(2026, 10, 15), 9, 0, D(2026, 10, 15), 10, 0)      # today+30: excluded
    near = timed(D(2026, 10, 14), 9, 0, D(2026, 10, 14), 10, 0)
    g = agenda.build_agenda([far, near], NOW, UTC)
    assert [d for d, _ in g] == [D(2026, 10, 14)]
    evs = [timed(D(2026, 9, 16), 9, i, D(2026, 9, 16), 10, i, f"e{i:02d}") for i in range(10)]
    ag = agenda.build_agenda_full(evs, NOW, UTC, cap=4)
    assert sum(len(x) for _, x in ag.groups) == 4 and ag.more_after == D(2026, 9, 16)
    assert agenda.build_agenda_full(evs, NOW, UTC, cap=10).more_after is None


def test_headings():
    t = D(2026, 9, 15)
    assert agenda.heading_text(t, t) == "Today"
    assert agenda.heading_text(D(2026, 9, 16), t) == "Tomorrow"
    assert agenda.heading_text(D(2026, 9, 17), t) == "Thursday 17 September"


def test_empty():
    assert agenda.build_agenda([], NOW, UTC) == []


def test_dst_day_berlin():
    # 2026-10-25 is the fall-back day in Berlin; now is the day before.
    now = datetime(2026, 10, 24, 20, 0, tzinfo=BER)
    e = timed(D(2026, 10, 24), 23, 30, D(2026, 10, 25), 0, 30, "late", tz=BER)
    x = timed(D(2026, 10, 25), 2, 30, D(2026, 10, 25), 3, 30, "dst", tz=BER)
    g = agenda.build_agenda([e, x], now, BER)
    assert [d for d, _ in g] == [D(2026, 10, 24), D(2026, 10, 25)]
    assert g[0][1][0].is_next and not g[1][1][0].is_next
