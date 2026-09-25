from datetime import datetime, timezone

import pytest

from calpi.data import formatting as f


@pytest.fixture(autouse=True)
def _reset():
    yield
    f.set_time_format("24h")


def t(h, m=0):
    return datetime(2026, 9, 1, h, m, tzinfo=timezone.utc)


def test_24h():
    assert f.short_time(t(9, 30)) == "09:30"
    assert f.short_time(t(0, 0)) == "00:00"
    assert f.long_time(t(14, 5)) == "14:05"


def test_12h():
    f.set_time_format("12h")
    assert f.short_time(t(9, 30)) == "9:30a"
    assert f.short_time(t(14, 15)) == "2:15p"
    assert f.short_time(t(0, 0)) == "12a"
    assert f.short_time(t(12, 0)) == "12p"
    assert f.short_time(t(12, 5)) == "12:05p"
    assert f.long_time(t(9, 30)) == "9:30 AM"
    assert f.long_time(t(0, 0)) == "12:00 AM"
    assert f.long_time(t(12, 0)) == "12:00 PM"


def test_bad_format():
    with pytest.raises(ValueError):
        f.set_time_format("13h")


def test_contrast():
    assert f.contrast_text("#ffffff") == "#0b0e11"
    assert f.contrast_text("#000000") == "#ffffff"
    assert f.contrast_text("#ffb020") == "#0b0e11"
    assert f.contrast_text("#1a237e") == "#ffffff"
    assert f.relative_luminance("#ffffff") == pytest.approx(1.0)


def test_valid_color():
    assert f.valid_color("#ABCDEF") == "#abcdef"
    for bad in ("red", "#fff", "#12345g", "#123456; } x {", None, ""):
        assert f.valid_color(bad) == f.DEFAULT_CALENDAR_COLOR


# --- US-09 day detail texts ---
from datetime import date, timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from calpi.data.models import Event  # noqa: E402

UTC = ZoneInfo("UTC")


def timed(sh, sm, eh, em, days=0):
    s = datetime(2026, 9, 15, sh, sm, tzinfo=timezone.utc)
    e = datetime(2026, 9, 15, eh, em, tzinfo=timezone.utc) + timedelta(days=days)
    return Event("c", "u", "x", False, s, e)


def test_time_range_text():
    d = date(2026, 9, 15)
    assert f.time_range_text(timed(9, 30, 10, 45), d, UTC) == "09:30 – 10:45"
    f.set_time_format("12h")
    assert f.time_range_text(timed(9, 30, 14, 45), d, UTC) == "9:30 AM – 2:45 PM"
    f.set_time_format("24h")
    assert f.time_range_text(timed(22, 30, 1, 0, days=1), d, UTC) == "22:30 – 01:00 (+1 day)"
    ad = Event("c", "u", "x", True, date(2026, 9, 15), date(2026, 9, 16))
    assert f.time_range_text(ad, d, UTC) == "All day"


def test_multi_day_text():
    ev = Event("c", "u", "x", True, date(2026, 9, 14), date(2026, 9, 17))
    assert f.multi_day_text(ev, date(2026, 9, 15), UTC) == "Day 2 of 3 · Mon 14 – Wed 16 Sep"
    assert f.multi_day_text(ev, date(2026, 9, 14), UTC).startswith("Day 1 of 3")
    assert f.multi_day_text(ev, date(2026, 9, 16), UTC).startswith("Day 3 of 3")
    one = Event("c", "u", "x", True, date(2026, 9, 14), date(2026, 9, 15))
    assert f.multi_day_text(one, date(2026, 9, 14), UTC) is None


def test_clean_description():
    assert f.clean_description("<p>Tom &amp; Jerry</p>\n\n<b>hi</b>   there") == "Tom & Jerry hi there"
    assert f.clean_description(None) == ""
    out = f.clean_description("a" * 500)
    assert len(out) == 301 and out.endswith("…")


def test_relative_and_long_date():
    t0 = date(2026, 9, 15)
    assert f.relative_day_word(t0, t0) == "Today"
    assert f.relative_day_word(t0 + timedelta(days=1), t0) == "Tomorrow"
    assert f.relative_day_word(t0 - timedelta(days=1), t0) == "Yesterday"
    assert f.relative_day_word(t0 + timedelta(days=2), t0) is None
    assert f.long_date(t0) == "Tuesday, 15 September 2026"


# --- US-27 ---
def test_interval_label():
    assert [f.interval_label(m) for m in (5, 60, 120, 240, 1)] == \
        ["5 minutes", "1 hour", "2 hours", "4 hours", "1 minute"]


def test_relative_datetime():
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Paris")
    now = datetime(2026, 9, 25, 0, 30, tzinfo=tz)            # Friday, just after midnight
    assert f.relative_datetime(None, now) == "Never"
    assert f.relative_datetime(datetime(2026, 9, 25, 0, 5, tzinfo=tz), now) == "Today 00:05"
    # 22:15 UTC on the 24th is 00:15 Paris on the 25th: "Today" in the display zone
    assert f.relative_datetime(datetime(2026, 9, 24, 22, 15, tzinfo=timezone.utc), now) == "Today 00:15"
    assert f.relative_datetime(datetime(2026, 9, 24, 22, 15, tzinfo=tz), now) == "Yesterday 22:15"
    assert f.relative_datetime(datetime(2026, 9, 21, 9, 10, tzinfo=tz), now) == "Monday 09:10"
    assert f.relative_datetime(datetime(2026, 9, 12, 9, 10, tzinfo=tz), now) == "12 Sep 09:10"
    f.set_time_format("12h")
    assert f.relative_datetime(datetime(2026, 9, 24, 22, 15, tzinfo=tz), now) == "Yesterday 10:15 PM"


def test_next_update_text():
    n = f.next_update_text
    assert n(700, False) == "in about 12 minutes"
    assert n(61, False) == "in about 2 minutes"
    assert n(30, False) == "in less than a minute"
    assert n(None, True) == "Updating now…"
    assert n(240, False, offline=True) == "Retrying in 4 minutes (offline)"
    assert n(240, False, safe_mode=True) == "Paused (safe mode)"
    assert n(None, False) == "Not scheduled"
