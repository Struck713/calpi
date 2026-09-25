from calpi.data import sync_text as st
from calpi.tasks import CallbackList


def res(*errs, reason="manual", status="done"):
    return {"status": status, "reason": reason,
            "accounts": [{"account_id": f"a{i}", "error": e} for i, e in enumerate(errs)]}


def test_manual_texts():
    t = st.manual_result_text
    assert t(res("NETWORK_DOWN", "DNS_FAILED")) == "Couldn't update: offline"
    assert t(res("NETWORK_DOWN", "AUTH_FAILED")) == "Couldn't update: sign-in problem"
    assert t(res("CREDENTIALS_UNREADABLE")) == "Couldn't update: sign-in problem"
    assert t(res("SERVER_ERROR"), {"a0": "iCloud"}) == "Couldn't update: iCloud not responding"
    assert t(res("TIMEOUT")) == "Couldn't update: server not responding"
    assert t(res("PARSE_ERROR")) == "Couldn't update"
    assert t(res()) == "Couldn't update"


def test_reason_and_success():
    assert st.is_manual(res(reason="manual"))
    assert st.is_manual(res(reason="coalesced:interval,manual"))
    assert not st.is_manual(res(reason="interval"))
    assert not st.is_manual(res(reason="manual-ish"))
    assert st.is_success(res(None)) and st.is_success(res(None, "AUTH_FAILED"))
    assert not st.is_success(res("AUTH_FAILED")) and not st.is_success(res(status="crashed"))


def test_callback_list():
    calls = []
    cl = CallbackList()
    h = cl.add(lambda x: calls.append(("a", x)))
    cl.add(lambda x: 1 / 0)
    cl.add(lambda x: calls.append(("c", x)))
    cl.call(1)
    assert calls == [("a", 1), ("c", 1)]
    cl.remove(h)
    cl.remove(h)
    cl.call(2)
    assert calls[-1] == ("c", 2) and ("a", 2) not in calls


def test_merge_keeps_manual_visible():
    from calpi.sync_engine import Request
    m = Request("interval").merge(Request("manual"))
    assert st.is_manual({"reason": m.reason})
    m = m.merge(Request("day-changed"))
    assert st.is_manual({"reason": m.reason})
