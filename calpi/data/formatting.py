"""Time and colour formatting helpers. No gi imports.

Always pass datetimes that are already converted to the display zone.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime

from calpi.data.models import DEFAULT_CALENDAR_COLOR

_time_format = "24h"
_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


def set_time_format(fmt: str) -> None:
    """US-28 calls this from settings. '24h' (default) or '12h'."""
    global _time_format
    if fmt not in ("24h", "12h"):
        raise ValueError(fmt)
    _time_format = fmt


def time_format() -> str:
    return _time_format


def short_time(t: datetime) -> str:
    """Compact grid label: '09:30' (24h) or '9:30a' / '2p' (12h)."""
    if _time_format == "24h":
        return f"{t.hour:02d}:{t.minute:02d}"
    h = t.hour % 12 or 12
    suffix = "a" if t.hour < 12 else "p"
    return f"{h}{suffix}" if t.minute == 0 else f"{h}:{t.minute:02d}{suffix}"


def long_time(t: datetime) -> str:
    """'09:30' (24h) or '9:30 AM' (12h). Used by the day detail (US-09)."""
    if _time_format == "24h":
        return f"{t.hour:02d}:{t.minute:02d}"
    h = t.hour % 12 or 12
    return f"{h}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def valid_color(c: str | None) -> str:
    """A safe '#rrggbb' (lower-case) for putting into CSS, else the default colour."""
    if isinstance(c, str):
        c = c.strip().lower()
        if _HEX_RE.match(c):
            return c
    return DEFAULT_CALENDAR_COLOR


def relative_luminance(color: str) -> float:
    """WCAG relative luminance of '#rrggbb' (0 black .. 1 white)."""
    c = valid_color(color)
    chans = []
    for i in (1, 3, 5):
        v = int(c[i:i + 2], 16) / 255
        chans.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def contrast_text(color: str) -> str:
    """Text colour to draw on a background of the given colour (D6)."""
    # Pick whichever of the two gives the higher WCAG contrast (US-26: crossover at L ~= 0.18;
    # the old 0.45 cut-off put white text on mid-tone colours at ~2.7:1).
    return "#0b0e11" if relative_luminance(color) > 0.18 else "#ffffff"


# --- day detail texts (US-09) -------------------------------------------------

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def long_date(day: date) -> str:
    """'Tuesday, 15 September 2026' (English names, independent of the OS locale)."""
    return f"{_WEEKDAYS[day.weekday()]}, {day.day} {_MONTHS[day.month - 1]} {day.year}"


def _short_date(day: date) -> str:
    return f"{_WEEKDAYS[day.weekday()][:3]} {day.day}"


def relative_day_word(day: date, today: date) -> str | None:
    delta = (day - today).days
    return {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(delta)


def time_range_text(event, day: date, tz) -> str:
    """'All day' / '09:30 – 10:45' / '22:30 – 01:00 (+1 day)'. `day` is the displayed day."""
    if event.all_day:
        return "All day"
    s = event.start.astimezone(tz)
    e = event.end.astimezone(tz)
    if e <= s:
        return long_time(s)
    text = f"{long_time(s)} – {long_time(e)}"
    extra = (e.date() - s.date()).days
    if extra > 0:
        text += f" (+{extra} day{'s' if extra != 1 else ''})"
    return text


def _covered(event, tz) -> tuple[date, date]:
    from calpi.data.layout import covered_days
    return covered_days(event, tz)


def multi_day_text(event, day: date, tz) -> str | None:
    """'Day 2 of 3 · Mon 14 – Wed 16 Sep', or None for a one-day event."""
    first, last = _covered(event, tz)
    n = (last - first).days + 1
    if n <= 1:
        return None
    k = min(max((day - first).days + 1, 1), n)
    end = f"{_short_date(last)} {_MONTHS[last.month - 1][:3]}"
    start = _short_date(first)
    if (first.year, first.month) != (last.year, last.month):
        start += f" {_MONTHS[first.month - 1][:3]}"
    return f"Day {k} of {n} · {start} – {end}"


def clean_description(text: str | None, limit: int = 300) -> str:
    """Plain text for display: tags removed, entities unescaped, whitespace collapsed, capped."""
    if not text:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", text))
    text = _SPACE_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


# --- US-27: sync texts ---
def interval_label(minutes: int) -> str:
    """5 -> '5 minutes', 60 -> '1 hour', 120 -> '2 hours'."""
    if minutes >= 60 and minutes % 60 == 0:
        h = minutes // 60
        return f"{h} hour" if h == 1 else f"{h} hours"
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


def relative_datetime(dt: datetime | None, now: datetime) -> str:
    """'Never' | 'Today 14:05' | 'Yesterday 22:15' | 'Monday 09:10' (last 6 days) | '12 Sep 09:10'.

    `dt` is converted to the zone of `now` (the display zone) before comparing days.
    """
    if dt is None:
        return "Never"
    if dt.tzinfo is not None and now.tzinfo is not None:
        dt = dt.astimezone(now.tzinfo)
    days = (now.date() - dt.date()).days
    t = long_time(dt)
    if days == 0:
        return f"Today {t}"
    if days == 1:
        return f"Yesterday {t}"
    if 1 < days <= 6:
        return f"{_WEEKDAYS[dt.weekday()]} {t}"
    return f"{dt.day} {_MONTHS[dt.month - 1][:3]} {t}"


def next_update_text(seconds: float | None, running: bool, offline: bool = False,
                     safe_mode: bool = False) -> str:
    """The 'Next update' line of the Sync settings section."""
    if safe_mode:
        return "Paused (safe mode)"
    if running:
        return "Updating now…"
    if seconds is None:
        return "Not scheduled"
    if seconds < 60:
        when = "less than a minute"
    else:
        n = int(-(-seconds // 60))
        when = f"{n} minute" if n == 1 else f"{n} minutes"
    if offline:
        return f"Retrying in {when} (offline)"
    return f"in about {when}" if seconds >= 60 else f"in {when}"
