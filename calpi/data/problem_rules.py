"""When and where problems are shown (US-38). Pure, no gi imports.

Problems are collected from the sync status (US-18), startup notices (US-12/13), network/clock state
(US-17) and device checks (US-31). The banner shows at most one (highest priority, after its grace
period, not dismissed, never during the setup wizard); the header shows only `error` severity ones.
Short outages stay quiet: the header's subtle "Offline" covers them (grace periods live in messages).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from calpi.data import messages
from calpi.data.settings_store import K_DISMISSED_PROBLEMS

DISMISS_FOR = timedelta(hours=24)
BANNER_INFO = {"DB_RESET"}                       # info-level problems that still get the banner
NETWORKISH = {"NETWORK_DOWN", "DNS_FAILED"}      # folded into the single OFFLINE problem


@dataclass(frozen=True)
class Problem:
    code: str
    since: datetime
    account_id: str | None = None
    account: str = ""                            # display name for {account}
    provider: str = "iCloud"

    @property
    def signature(self) -> str:
        return f"{self.code}|{self.account_id or ''}"


@dataclass(frozen=True)
class ProblemInputs:
    snapshot: object | None = None               # sync_status.StatusSnapshot
    startup_notices: tuple[str, ...] = ()        # 'safe_mode' | 'db_reset' | 'credentials_unreadable'
    started_at: datetime | None = None           # process start: a later successful sync clears DB_RESET
    offline_since: datetime | None = None        # network down / sync offline (None = online)
    clock_unsynced_since: datetime | None = None
    device_codes: tuple[str, ...] = ()           # POWER_UNDERVOLTAGE, TEMP_HIGH, ... (since = now)
    account_info: dict = field(default_factory=dict)   # account_id -> (provider display name, account label)


_NOTICE_CODES = {"safe_mode": "SAFE_MODE", "db_reset": "DB_RESET",
                 "credentials_unreadable": "CREDENTIALS_UNREADABLE"}


def collect(inp: ProblemInputs, now: datetime) -> list[Problem]:
    out: list[Problem] = []
    snap = inp.snapshot
    offline_since = inp.offline_since
    db_reset = "db_reset" in inp.startup_notices
    for st in (snap.accounts if snap is not None else ()):
        if (inp.started_at and st.last_success_at and st.last_success_at >= inp.started_at):
            db_reset = False
        code = messages.classify_account_problem(st)
        if not code:
            continue
        since = st.failing_since or st.last_error_at or now
        if code in NETWORKISH:
            offline_since = min(offline_since, since) if offline_since else since
            continue
        provider, label = inp.account_info.get(st.account_id, ("iCloud", ""))
        out.append(Problem(code, since, st.account_id, label, provider))
    if offline_since is not None:
        out.append(Problem("OFFLINE", offline_since))
    if inp.clock_unsynced_since is not None:
        out.append(Problem("CLOCK_UNSYNCED", inp.clock_unsynced_since))
    for n in inp.startup_notices:
        code = _NOTICE_CODES.get(n)
        if code == "DB_RESET":
            if db_reset:
                out.append(Problem(code, inp.started_at or now))
        elif code and not any(p.code == code for p in out):
            out.append(Problem(code, inp.started_at or now))
    if "credentials_unreadable" in inp.startup_notices:
        # unreadable credentials make every account fail with sign-in errors: show the root cause only
        out = [p for p in out if p.code not in ("AUTH_FAILED", "AUTH_REVOKED")]
    for code in inp.device_codes:
        out.append(Problem(code, now))
    out.sort(key=lambda p: messages.priority_rank(p.code))
    return out


def _shown_in_banner(p: Problem) -> bool:
    e = messages.entry_for(p.code)
    return e.severity in ("warning", "error") or p.code in BANNER_INFO


def is_dismissed(p: Problem, dismissed: dict, now: datetime) -> bool:
    t = dismissed.get(p.signature)
    return t is not None and now - _as_dt(t, now) < DISMISS_FOR


def _as_dt(t, now: datetime) -> datetime:
    return t if isinstance(t, datetime) else datetime.fromtimestamp(t, now.tzinfo)


def visible_banner(problems: list[Problem], now: datetime, dismissed: dict, in_wizard: bool) -> Problem | None:
    """The one problem to show in the banner slot (or None). `dismissed`: {signature: datetime|unix s}."""
    if in_wizard:
        return None
    best = None
    for p in problems:
        if not _shown_in_banner(p) or now - p.since < timedelta(seconds=messages.entry_for(p.code).grace_s):
            continue
        if is_dismissed(p, dismissed, now):
            continue
        if best is None or messages.priority_rank(p.code) < messages.priority_rank(best.code):
            best = p
    return best


def header_problem(problems: list[Problem], now: datetime, in_wizard: bool) -> Problem | None:
    """The actionable (severity `error`) problem for the header indicator, after its grace period."""
    if in_wizard:
        return None
    best = None
    for p in problems:
        e = messages.entry_for(p.code)
        if e.severity != "error" or now - p.since < timedelta(seconds=e.grace_s):
            continue
        if best is None or messages.priority_rank(p.code) < messages.priority_rank(best.code):
            best = p
    return best


class Dismissals:
    """Dismissed problem signatures: in memory plus the settings key (pruned after 24 h)."""

    def __init__(self, settings=None, key: str = K_DISMISSED_PROBLEMS):
        self._settings, self._key = settings, key
        self.items: dict[str, float] = dict(settings.get(key)) if settings is not None else {}

    def dismiss(self, p: Problem, now: datetime) -> None:
        self.items[p.signature] = now.timestamp()
        self._save(now)

    def prune(self, now: datetime) -> None:
        keep = {s: t for s, t in self.items.items() if now.timestamp() - t < DISMISS_FOR.total_seconds()}
        if keep != self.items:
            self.items = keep
            self._save(now)

    def _save(self, now: datetime) -> None:
        if self._settings is not None:
            try:
                self._settings.set(self._key, dict(self.items))
            except Exception:
                pass
