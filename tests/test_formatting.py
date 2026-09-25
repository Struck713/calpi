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
