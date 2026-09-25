"""Swipe classification (US-35). Pure: no gi imports. Distances in px, time in s."""
from __future__ import annotations

MIN_DIST = 150.0
FLICK_DIST = 80.0
FLICK_VELOCITY = 800.0      # px/s
MAX_DURATION = 1.0
DIRECTION_RATIO = 2.0
CLAIM_DIST = 40.0


def classify_swipe(dx: float, dy: float, dt: float) -> int:
    """Return +1 (next: finger moved left), -1 (previous), or 0."""
    if dt <= 0 or dt > MAX_DURATION:
        return 0
    if abs(dx) < DIRECTION_RATIO * abs(dy):
        return 0
    if abs(dx) >= MIN_DIST or (abs(dx) >= FLICK_DIST and abs(dx) / dt >= FLICK_VELOCITY):
        return 1 if dx < 0 else -1
    return 0


def should_claim(dx: float, dy: float) -> bool:
    return abs(dx) >= CLAIM_DIST and abs(dx) >= DIRECTION_RATIO * abs(dy)
