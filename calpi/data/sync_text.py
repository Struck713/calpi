"""Short user-facing sync texts (US-19). No gi imports. Problem wording lives in messages (US-38)."""
from __future__ import annotations

from datetime import datetime, timedelta

from calpi.data import formatting



def is_manual(result: dict) -> bool:
    """True if the run was requested by a manual refresh (also when merged: 'coalesced:...manual...')."""
    return "manual" in (result.get("reason") or "").removeprefix("coalesced:").split(",")


def is_success(result: dict) -> bool:
    """Same rule as the engine: done, and no accounts or at least one account without an error."""
    if result.get("status") != "done":
        return False
    accts = result.get("accounts", [])
    return not accts or any(a.get("error") is None for a in accts)


def manual_result_text(result: dict, provider_names: dict[str, str] | None = None) -> str:
    """Short failure text for a manual refresh. `provider_names` maps account_id -> provider name."""
    from calpi.data import messages
    return messages.toast_for_result(result, provider_names)


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
                  last_success: datetime | None, now: datetime,
                  error: str | None = None) -> tuple[str, str]:
    """-> (css_state, text). net_state: 'online'|'limited'|'offline'|'unknown'|None.
    `error` (US-38): header text of an actionable problem; wins over everything but 'running'."""
    if running:
        return "running", "Updating…"
    if error:
        return "error", error
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
