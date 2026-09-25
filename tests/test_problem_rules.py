from datetime import datetime, timedelta, timezone

from calpi.data import problem_rules as pr
from calpi.data.sync_status import AccountStatus, StatusSnapshot

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)


def acct(code, since_ago, ok_before=True, aid="a"):
    since = NOW - since_ago
    return AccountStatus(aid, NOW, since - timedelta(hours=1) if ok_before else None, code, None, NOW, 3,
                         failing_since=since)


def inputs(**kw):
    return pr.ProblemInputs(**kw)


def banner(problems, dismissed=None, wizard=False, now=NOW):
    return pr.visible_banner(problems, now, dismissed or {}, wizard)


def test_offline_grace():
    p = pr.collect(inputs(offline_since=NOW - 29 * MIN), NOW)
    assert banner(p) is None
    p = pr.collect(inputs(offline_since=NOW - 31 * MIN), NOW)
    assert banner(p).code == "OFFLINE"


def test_network_account_errors_fold_into_offline():
    snap = StatusSnapshot(accounts=(acct("NETWORK_DOWN", 40 * MIN), acct("DNS_FAILED", 50 * MIN, aid="b")))
    p = pr.collect(inputs(snapshot=snap), NOW)
    assert [x.code for x in p] == ["OFFLINE"] and p[0].since == NOW - 50 * MIN
    assert banner(p).code == "OFFLINE"


def test_revoked_shown_at_once_and_priority_over_offline():
    snap = StatusSnapshot(accounts=(acct("AUTH_FAILED", 1 * MIN),))
    p = pr.collect(inputs(snapshot=snap, offline_since=NOW - 3 * 60 * MIN), NOW)
    assert banner(p).code == "AUTH_REVOKED"
    assert pr.header_problem(p, NOW, False).code == "AUTH_REVOKED"


def test_never_succeeded_is_auth_failed():
    snap = StatusSnapshot(accounts=(acct("AUTH_FAILED", 1 * MIN, ok_before=False),))
    assert pr.collect(inputs(snapshot=snap), NOW)[0].code == "AUTH_FAILED"


def test_server_error_needs_an_hour():
    snap = StatusSnapshot(accounts=(acct("SERVER_ERROR", 59 * MIN),))
    assert banner(pr.collect(inputs(snapshot=snap), NOW)) is None
    snap = StatusSnapshot(accounts=(acct("SERVER_ERROR", 61 * MIN),))
    assert banner(pr.collect(inputs(snapshot=snap), NOW)).code == "SERVER_ERROR"


def test_dismissal_by_signature_and_expiry():
    snap = StatusSnapshot(accounts=(acct("AUTH_FAILED", 5 * MIN),))
    p = pr.collect(inputs(snapshot=snap), NOW)
    top = banner(p)
    d = {top.signature: (NOW - 2 * 60 * MIN).timestamp()}
    assert banner(p, d) is None
    # a different problem is not hidden by that dismissal
    p2 = pr.collect(inputs(snapshot=snap, device_codes=("POWER_UNDERVOLTAGE",)), NOW)
    assert banner(p2, d).code == "POWER_UNDERVOLTAGE"
    # a different account is a different signature
    snap2 = StatusSnapshot(accounts=(acct("AUTH_FAILED", 5 * MIN, aid="b"),))
    assert banner(pr.collect(inputs(snapshot=snap2), NOW), d) is not None
    # 24 hours later it comes back
    assert banner(p, d, now=NOW + timedelta(hours=25)) is not None


def test_header_only_for_error_severity():
    p = pr.collect(inputs(offline_since=NOW - 3 * 60 * MIN), NOW)
    assert pr.header_problem(p, NOW, False) is None
    p = pr.collect(inputs(device_codes=("POWER_UNDERVOLTAGE",)), NOW)
    assert pr.header_problem(p, NOW, False).code == "POWER_UNDERVOLTAGE"
    p = pr.collect(inputs(clock_unsynced_since=NOW - 10 * MIN), NOW)
    assert pr.header_problem(p, NOW, False) is None
    p = pr.collect(inputs(clock_unsynced_since=NOW - 16 * MIN), NOW)
    assert pr.header_problem(p, NOW, False).code == "CLOCK_UNSYNCED"


def test_wizard_suppresses_everything():
    p = pr.collect(inputs(startup_notices=("safe_mode",)), NOW)
    assert banner(p).code == "SAFE_MODE" and pr.header_problem(p, NOW, False).code == "SAFE_MODE"
    assert banner(p, wizard=True) is None and pr.header_problem(p, NOW, True) is None


def test_db_reset_info_banner_clears_after_success():
    started = NOW - 5 * MIN
    p = pr.collect(inputs(startup_notices=("db_reset",), started_at=started), NOW)
    assert banner(p).code == "DB_RESET"
    ok = AccountStatus("a", NOW, NOW - MIN, None, None, None, 0)
    p = pr.collect(inputs(startup_notices=("db_reset",), started_at=started,
                          snapshot=StatusSnapshot(accounts=(ok,))), NOW)
    assert banner(p) is None


def test_credentials_unreadable_hides_derived_auth_errors():
    snap = StatusSnapshot(accounts=(acct("AUTH_FAILED", 5 * MIN),))
    p = pr.collect(inputs(snapshot=snap, startup_notices=("credentials_unreadable",)), NOW)
    assert [x.code for x in p] == ["CREDENTIALS_UNREADABLE"]


def test_dismissals_persist_and_prune():
    class S:
        d = {}
        def get(self, k): return dict(self.d)
        def set(self, k, v): self.d = v; return True
    s = S()
    dm = pr.Dismissals(s)
    p = pr.Problem("OFFLINE", NOW)
    dm.dismiss(p, NOW)
    assert p.signature in s.d
    dm.prune(NOW + timedelta(hours=25))
    assert s.d == {}
