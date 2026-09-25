import logging
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from calpi.data.credentials import CredentialStore, Secret
from calpi.data.event_store import EventStore
from calpi.data.models import Account
from calpi.data.settings_store import SettingsStore
from calpi.sync import cli, fetch, providers
from calpi.sync.errors import ErrorCode, SyncError
from calpi.sync.http import HttpClient
from calpi.sync.provider_ics import normalize_feed
from tests.test_fetch import ics, multistatus

BER = ZoneInfo("Europe/Berlin")
WINDOW = fetch.compute_window(date(2026, 3, 15), BER, 2, 12)
FEED = "https://calendar.example.org/private/abc123secret/basic.ics"
FIX = Path(__file__).parent / "fixtures" / "caldav"


def dav(body):
    return (207, {}, body.encode())


PRINCIPAL = ('<d:multistatus xmlns:d="DAV:"><d:response><d:href>/</d:href><d:propstat><d:prop>'
             '<d:current-user-principal><d:href>/principals/me/</d:href></d:current-user-principal>'
             '</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>')
HOMESET = ('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response>'
           '<d:href>/principals/me/</d:href><d:propstat><d:prop><c:calendar-home-set>'
           '<d:href>/cal/me/</d:href></c:calendar-home-set><d:displayname>Me</d:displayname></d:prop>'
           '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>')
CALS = ('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
        'xmlns:cs="http://calendarserver.org/ns/"><d:response><d:href>/cal/me/</d:href><d:propstat>'
        '<d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK'
        '</d:status></d:propstat></d:response><d:response><d:href>/cal/me/work/</d:href><d:propstat>'
        '<d:prop><d:displayname>Work</d:displayname><d:resourcetype><d:collection/><c:calendar/>'
        '</d:resourcetype><cs:getctag>c1</cs:getctag></d:prop><d:status>HTTP/1.1 200 OK</d:status>'
        '</d:propstat></d:response></d:multistatus>')


class DavFake:
    def __init__(self, wellknown="redirect", auth_ok=True):
        self.calls, self.wellknown, self.auth_ok = [], wellknown, auth_ok

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers))
        if not self.auth_ok:
            return 401, {}, b""
        if url == "https://cloud.example.com/.well-known/caldav":
            if self.wellknown == "redirect":
                return 301, {"Location": "/remote.php/dav/"}, b""
            if self.wellknown == "evil":
                return 301, {"Location": "https://evil.example.net/dav/"}, b""
            return 404, {}, b""
        if url in ("https://cloud.example.com/remote.php/dav/", "https://cloud.example.com"):
            return dav(PRINCIPAL)
        if url.endswith("/principals/me/"):
            return dav(HOMESET)
        if url.endswith("/cal/me/"):
            return dav(CALS)
        if method == "REPORT":
            return dav(multistatus([ics("e1", "Meeting")]).decode())
        return 404, {}, b""


def caldav_client(fake):
    return HttpClient(allowed_auth_hosts=("cloud.example.com",), exact_auth_hosts=True, transport=fake)


FIELDS = {"server_url": "https://cloud.example.com", "username": "me"}


def test_registry():
    assert [n for n, _ in providers.all()] == ["icloud", "caldav", "ics"]
    assert providers.get("ics").auth_hosts(None) == ()
    assert providers.get("icloud").auth_hosts(None) == ("icloud.com",)
    with pytest.raises(SyncError):
        providers.get("nope")
    assert fetch.provider_hosts("icloud") == ("icloud.com",)


def test_caldav_discovery_wellknown_redirect():
    fake = DavFake()
    d = providers.get("caldav").discover(FIELDS, Secret("app-password-1"), caldav_client(fake))
    assert d.calendar_home_url == "https://cloud.example.com/cal/me/"
    assert [c.name for c in d.calendars] == ["Work"] and d.display_name == "Me"
    assert all("Authorization" in h for _m, _u, h in fake.calls)


def test_caldav_discovery_fallback_to_base():
    d = providers.get("caldav").discover(FIELDS, Secret("app-password-1"),
                                         caldav_client(DavFake(wellknown="404")))
    assert d.calendars


def test_caldav_manual_principal_override():
    class F(DavFake):
        def __call__(self, m, url, h, b):
            if url in ("https://cloud.example.com", "https://cloud.example.com/.well-known/caldav"):
                return 404, {}, b""
            if url == "https://cloud.example.com/dav/me/":
                return dav(PRINCIPAL)
            return super().__call__(m, url, h, b)
    d = providers.get("caldav").discover(dict(FIELDS, principal_url="/dav/me/"),
                                         Secret("app-password-1"), caldav_client(F()))
    assert d.calendars


