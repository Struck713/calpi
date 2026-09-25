"""Month grid arithmetic and English names (no locale dependence, no gi)."""
from __future__ import annotations

from datetime import date, timedelta

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
GRID_DAYS = 42


def month_grid_dates(year: int, month: int, week_start: int = 0) -> list[date]:
    """42 consecutive dates covering the month; the first has weekday() == week_start (0=Mon)."""
    first = date(year, month, 1)
    lead = (first.weekday() - week_start) % 7
    start = first - timedelta(days=lead)
    return [start + timedelta(days=i) for i in range(GRID_DAYS)]


def weekday_order(week_start: int) -> list[int]:
    return [(week_start + i) % 7 for i in range(7)]


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def month_title(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"
