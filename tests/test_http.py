import errno
import http.client
import ssl
import urllib.error
from unittest import mock

import pytest

from calpi.sync import errors
from calpi.sync.errors import ErrorCode, SyncError, classify_exception
from calpi.sync.http import HttpClient, parse_retry_after, _read_limited
import socket
import io


@pytest.mark.parametrize("exc,code", [
    (urllib.error.URLError(socket.gaierror(-2, "x")), ErrorCode.DNS_FAILED),
    (urllib.error.URLError(ConnectionRefusedError()), ErrorCode.NETWORK_DOWN),
    (urllib.error.URLError(OSError(errno.ENETUNREACH, "unreach")), ErrorCode.NETWORK_DOWN),
    (urllib.error.URLError(OSError(errno.EHOSTUNREACH, "unreach")), ErrorCode.NETWORK_DOWN),
    (urllib.error.URLError(socket.timeout("t")), ErrorCode.TIMEOUT),
    (TimeoutError(), ErrorCode.TIMEOUT),
    (http.client.RemoteDisconnected("x"), ErrorCode.NETWORK_DOWN),
    (ssl.SSLError("boom"), ErrorCode.TLS_ERROR),
    (OSError(errno.ENOSPC, "full"), ErrorCode.DISK_FULL),
    (ValueError("x"), ErrorCode.UNKNOWN),
])
def test_classify(exc, code):
    assert classify_exception(exc).code is code


def test_cert_errors():
    e = ssl.SSLCertVerificationError(1, "certificate verify failed: certificate is not yet valid")
    assert classify_exception(urllib.error.URLError(e)).code is ErrorCode.CLOCK_WRONG
    e2 = ssl.SSLCertVerificationError(1, "certificate verify failed: self signed certificate")
    with mock.patch.object(errors, "clock_looks_wrong", return_value=False):
        assert classify_exception(e2).code is ErrorCode.TLS_ERROR
    with mock.patch.object(errors, "clock_looks_wrong", return_value=True):
        assert classify_exception(e2).code is ErrorCode.CLOCK_WRONG


def test_transient_flags():
    assert SyncError(ErrorCode.TIMEOUT).transient
    assert not SyncError(ErrorCode.AUTH_FAILED).transient


def test_retry_after_parsing():
    assert parse_retry_after("30") == 30
    assert parse_retry_after("999999") == 3600
    assert parse_retry_after("garbage") is None
    assert parse_retry_after(None) is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0


def test_size_limit():
    with pytest.raises(SyncError) as e:
        _read_limited(io.BytesIO(b"x" * 100), 50)
    assert e.value.code is ErrorCode.SERVER_ERROR and "too large" in e.value.detail
    c = HttpClient(max_bytes=10, transport=lambda m, u, h, b: (200, {}, b"x" * 11))
    with pytest.raises(SyncError):
        c.request("GET", "https://x.icloud.com/")


def test_no_auth_to_unlisted_host():
    seen = []
    c = HttpClient(allowed_auth_hosts=("icloud.com",),
                   transport=lambda m, u, h, b: (seen.append(h) or (200, {}, b"")))
    from calpi.data.credentials import Secret
    c.request("GET", "https://example.com/", auth=("u", Secret("secret-value")))
    assert "Authorization" not in seen[0]