def test_caldav_rejects_http_and_other_host_redirect():
    with pytest.raises(SyncError):
        providers.get("caldav").discover(dict(FIELDS, server_url="http://cloud.example.com"),
                                         Secret("app-password-1"), caldav_client(DavFake()))
    fake = DavFake(wellknown="evil")
    d = providers.get("caldav").discover(FIELDS, Secret("app-password-1"), caldav_client(fake))
    assert d.calendars                           # fell back to base, never followed the redirect
    assert not any("evil" in u for _m, u, _h in fake.calls)


def test_exact_host_matching():
    acc = Account("caldav-1", "caldav", "me", "x", "https://example.com", "", "", "")
    c = providers.make_client(acc, transport=lambda *a: (200, {}, b""))
    hdrs = []
    c._transport = lambda m, u, h, b: (hdrs.append((u, h)) or (200, {}, b""))
    c.request("GET", "https://evil-example.com/", auth=("me", Secret("app-password-1")))
    c.request("GET", "https://sub.example.com/", auth=("me", Secret("app-password-1")))
    c.request("GET", "https://example.com/", auth=("me", Secret("app-password-1")))
    assert [("Authorization" in h) for _u, h in hdrs] == [False, False, True]


def test_caldav_auth_failed_is_raised():
    with pytest.raises(SyncError) as e:
        providers.get("caldav").discover(FIELDS, Secret("app-password-1"),
                                         caldav_client(DavFake(auth_ok=False)))
    assert e.value.code is ErrorCode.AUTH_FAILED


def test_caldav_sync_and_credentials_host(tmp_path):
    store = EventStore(tmp_path / "t.sqlite3")
    fake = DavFake()
    acc = Account("caldav-1", "caldav", "me", "Me", "https://cloud.example.com", "",
                  "https://cloud.example.com/cal/me/", "")
    res = providers.get("caldav").sync(acc, Secret("app-password-1"), store, WINDOW,
                                       client=caldav_client(fake), tz=BER)
    assert res.error is None and res.calendars[0].status == "ok" and res.calendars[0].events == 1
    res = fetch.sync_account(acc, Secret("app-password-1"), store, WINDOW,
                             client=caldav_client(fake), tz=BER)
    assert res.calendars[0].status == "unchanged"


# ---- ICS ----

def feed_body(name="Holidays", summary="Holiday"):
    return (f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nX-WR-CALNAME:{name}\nBEGIN:VEVENT\nUID:h1\n"
            f"SUMMARY:{summary}\nDTSTART;VALUE=DATE:20260320\nDTEND;VALUE=DATE:20260321\n"
            "END:VEVENT\nEND:VCALENDAR\n").encode()


class FeedFake:
    def __init__(self, etag='"v1"', body=None, lm=None):
        self.etag, self.body, self.lm, self.calls = etag, body or feed_body(), lm, []

    def __call__(self, method, url, headers, body):
        self.calls.append((url, headers))
        assert "Authorization" not in headers
        if self.etag and headers.get("If-None-Match") == self.etag:
            return 304, {}, b""
        if self.lm and headers.get("If-Modified-Since") == self.lm:
            return 304, {}, b""
        h = {}
        if self.etag:
            h["ETag"] = self.etag
        if self.lm:
            h["Last-Modified"] = self.lm
        return 200, h, self.body


ACC = Account("ics-1", "ics", "Holidays", "Holidays", "https://calendar.example.org/", "",
              "https://calendar.example.org/", "", {"color": "#ff8800"})


def run_ics(store, fake, **kw):
    return providers.get("ics").sync(ACC, Secret(FEED), store, WINDOW,
                                     client=HttpClient(transport=fake), tz=BER, **kw)


def age_token(store):
    store.set_sync_token("ics-1:feed", "t:1")


