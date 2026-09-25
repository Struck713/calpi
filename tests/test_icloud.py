import base64
import logging
import socket
from pathlib import Path

import pytest

from calpi.data.credentials import Secret
from calpi.sync import icloud
from calpi.sync.errors import ErrorCode, SyncError
from calpi.sync.http import HttpClient

FX = Path(__file__).parent / "fixtures" / "icloud"
PW = Secret("abcd-efgh-ijkl-mnop")
HOME = "https://p42-caldav.icloud.com:443/1234567890/calendars/"


def fx(name):
    return (FX / name).read_bytes()


class Fake:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        r = self.routes[(method, url)]
        if isinstance(r, BaseException):
            raise r
        return r if isinstance(r, tuple) and len(r) == 3 else (207, {}, r)


def happy():
    return {
        ("PROPFIND", "https://caldav.icloud.com/"): fx("root_principal.xml"),
        ("PROPFIND", "https://caldav.icloud.com/1234567890/principal/"): fx("principal_home.xml"),
        ("PROPFIND", HOME): fx("calendars.xml"),
    }


def client(routes):
    f = Fake(routes)
    return f, HttpClient(allowed_auth_hosts=icloud.ALLOWED, transport=f)


def test_discovery_happy_path():
    f, c = client(happy())
    d = icloud.discover(" me@icloud.com ", PW, c)
    assert [x[1] for x in f.calls] == list(x[1] for x in happy())
    assert [x[2]["Depth"] for x in f.calls] == ["0", "0", "1"]
    exp = "Basic " + base64.b64encode(b"me@icloud.com:abcd-efgh-ijkl-mnop").decode()
    assert all(x[2]["Authorization"] == exp for x in f.calls)
    assert d.calendar_home_url == HOME and d.display_name == "Test User"
    assert [(x.name, x.color) for x in d.calendars] == [
        ("Home", "#ff2968"), ("Work", "#1badf8"), ("Unspecified", None)]
    assert d.calendars[0].read_only and not d.calendars[1].read_only
    assert d.calendars[1].ctag == "ctag-work-1" and d.calendars[1].sync_token
    assert d.calendars[0].href == "https://caldav.icloud.com/1234567890/calendars/home/" or \
        d.calendars[0].href.endswith("/calendars/home/")


@pytest.mark.parametrize("s,exp", [("#FF2968FF", "#ff2968"), ("#1BADF8", "#1badf8"),
                                   ("red", None), ("", None), (None, None), ("#12345", None)])
def test_color(s, exp):
    assert icloud.normalize_color(s) == exp


def test_redirect_to_icloud_host_keeps_auth():
    r = happy()
    r[("PROPFIND", "https://caldav.icloud.com/")] = (301, {"Location": "https://p42-caldav.icloud.com/"}, b"")
    r[("PROPFIND", "https://p42-caldav.icloud.com/")] = fx("root_principal.xml")
    r[("PROPFIND", "https://p42-caldav.icloud.com/1234567890/principal/")] = fx("principal_home.xml")
    f, c = client(r)
    icloud.discover("me@icloud.com", PW, c)
    assert f.calls[1][1] == "https://p42-caldav.icloud.com/" and "Authorization" in f.calls[1][2]
    assert f.calls[1][0] == "PROPFIND" and f.calls[1][3] is not None


@pytest.mark.parametrize("loc", ["http://p1.icloud.com/", "https://evil.example/", "https://icloud.com.evil.example/"])
def test_bad_redirect(loc):
    r = happy()
    r[("PROPFIND", "https://caldav.icloud.com/")] = (302, {"Location": loc}, b"")
    f, c = client(r)
    with pytest.raises(SyncError) as e:
        icloud.discover("me@icloud.com", PW, c)
    assert e.value.code is ErrorCode.SERVER_ERROR
    assert len(f.calls) == 1      # never contacted the target


def test_too_many_redirects():
    class Loop:
        def __call__(self, m, u, h, b):
            return 302, {"Location": u}, b""
    c = HttpClient(allowed_auth_hosts=icloud.ALLOWED, transport=Loop())
    with pytest.raises(SyncError) as e:
        icloud.discover("u", PW, c)
    assert e.value.code is ErrorCode.SERVER_ERROR


@pytest.mark.parametrize("resp,code", [
    ((401, {}, b""), ErrorCode.AUTH_FAILED),
    ((403, {}, b""), ErrorCode.AUTH_FAILED),
    ((404, {}, b""), ErrorCode.NOT_FOUND),
    ((500, {}, b""), ErrorCode.SERVER_ERROR),
    ((429, {}, b""), ErrorCode.RATE_LIMITED),
    (socket.timeout(), ErrorCode.TIMEOUT),
    (socket.gaierror(-2, "Name or service not known"), ErrorCode.DNS_FAILED),
    (ConnectionRefusedError(), ErrorCode.NETWORK_DOWN),
])
def test_error_mapping(resp, code):
    f, c = client({("PROPFIND", "https://caldav.icloud.com/"): resp,
                   ("PROPFIND", "https://caldav.icloud.com/.well-known/caldav"): resp})
    with pytest.raises(SyncError) as e:
        icloud.discover("u", PW, c)
    assert e.value.code is code


def test_503_retry_after():
    f, c = client({("PROPFIND", "https://caldav.icloud.com/"): (503, {"Retry-After": "120"}, b"")})
    with pytest.raises(SyncError) as e:
        icloud.discover("u", PW, c)
    assert e.value.code is ErrorCode.RATE_LIMITED and e.value.retry_after == 120 and e.value.transient


def test_doctype_rejected():
    r = happy()
    r[("PROPFIND", "https://caldav.icloud.com/")] = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><multistatus xmlns="DAV:"/>'
    f, c = client(r)
    with pytest.raises(SyncError) as e:
        icloud.discover("u", PW, c)
    assert e.value.code is ErrorCode.PARSE_ERROR


def test_missing_home_set():
    r = happy()
    r[("PROPFIND", "https://caldav.icloud.com/1234567890/principal/")] = fx("root_principal.xml")
    f, c = client(r)
    with pytest.raises(SyncError) as e:
        icloud.discover("u", PW, c)
    assert e.value.code is ErrorCode.PARSE_ERROR


def test_garbage_xml():
    r = happy()
    r[("PROPFIND", "https://caldav.icloud.com/")] = b"<not xml"
    f, c = client(r)
    with pytest.raises(SyncError) as e:
        icloud.discover("u", PW, c)
    assert e.value.code is ErrorCode.PARSE_ERROR


def test_well_known_fallback():
    r = happy()
    r[("PROPFIND", "https://caldav.icloud.com/")] = (404, {}, b"")
    r[("PROPFIND", "https://caldav.icloud.com/.well-known/caldav")] = fx("root_principal.xml")
    f, c = client(r)
    assert icloud.discover("u", PW, c).calendar_home_url == HOME


def test_secret_not_in_logs_or_exception(caplog):
    caplog.set_level(logging.DEBUG)
    f, c = client({("PROPFIND", "https://caldav.icloud.com/"): (401, {}, b"")})
    with pytest.raises(SyncError) as e:
        icloud.discover("u", PW, c)
    assert PW.reveal() not in str(e.value) + e.value.detail + caplog.text
    assert PW.reveal() not in repr(e.value)
