from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

import pytest

from calpi.data.credentials import Secret
from calpi.data.event_store import EventStore
from calpi.data.models import Account
from calpi.sync import fetch, icloud
from calpi.sync.errors import ErrorCode, SyncError
from calpi.sync.http import HttpClient

BER = ZoneInfo("Europe/Berlin")
FX = Path(__file__).parent / "fixtures"
HOME = "https://p42-caldav.icloud.com:443/1234567890/calendars/"
WORK = HOME + "work/"
HOMECAL = HOME + "home/"
NOCOMP = HOME + "nocomp/"      # third event calendar in calendars.xml ("Unspecified")
PW = Secret("abcd-efgh-ijkl-mnop")
TODAY = date(2026, 3, 15)
WINDOW = fetch.compute_window(TODAY, BER, 2, 12)

ACC = Account(id="icloud-t1", provider="icloud", username="me@icloud.com", display_name="Me",
              server_url="https://caldav.icloud.com/", principal_url="x", calendar_home_url=HOME,
              created_at="2026-01-01T00:00:00+00:00")


def ics(uid, summary, start="20260310T100000Z", end="20260310T110000Z"):
    return (f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\nUID:{uid}\nSUMMARY:{summary}\n"
            f"DTSTART:{start}\nDTEND:{end}\nEND:VEVENT\nEND:VCALENDAR\n")


def multistatus(resources):
    body = "".join(f"<d:response><d:href>/r{i}.ics</d:href><d:propstat><d:prop><d:getetag>\"e\"</d:getetag>"
                   f"<c:calendar-data>{escape(r)}</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status>"
                   f"</d:propstat></d:response>" for i, r in enumerate(resources))
    return (f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f"{body}</d:multistatus>").encode()


class Fake:
    def __init__(self, reports=None, propfind=None):
        self.reports = reports or {WORK: multistatus([ics("w1", "Work thing")]),
                                   HOMECAL: multistatus([ics("h1", "Home thing")]),
                                   NOCOMP: multistatus([])}
        self.propfind = propfind if propfind is not None else (FX / "icloud" / "calendars.xml").read_bytes()
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        if method == "PROPFIND":
            r = self.propfind
        else:
            r = self.reports[url]
        if isinstance(r, BaseException):
            raise r
        return r if isinstance(r, tuple) else (207, {}, r)

    def reports_sent(self):
        return [c for c in self.calls if c[0] == "REPORT"]


@pytest.fixture
def store(tmp_path):
    return EventStore(tmp_path / "t.sqlite3")


def run(store, fake, **kw):
    c = HttpClient(allowed_auth_hosts=icloud.ALLOWED, transport=fake)
    return fetch.sync_account(ACC, PW, store, kw.pop("window", WINDOW), client=c, tz=BER, **kw)


def by_name(res):
    return {c.name: c for c in res.calendars}


def test_compute_window():
    w = fetch.compute_window(date(2026, 3, 15), BER, 2, 12)
    assert w == (datetime(2026, 1, 1, tzinfo=BER).astimezone(timezone.utc),
                 datetime(2027, 4, 1, tzinfo=BER).astimezone(timezone.utc))
    assert w[0] == datetime(2025, 12, 31, 23, tzinfo=timezone.utc)
    # year wrap and extra range
    w = fetch.compute_window(date(2026, 1, 5), BER, 2, 12, extra=(date(2028, 1, 1), date(2028, 3, 1)))
    assert w[0] == datetime(2025, 11, 1, tzinfo=BER).astimezone(timezone.utc)
    assert w[1] == datetime(2028, 3, 1, tzinfo=BER).astimezone(timezone.utc)
    w = fetch.compute_window(date(2026, 6, 1), BER, 0, 1, extra=(date(2026, 7, 1), date(2026, 7, 2)))
    assert w[0] == datetime(2026, 6, 1, tzinfo=BER).astimezone(timezone.utc)
    assert w[1] == datetime(2026, 8, 1, tzinfo=BER).astimezone(timezone.utc)


def test_calendar_id_stable_and_slash_insensitive():
    a = fetch.calendar_id_for("acc", "https://x/y/")
    assert a == fetch.calendar_id_for("acc", "https://x/y")
    assert a.startswith("acc:") and len(a) == len("acc:") + 16


