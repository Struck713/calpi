from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from calpi.data.daychange import DayChangeDetector

BER = ZoneInfo("Europe/Berlin")


class Clock:
    def __init__(self, start, tz=None):
        self.wall = start
        self.mono = 1000.0
        self.tz = tz

    def now(self):
        return self.wall.astimezone(self.tz) if self.tz else self.wall

    def m(self):
        return self.mono

    def advance(self, s):
        self.wall += timedelta(seconds=s)
        self.mono += s


def make(start, tz=None):
    c = Clock(start, tz)
    return c, DayChangeDetector(c.now, c.m)


def test_midnight_once():
    c, d = make(datetime(2026, 9, 30, 23, 58, tzinfo=BER))
    changes = []
    for _ in range(5):
        c.advance(60)
        r = d.tick()
        assert r.jump_seconds is None
        if r.day_changed:
            changes.append((r.day_changed, r.now.strftime("%H:%M")))
    assert len(changes) == 1
    assert changes[0][1] == "00:00"
    assert str(changes[0][0][1]) == "2026-10-01"


def test_forward_jump():
    c, d = make(datetime(2026, 9, 30, 22, 0, tzinfo=BER))
    c.wall += timedelta(hours=3)
    c.mono += 60
    r = d.tick()
    assert r.day_changed is not None
    assert abs(r.jump_seconds - (3 * 3600 - 60)) < 1


def test_backward_jump_over_midnight():
    c, d = make(datetime(2026, 10, 1, 0, 5, tzinfo=BER))
    c.wall -= timedelta(minutes=15)
    c.mono += 60
    r = d.tick()
    assert r.day_changed is not None and r.day_changed[1] < r.day_changed[0]
    assert r.jump_seconds < 0


def test_zone_change_no_jump():
    base = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)
    c, d = make(base, ZoneInfo("UTC"))
    c.advance(60)
    c.tz = ZoneInfo("Asia/Tokyo")
    r = d.tick()
    assert r.day_changed is not None
    assert r.jump_seconds is None


def test_dst_nights_single_change():
    for start in (datetime(2026, 3, 28, 22, 0, tzinfo=BER), datetime(2026, 10, 24, 22, 0, tzinfo=BER)):
        c, d = make(start.astimezone(timezone.utc), BER)
        n = 0
        for _ in range(6 * 60):
            c.advance(60)
            r = d.tick()
            assert r.jump_seconds is None
            n += r.day_changed is not None
        assert n == 1
