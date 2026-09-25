"""Retry policy (US-17). Pure, no gi. Decides how long to wait after a sync run."""
from __future__ import annotations

TRANSIENT = {"NETWORK_DOWN", "DNS_FAILED", "TIMEOUT", "SERVER_ERROR", "RATE_LIMITED"}
NETWORKISH = {"NETWORK_DOWN", "DNS_FAILED", "TIMEOUT"}
STEPS = [60, 120, 240, 480, 900]
MIN_DELAY_S = 60


def classify(result: dict) -> str:
    """'success' | 'transient' | 'permanent'. Some account fine (mixed) counts as success."""
    if result.get("status") != "done":
        return "transient"
    accs = result.get("accounts") or []
    if not accs:
        return "success"
    errs = [a.get("error") for a in accs]
    if any(e is None for e in errs):
        return "success"
    if all(e in TRANSIENT for e in errs):
        return "transient"
    return "permanent"


def is_offline(result: dict) -> bool:
    accs = result.get("accounts") or []
    return bool(accs) and all(a.get("error") in NETWORKISH for a in accs)


def max_retry_after(result: dict) -> int | None:
    vals = [a.get("retry_after") for a in result.get("accounts") or [] if a.get("retry_after")]
    return int(max(vals)) if vals else None


class RetryPolicy:
    def __init__(self):
        self.failures = 0

    def reset(self) -> None:
        self.failures = 0

    def next_delay(self, kind: str, retry_after: int | None, interval_s: int) -> int:
        if kind in ("success", "mixed", "permanent"):
            self.failures = 0
            return interval_s
        step = STEPS[self.failures] if self.failures < len(STEPS) else 900
        self.failures += 1
        delay = max(MIN_DELAY_S, min(step, interval_s))
        if retry_after:
            delay = max(delay, min(int(retry_after), 3600))
        return delay