def test_first_sync_stores_events_and_state(store):
    fake = Fake()
    res = run(store, fake)
    assert res.error is None
    r = by_name(res)
    assert r["Work"].status == "ok" and r["Work"].events == 1 and r["Home"].events == 1
    assert store.count_events() == 2
    cid = fetch.calendar_id_for(ACC.id, WORK)
    ctag, tok, ws, we = store.sync_state(cid)
    assert ctag == "ctag-work-1" and tok and ws == int(WINDOW[0].timestamp()) and we == int(WINDOW[1].timestamp())
    m, url, hdrs, body = fake.reports_sent()[0]
    assert hdrs["Depth"] == "1" and b"time-range" in body
    assert b'start="20251231T230000Z"' in body and b'end="20270331T220000Z"' in body
    assert [c[2]["Depth"] for c in fake.calls if c[0] == "PROPFIND"] == ["1"]


def test_unchanged_ctag_skips_report(store):
    run(store, Fake())
    fake = Fake()
    res = run(store, fake)
    r = by_name(res)
    assert r["Work"].status == r["Home"].status == "unchanged"
    assert r["Unspecified"].status == "ok"          # server gives it no ctag: always fetched
    assert [c[1] for c in fake.reports_sent()] == [NOCOMP] and store.count_events() == 2


def test_force_ignores_ctag(store):
    run(store, Fake())
    fake = Fake()
    res = run(store, fake, force=True)
    assert {c.status for c in res.calendars} == {"ok"} and len(fake.reports_sent()) == 3


def test_changed_ctag_refetches_and_replaces(store):
    run(store, Fake())
    cid = fetch.calendar_id_for(ACC.id, WORK)
    store.conn.execute("UPDATE calendars SET ctag='old' WHERE id=?", (cid,))
    store.conn.commit()
    fake = Fake(reports={WORK: multistatus([ics("w2", "New"), ics("w3", "New2")]),
                         HOMECAL: multistatus([]), NOCOMP: multistatus([])})
    res = run(store, fake)
    r = by_name(res)
    assert r["Work"].status == "ok" and r["Work"].events == 2 and r["Home"].status == "unchanged"
    assert len(fake.reports_sent()) == 2      # Work + the ctag-less calendar
    assert store.sync_state(cid)[0] == "ctag-work-1"


def test_stored_window_smaller_than_requested_refetches(store):
    small = fetch.compute_window(TODAY, BER, 0, 1)
    run(store, Fake(), window=small)
    fake = Fake()
    res = run(store, fake)                      # bigger window, same ctag
    assert {c.status for c in res.calendars} == {"ok"} and len(fake.reports_sent()) == 3


def test_one_calendar_failing_leaves_others_and_store(store):
    run(store, Fake())
    store.conn.execute("UPDATE calendars SET ctag='old'")
    store.conn.commit()
    fake = Fake(reports={WORK: (503, {"Retry-After": "60"}, b""),
                         HOMECAL: multistatus([ics("h9", "Home new")]), NOCOMP: multistatus([])})
    res = run(store, fake)
    r = by_name(res)
    assert r["Work"].status == "error" and r["Work"].error is ErrorCode.RATE_LIMITED
    assert r["Home"].status == "ok"
    cid = fetch.calendar_id_for(ACC.id, WORK)
    assert [e.summary for e in store.events_for_days(date(2026, 3, 1), date(2026, 4, 1), BER)
            if e.calendar_id == cid] == ["Work thing"]
    assert store.sync_state(cid)[0] == "old"


def test_unexpected_exception_is_unknown(store, monkeypatch):
    monkeypatch.setattr(fetch, "parse_resources", lambda *a, **k: 1 / 0)
    res = run(store, Fake())
    assert {c.error for c in res.calendars} == {ErrorCode.UNKNOWN}


def test_all_resources_unparseable_is_parse_error_and_store_unchanged(store):
    run(store, Fake())
    store.conn.execute("UPDATE calendars SET ctag='old'")
    store.conn.commit()
    bad = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:garbage\n"
    fake = Fake(reports={WORK: multistatus([bad]), HOMECAL: multistatus([bad, ics("h1", "ok")]), NOCOMP: multistatus([])})
    r = by_name(run(store, fake))
    assert r["Work"].error is ErrorCode.PARSE_ERROR
    assert r["Home"].status == "ok" and r["Home"].stats.parse_errors == 1
    assert store.count_events() == 2 and store.sync_state(fetch.calendar_id_for(ACC.id, WORK))[0] == "old"


