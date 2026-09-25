"""Fetch schedule policy (US-41 D5). No gi."""
from __future__ import annotations

INTERVAL_S = 30 * 60
BACKOFF_S = (60, 5 * 60, 15 * 60, 30 * 60)
STARTUP_DELAY_S = 10


def next_delay(failures: int) -> int:
    """Seconds until the next fetch after `failures` consecutive failures (0 = last one succeeded)."""
    if failures <= 0:
        return INTERVAL_S
    return BACKOFF_S[min(failures, len(BACKOFF_S)) - 1]
