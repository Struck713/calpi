"""Header sync indicator state (US-17). No gi. US-19 adds manual-result helpers to this module."""
from __future__ import annotations

from datetime import datetime, timedelta

from calpi.data import formatting

# --- US-17: header indicator state (running > clock > offline > stale > ok) ---
STALE_AFTER = timedelta(hours=6)


def _updated(last_success: datetime, now: datetime) -> str:
    t = last_success.astimezone(now.tzinfo)
    when = formatting.short_time(t)
    days = (now.date() - t.date()).days
    if days <= 0:
        return f"Updated {when}"
    if days == 1:
        return f"Updated yesterday {when}"
    if days < 7:
        return f"Updated {days} days ago"
    return f"Updated {t.day} {t:%b} {when}"


def compute_state(running: bool, offline: bool, clock_synced: bool | None, net_state: str | None,
                  last_success: datetime | None, now: datetime) -> tuple[str, str]:
    """-> (css_state, text). net_state: 'online'|'limited'|'offline'|'unknown'|None."""
    if running:
        return "running", "Updating…"
    net_down = net_state in ("offline", "limited")
    if clock_synced is False and (net_down or offline):
        return "clock", "Clock not set"
    if offline or net_down:
        text = "Offline"
        if last_success is not None:
            text += " · " + _updated(last_success, now).replace("Updated ", "updated ", 1)
        return "offline", text
    if last_success is None:
        return "ok", ""
    text = _updated(last_success, now)
    if now - last_success > STALE_AFTER:
        return "stale", text
    return "ok", text
