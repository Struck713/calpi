from datetime import datetime, timedelta, timezone

from calpi.data import messages, status_summary as ss
from calpi.data.status_summary import StatusInputs, summarize
from calpi.data.sync_status import AccountStatus, RunRecord

NOW = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)
OK_AT = NOW - timedelta(minutes=55)


def v(**kw):
    kw.setdefault("last_success", OK_AT)
    return summarize(StatusInputs(**kw), NOW)


def test_green():
    r = v()
    assert r.level == "ok" and r.text.startswith("Everything is working") and "14:05" in r.text


def test_each_level_in_priority_order():
    order = [
        ("power_problem", "bad"), ("safe_mode", "bad"), ("auth_failed", "bad"),
        ("no_accounts", "warn"), ("offline", "warn"), ("clock_unsynced", "warn"),
        ("failing_since", "warn"), ("db_reset", "warn"),
    ]
    vals = {"failing_since": OK_AT}
    kinds = []
    for i, (k, lvl) in enumerate(order):
        # everything at or below this one is on: the topmost wins
        kw = {name: vals.get(name, True) for name, _ in order[i:]}
        r = v(**kw)
        kinds.append((k, r.level))
        assert r.level == lvl, k
    assert v(power_problem=True, safe_mode=True).text.startswith("The power supply is too weak")
    assert v(safe_mode=True, auth_failed=True).text == messages.describe("SAFE_MODE").title


def test_texts_and_fix_targets():
    assert v(auth_failed=True).fix_section == "accounts"
    assert "sign in again" in v(credentials_unreadable=True).text
    assert v(no_accounts=True).fix_section == "accounts"
    o = v(offline=True)
    assert o.text == "calpi is offline · Showing events from 14:05" and o.fix_section == "network"
    assert "since 09:12" in v(failing_since=NOW.replace(hour=9, minute=12)).text


def test_stale_and_no_accounts_not_stale():
    old = NOW - timedelta(hours=7)
    assert v(last_success=old).level == "warn"
    assert v(last_success=old, has_accounts=False).level == "ok"


def test_account_line():
    a = lambda **k: AccountStatus("a", NOW, k.get("ok"), k.get("code"), None, NOW if k.get("code") else None,
                                  k.get("n", 0))
    assert ss.account_line(None, NOW) == "Waiting for the first update"
    assert ss.account_line(a(ok=NOW), NOW) == "Up to date"
    assert ss.account_line(a(code="AUTH_FAILED", n=1), NOW) == "Sign-in problem"
    assert ss.account_line(a(code="NETWORK_DOWN", n=3), NOW) == "Couldn't reach iCloud at 15:00 (3 tries)"


def test_run_line():
    r = RunRecord(1, NOW, NOW, "coalesced:interval,manual", "done", 3400, 1, 0, True)
    assert ss.run_line(r, NOW) == "Today 15:00 · manual · OK · 3 s"
    r = RunRecord(1, NOW, NOW, "network-connected", "done", 200, 0, 1, False)
    assert "network came back" in ss.run_line(r, NOW) and "problem" in ss.run_line(r, NOW)


def test_describe_fallback_and_codes():
    for c in ("POWER_UNDERVOLTAGE", "POWER_THROTTLED_PAST", "TEMP_HIGH", "DISK_LOW", "SAFE_MODE", "DB_RESET",
              "CREDENTIALS_UNREADABLE", "CLOCK_UNSYNCED", "NO_ACCOUNTS", "AUTH_FAILED", "NETWORK_DOWN"):
        assert messages.describe(c).title
    assert messages.describe("???").title == messages.describe("UNKNOWN").title