def test_calendar_removed_on_server_is_deleted(store):
    run(store, Fake())
    keep = fetch.calendar_id_for(ACC.id, WORK)
    xml = (FX / "icloud" / "calendars.xml").read_bytes().decode()
    # drop the 'home' calendar from the listing
    start = xml.index("<response>", xml.index("/calendars/work/") + 1)
    end = xml.index("</response>", start) + len("</response>")
    fake = Fake(propfind=(xml[:start] + xml[end:]).encode())
    res = run(store, fake)
    assert sorted(c.name for c in res.calendars) == ["Unspecified", "Work"]
    assert keep in [c.id for c in store.calendars_for_account(ACC.id)]
    assert len(store.calendars_for_account(ACC.id)) == 2


def test_propfind_failure_deletes_nothing(store):
    run(store, Fake())
    res = run(store, Fake(propfind=SyncError(ErrorCode.NETWORK_DOWN, "down")))
    assert res.error is ErrorCode.NETWORK_DOWN and res.calendars == []
    assert len(store.calendars_for_account(ACC.id)) == 3 and store.count_events() == 2


def test_auth_failure_at_propfind(store):
    res = run(store, Fake(propfind=(401, {}, b"")))
    assert res.error is ErrorCode.AUTH_FAILED and store.list_calendars() == []


def test_home_404_rediscovers(store):
    fake = Fake()
    calls = []
    orig = fake.__call__

    def routed(method, url, headers, body):
        calls.append((method, url))
        if method == "PROPFIND" and url == HOME and sum(1 for c in calls if c == ("PROPFIND", HOME)) == 1:
            return 404, {}, b""
        if method == "PROPFIND" and url == "https://caldav.icloud.com/":
            return 207, {}, (FX / "icloud" / "root_principal.xml").read_bytes()
        if method == "PROPFIND" and url.endswith("/principal/"):
            return 207, {}, (FX / "icloud" / "principal_home.xml").read_bytes()
        return orig(method, url, headers, body)
    c = HttpClient(allowed_auth_hosts=icloud.ALLOWED, transport=routed)
    res = fetch.sync_account(ACC, PW, store, WINDOW, client=c, tz=BER)
    assert res.error is None and len(res.calendars) == 3


def test_upsert_keeps_user_owned_fields(store):
    run(store, Fake())
    cid = fetch.calendar_id_for(ACC.id, WORK)
    store.set_calendar_overrides(cid, user_name="Mine", hidden=True, sort_order=7)
    run(store, Fake(), force=True)
    c = store.get_calendar(cid)
    assert (c.user_name, c.hidden, c.sort_order) == ("Mine", True, 7)


def test_apply_calendar_sync_is_transactional(store, monkeypatch):
    run(store, Fake())
    cid = fetch.calendar_id_for(ACC.id, WORK)
    before = store.sync_state(cid)
    real = store.conn

    class Boom:
        """Proxy connection whose UPDATE (the set-state step) fails after events were replaced."""
        def __getattr__(self, n):
            return getattr(real, n)

        def execute(self, sql, *a):
            if sql.lstrip().startswith("UPDATE calendars SET ctag"):
                raise RuntimeError("boom")
            return real.execute(sql, *a)
    store.conn = Boom()
    from calpi.data.models import Event
    ev = Event(calendar_id=cid, uid="z", summary="Z", all_day=True, start=date(2026, 3, 1), end=date(2026, 3, 2))
    with pytest.raises(RuntimeError):
        store.apply_calendar_sync(cid, [ev], "new", None, WINDOW)
    store.conn = real
    assert store.sync_state(cid) == before
    assert [e.summary for e in store.events_for_days(date(2026, 3, 1), date(2026, 4, 1), BER)
            if e.calendar_id == cid] == ["Work thing"]


def test_sync_state_unknown_calendar(store):
    assert store.sync_state("nope") == (None, None, None, None)


def test_ui_modules_do_not_reference_icalendar():
    root = Path(__file__).parent.parent / "calpi"
    for sub in ["widgets", "app.py"]:
        p = root / sub
        files = list(p.rglob("*.py")) if p.is_dir() else [p]
        for f in files:
            t = f.read_text()
            assert "icalendar" not in t and "ical_parse" not in t, f
