"""Overall verdict and plain-language lines for the Status screen (US-31). No gi imports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from calpi.data import formatting, messages

STALE_AFTER = timedelta(hours=6)
FAILING_MIN = 3

GREEN, AMBER, RED = "ok", "warn", "bad"


@dataclass(frozen=True)
class StatusInputs:
    power_problem: bool = False              # under-voltage right now
    safe_mode: bool = False
    credentials_unreadable: bool = False
    auth_failed: bool = False                # any account AUTH_FAILED
    no_accounts: bool = False
    offline: bool = False                    # network down / no internet
    clock_unsynced: bool = False
    failing_since: datetime | None = None    # first-known time of a non-auth failure streak >= FAILING_MIN
    failing_provider: str = "iCloud"
    last_success: datetime | None = None
    has_accounts: bool = True
    db_reset: bool = False


@dataclass(frozen=True)
class Verdict:
    level: str                               # "ok" | "warn" | "bad"
    text: str
    fix_section: str | None = None


def _hhmm(t: datetime | None, now: datetime) -> str:
    return formatting.short_time(t.astimezone(now.tzinfo)) if t else ""


def summarize(i: StatusInputs, now: datetime) -> Verdict:
    """Highest priority wins (D1)."""
    if i.power_problem:
        m = messages.describe("POWER_UNDERVOLTAGE")
        return Verdict(RED, f"{m.title} — {m.detail}")
    if i.safe_mode:
        m = messages.describe("SAFE_MODE")
        return Verdict(RED, m.title)
    if i.credentials_unreadable or i.auth_failed:
        return Verdict(RED, f"{i.failing_provider} needs you to sign in again", "accounts")
    if i.no_accounts:
        m = messages.describe("NO_ACCOUNTS")
        return Verdict(AMBER, f"{m.title} — add one in Settings → Accounts", m.fix_section)
    if i.offline:
        text = "calpi is offline"
        if i.last_success:
            text += f" · Showing events from {_hhmm(i.last_success, now)}"
        return Verdict(AMBER, text, "network")
    if i.clock_unsynced:
        return Verdict(AMBER, "Clock not set yet \u2014 needs internet", "network")
    if i.failing_since is not None:
        return Verdict(AMBER, f"Couldn't reach {i.failing_provider} since {_hhmm(i.failing_since, now)}")
    if i.has_accounts and i.last_success is not None and now - i.last_success > STALE_AFTER:
        return Verdict(AMBER, f"Calendars haven't updated since {formatting.relative_datetime(i.last_success, now)}")
    if i.db_reset:
        return Verdict(AMBER, messages.describe("DB_RESET").title)
    text = "Everything is working"
    if i.last_success:
        text += f" · Updated {_hhmm(i.last_success, now)}"
    return Verdict(GREEN, text)


def account_line(st, now: datetime, provider: str = "iCloud") -> str:
    """One plain line for an account's sync state (st: sync_status.AccountStatus | None)."""
    if st is None or st.last_attempt_at is None:
        return "Waiting for the first update"
    if not st.last_error_code:
        return "Up to date"
    if st.last_error_code in ("AUTH_FAILED", "CREDENTIALS_UNREADABLE"):
        return "Sign-in problem"
    m = messages.describe(st.last_error_code, provider=provider)
    n = st.consecutive_failures
    tries = f" ({n} tries)" if n > 1 else ""
    if st.last_error_code in ("NETWORK_DOWN", "DNS_FAILED", "TIMEOUT"):
        return f"Couldn't reach {provider} at {_hhmm(st.last_error_at, now)}{tries}"
    return f"{m.title} at {_hhmm(st.last_error_at, now)}{tries}"


_REASONS = {
    "startup": "at start", "interval": "scheduled", "manual": "manual", "day-changed": "new day",
    "tz-changed": "time zone changed", "account-added": "account added",
    "network-connected": "network came back", "network-up": "network came back",
}


def reason_text(reason: str | None) -> str:
    parts = (reason or "").removeprefix("coalesced:").split(",")
    for p in parts:                       # a merged run shows the most user-visible reason
        if p == "manual":
            return _REASONS["manual"]
    return _REASONS.get(parts[0], "scheduled" if not parts[0] else parts[0].replace("-", " "))


def run_result(run) -> str:
    if run.status != "done":
        return "didn't finish"
    if run.accounts_failed and not run.accounts_ok:
        return "problem"
    if run.accounts_failed:
        return "partly"
    return "OK"


def run_line(run, now: datetime) -> str:
    """'Today 14:05 · scheduled · OK · 3 s'"""
    secs = (run.duration_ms or 0) / 1000
    dur = f"{secs:.0f} s" if secs >= 1 else "<1 s"
    return f"{formatting.relative_datetime(run.finished_at, now)} · {reason_text(run.reason)} " \
           f"· {run_result(run)} · {dur}"
