import pytest

from calpi.sync import retry
from calpi.sync.retry import RetryPolicy, classify, is_offline
from calpi.system.netstate import NetState, map_state


def seq(interval_min, n=7, kind="transient", retry_after=None):
    p = RetryPolicy()
    return [p.next_delay(kind, retry_after, interval_min * 60) for _ in range(n)]


def test_sequences():
    assert seq(5) == [60, 120, 240, 300, 300, 300, 300]
    assert seq(15) == [60, 120, 240, 480, 900, 900, 900]
    assert seq(60) == [60, 120, 240, 480, 900, 900, 900]
    assert seq(1) == [60] * 7


def test_reset_on_success_and_permanent():
    p = RetryPolicy()
    p.next_delay("transient", None, 900)
    p.next_delay("transient", None, 900)
    assert p.next_delay("success", None, 900) == 900 and p.failures == 0
    assert p.next_delay("transient", None, 900) == 60
    assert p.next_delay("permanent", None, 900) == 900 and p.failures == 0
    assert p.next_delay("mixed", None, 900) == 900


def test_retry_after():
    p = RetryPolicy()
    assert p.next_delay("transient", 1800, 900) == 1800
    assert p.next_delay("transient", 10, 900) == 120
    assert p.next_delay("transient", 99999, 900) == 3600


def acc(*errs, ra=None):
    return {"status": "done", "accounts": [{"error": e, "retry_after": ra} for e in errs]}


def test_classify():
    assert classify(acc(None)) == "success"
    assert classify({"status": "done", "accounts": []}) == "success"
    assert classify(acc(None, "NETWORK_DOWN")) == "success"
    assert classify(acc("NETWORK_DOWN", "SERVER_ERROR")) == "transient"
    assert classify(acc("AUTH_FAILED")) == "permanent"
    assert classify(acc("NETWORK_DOWN", "AUTH_FAILED")) == "permanent"
    assert classify({"status": "crashed", "accounts": []}) == "transient"


def test_is_offline_and_retry_after():
    assert is_offline(acc("DNS_FAILED", "TIMEOUT"))
    assert not is_offline(acc("SERVER_ERROR"))
    assert not is_offline(acc(None, "TIMEOUT"))
    assert not is_offline({"accounts": []})
    assert retry.max_retry_after(acc("RATE_LIMITED", "TIMEOUT", ra=30)) == 30
    assert retry.max_retry_after(acc(None)) is None


@pytest.mark.parametrize("n,state", [(70, NetState.ONLINE), (60, NetState.LIMITED), (50, NetState.LIMITED),
                                     (40, NetState.OFFLINE), (20, NetState.OFFLINE), (10, NetState.OFFLINE),
                                     (0, NetState.UNKNOWN)])
def test_map_state(n, state):
    assert map_state(n) is state