def test_ics_200_then_304(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    store = EventStore(tmp_path / "t.sqlite3")
    fake = FeedFake()
    r = run_ics(store, fake)
    assert r.calendars[0].status == "ok" and r.calendars[0].events == 1
    cal = store.get_calendar("ics-1:feed")
    assert cal.remote_color == "#ff8800" and cal.remote_name == "Holidays"
    assert store.sync_state("ics-1:feed")[0] == '"v1"'
    # within 15 minutes: no request at all
    n = len(fake.calls)
    assert run_ics(store, fake).calendars[0].status == "unchanged" and len(fake.calls) == n
    age_token(store)
    r = run_ics(store, fake)
    assert r.calendars[0].status == "unchanged" and fake.calls[-1][1]["If-None-Match"] == '"v1"'
    age_token(store)
    r = run_ics(store, fake, force=True)
    assert r.calendars[0].status == "ok" and "If-None-Match" not in fake.calls[-1][1]
    assert "abc123secret" not in caplog.text and "calendar.example.org" in caplog.text


def test_ics_sha_fallback_and_change(tmp_path):
    store = EventStore(tmp_path / "t.sqlite3")
    fake = FeedFake(etag=None)
    assert run_ics(store, fake).calendars[0].status == "ok"
    assert store.sync_state("ics-1:feed")[0].startswith("sha:")
    age_token(store)
    assert run_ics(store, fake).calendars[0].status == "unchanged"
    fake.body = feed_body(summary="Changed")
    age_token(store)
    assert run_ics(store, fake).calendars[0].status == "ok"


def test_ics_last_modified(tmp_path):
    store = EventStore(tmp_path / "t.sqlite3")
    fake = FeedFake(etag=None, lm="Wed, 01 Jan 2026 00:00:00 GMT")
    run_ics(store, fake)
    assert store.sync_state("ics-1:feed")[0].startswith("lm:")
    age_token(store)
    assert run_ics(store, fake).calendars[0].status == "unchanged"


def test_ics_errors(tmp_path):
    store = EventStore(tmp_path / "t.sqlite3")
    r = run_ics(store, FeedFake(body=b"<html>login</html>"))
    assert r.error is ErrorCode.PARSE_ERROR
    r = providers.get("ics").sync(ACC, Secret("http://calendar.example.org/x.ics"), store, WINDOW,
                                  client=HttpClient(transport=FeedFake()), tz=BER)
    assert r.error is not None


def test_normalize_feed():
    assert normalize_feed("webcal://a.example/x.ics") == "https://a.example/x.ics"
    with pytest.raises(SyncError):
        normalize_feed("http://a.example/x.ics")


def test_ics_discover_names():
    p = providers.get("ics")
    c = HttpClient(transport=FeedFake())
    d = p.discover({}, Secret("webcal://calendar.example.org/x.ics"), c)
    assert d.display_name == "Holidays" and d.calendar_home_url == "https://calendar.example.org/"
    assert "x.ics" not in d.calendar_home_url
    assert p.discover({"name": "Mine"}, Secret(FEED), c).display_name == "Mine"


def test_cli_add_ics_and_caldav(tmp_path, monkeypatch, capsys):
    s = SettingsStore(tmp_path)
    c = CredentialStore(tmp_path, serial_fn=lambda: ("abc", "t"))
    monkeypatch.setenv("URL", FEED)
    rc = cli.main(["add-account", "--provider", "ics", "--name", "Hol", "--color", "#ff8800",
                   "--password-env", "URL"], settings=s, credentials=c,
                  client=HttpClient(transport=FeedFake()))
    assert rc == 0
    out = capsys.readouterr().out
    assert "abc123secret" not in out
    accs = s.get("accounts")
    assert accs[0]["provider"] == "ics" and "abc123secret" not in str(accs)
    assert accs[0]["options"] == {"color": "#ff8800"}
    assert c.get(accs[0]["id"]).reveal() == FEED
    monkeypatch.setenv("PW", "app-password-1")
    rc = cli.main(["add-account", "--provider", "caldav", "--server", "https://cloud.example.com",
                   "--username", "me", "--password-env", "PW"], settings=s, credentials=c,
                  client=caldav_client(DavFake()))
    assert rc == 0 and len(s.get("accounts")) == 2
    from calpi.data.accounts import list_accounts
    assert {a.provider for a in list_accounts(s)} == {"ics", "caldav"}


def test_mixed_accounts(tmp_path):
    store = EventStore(tmp_path / "t.sqlite3")
    r1 = run_ics(store, FeedFake())
    acc = Account("caldav-1", "caldav", "me", "Me", "https://cloud.example.com", "",
                  "https://cloud.example.com/cal/me/", "")
    r2 = fetch.sync_account(acc, Secret("app-password-1"), store, WINDOW,
                            client=caldav_client(DavFake()), tz=BER)
    assert r1.calendars[0].status == r2.calendars[0].status == "ok"
    assert store.count_events() == 2
