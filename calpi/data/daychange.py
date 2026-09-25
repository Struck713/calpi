"""Pure day-change / wall-clock-jump detection (no gi)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime

from calpi.data import timeutil


@dataclass
class TickResult:
    now: datetime
    day_changed: tuple[date, date] | None
    jump_seconds: float | None


class DayChangeDetector:
    JUMP_THRESHOLD_S = 90

    def __init__(self, now_fn=timeutil.now, mono_fn=time.monotonic):
        self._now, self._mono = now_fn, mono_fn
        n = now_fn()
        self._last_date, self._last_wall, self._last_mono = n.date(), n, mono_fn()

    def tick(self) -> TickResult:
        n, m = self._now(), self._mono()
        jump = (n.timestamp() - self._last_wall.timestamp()) - (m - self._last_mono)  # absolute instants (same-tzinfo subtraction is wall-clock)
        changed = None
        if n.date() != self._last_date:
            changed = (self._last_date, n.date())
            self._last_date = n.date()
        self._last_wall, self._last_mono = n, m
        return TickResult(n, changed, jump if abs(jump) > self.JUMP_THRESHOLD_S else None)
