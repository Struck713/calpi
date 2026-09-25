from datetime import date, timedelta

import pytest

from calpi.data import monthmath as mm


@pytest.mark.parametrize("year", range(2024, 2031))
@pytest.mark.parametrize("month", range(1, 13))
@pytest.mark.parametrize("ws", range(7))
def test_grid(year, month, ws):
    d = mm.month_grid_dates(year, month, ws)
    first = date(year, month, 1)
    assert len(d) == 42
    assert all(b - a == timedelta(days=1) for a, b in zip(d, d[1:]))
    assert d[0].weekday() == ws
    assert first - timedelta(days=7) < d[0] <= first
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    assert nxt - timedelta(days=1) in d


def test_examples():
    assert mm.month_grid_dates(2026, 2, 0)[0] == date(2026, 1, 26)
    assert mm.month_grid_dates(2026, 2, 6)[0] == date(2026, 2, 1)


def test_add_months():
    assert mm.add_months(2026, 12, 1) == (2027, 1)
    assert mm.add_months(2026, 1, -1) == (2025, 12)
    assert mm.add_months(2026, 3, -15) == (2024, 12)


def test_title_and_order():
    assert mm.month_title(2026, 9) == "September 2026"
    assert mm.weekday_order(6) == [6, 0, 1, 2, 3, 4, 5]
