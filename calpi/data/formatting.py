"""Time and colour formatting helpers. No gi imports.

Always pass datetimes that are already converted to the display zone.
"""
from __future__ import annotations

import re
from datetime import datetime

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
    return "#0b0e11" if relative_luminance(color) > 0.45 else "#ffffff"
