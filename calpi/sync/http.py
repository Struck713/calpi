"""Small strict HTTP client for WebDAV/CalDAV on urllib. No gi imports."""
from __future__ import annotations

import base64
import email.utils
import logging
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlsplit

from calpi import __version__
from calpi.data.credentials import Secret
from calpi.sync.errors import ErrorCode, SyncError, classify_exception

log = logging.getLogger("calpi.sync.http")

MAX_REDIRECTS = 5
MAX_RETRY_AFTER = 3600
REDIRECT_CODES = (301, 302, 303, 307, 308)

Transport = Callable[[str, str, dict, "bytes | None"], "tuple[int, dict, bytes]"]


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes
    url: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_limited(resp, max_bytes: int) -> bytes:
    chunks, total = [], 0
    while True:
        chunk = resp.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise SyncError(ErrorCode.SERVER_ERROR, "response too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _urllib_transport(timeout: float, max_bytes: int) -> Transport:
    opener = urllib.request.build_opener(
        _NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def send(method, url, headers, body):
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            resp = e
        with resp:
            status = getattr(resp, "status", None) or resp.code
            return status, {k: v for k, v in resp.headers.items()}, _read_limited(resp, max_bytes)
    return send


def parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0, min(int(value), MAX_RETRY_AFTER))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(value)
        return max(0, min(int(dt.timestamp() - time.time()), MAX_RETRY_AFTER))
    except (TypeError, ValueError):
        return None


_LOCAL = ("localhost", "127.0.0.1", "::1")


def host_allowed(url: str, allowed: tuple[str, ...], exact: bool = False,
                 insecure_localhost: bool = False) -> bool:
    parts = urlsplit(url)
    if not parts.hostname:
        return False
    host = parts.hostname.lower()
    if parts.scheme != "https" and not (insecure_localhost and parts.scheme == "http"
                                        and host in _LOCAL):
        return False
    return any(host == a or (not exact and host.endswith("." + a)) for a in allowed)


class HttpClient:
    def __init__(self, timeout: float = 20, max_bytes: int = 20_000_000,
                 user_agent: str | None = None, allowed_auth_hosts: tuple[str, ...] = (),
                 transport: Transport | None = None, exact_auth_hosts: bool = False,
                 allow_insecure_localhost: bool = False):
        self.exact_auth_hosts = exact_auth_hosts              # US-20: no suffix matching
        self.allow_insecure_localhost = allow_insecure_localhost   # tests only
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.user_agent = user_agent or f"calpi/{__version__}"
        self.allowed_auth_hosts = tuple(h.lower() for h in allowed_auth_hosts)
        self._transport = transport or _urllib_transport(timeout, max_bytes)

    def request(self, method: str, url: str, *, body: bytes | None = None,
                headers: dict | None = None, auth: "tuple[str, Secret] | None" = None,
                ok_statuses: tuple[int, ...] = ()) -> Response:
        for _hop in range(MAX_REDIRECTS + 1):
            hdrs = {"User-Agent": self.user_agent}
            if body is not None:
                hdrs["Content-Type"] = "application/xml; charset=utf-8"
            hdrs.update(headers or {})
            if auth is not None and self._allowed(url):
                raw = f"{auth[0]}:{auth[1].reveal()}".encode("utf-8")
                hdrs["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
            try:
                status, rhdrs, rbody = self._transport(method, url, hdrs, body)
            except Exception as e:
                raise classify_exception(e) from None
            if len(rbody) > self.max_bytes:
                raise SyncError(ErrorCode.SERVER_ERROR, "response too large")
            rh = {k.lower(): v for k, v in rhdrs.items()}
            if status in REDIRECT_CODES:
                loc = rh.get("location")
                if not loc:
                    raise SyncError(ErrorCode.SERVER_ERROR, "redirect without Location")
                new = urljoin(url, loc)
                if auth is not None and not self._allowed(new):
                    raise SyncError(ErrorCode.SERVER_ERROR, "unexpected redirect")
                if urlsplit(new).scheme != "https" and not (
                        self.allow_insecure_localhost and urlsplit(new).scheme == "http"
                        and urlsplit(new).hostname in _LOCAL):
                    raise SyncError(ErrorCode.SERVER_ERROR, "unexpected redirect")
                url = new
                continue
            if status not in ok_statuses:
                self._raise_for_status(status, rh)
            return Response(status, rh, rbody, url)
        raise SyncError(ErrorCode.SERVER_ERROR, "too many redirects")

    def _allowed(self, url: str) -> bool:
        return host_allowed(url, self.allowed_auth_hosts, self.exact_auth_hosts,
                            self.allow_insecure_localhost)

    @staticmethod
    def _raise_for_status(status: int, rh: dict) -> None:
        if 200 <= status < 300:
            return
        if status == 401:
            raise SyncError(ErrorCode.AUTH_FAILED, "unauthorized")
        if status == 403:
            raise SyncError(ErrorCode.AUTH_FAILED, "forbidden")
        if status == 404:
            raise SyncError(ErrorCode.NOT_FOUND, "not found")
        if status in (429, 503):
            raise SyncError(ErrorCode.RATE_LIMITED, f"HTTP {status}",
                            retry_after=parse_retry_after(rh.get("retry-after")))
        if status >= 500:
            raise SyncError(ErrorCode.SERVER_ERROR, f"HTTP {status}")
        raise SyncError(ErrorCode.SERVER_ERROR, f"unexpected HTTP {status}")
