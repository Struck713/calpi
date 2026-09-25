"""ICS subscription provider: one GET of a secret https/webcal URL, read-only. No gi imports.

The URL is the credential: it lives in the CredentialStore and only its host is ever logged.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from urllib.parse import urlsplit

from calpi.sync.errors import ErrorCode, SyncError
from calpi.sync.http import HttpClient
from calpi.sync.icloud import Discovery, normalize_color
from calpi.data.models import Calendar, RemoteCalendar

log = logging.getLogger("calpi.sync.ics")

MIN_INTERVAL = 15 * 60          # D5
DEFAULT_COLORS = ("#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6")
_CALNAME = re.compile(r"^X-WR-CALNAME(?:;[^:\r\n]*)?:(.*)$", re.M | re.I)


def normalize_feed(url: str) -> str:
    u = (url or "").strip()
    low = u.lower()
    if low.startswith("webcal://"):
        u = "https://" + u[9:]
    elif low.startswith("webcals://"):
        u = "https://" + u[10:]
    parts = urlsplit(u)
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise SyncError(ErrorCode.UNKNOWN, "the link must start with https:// or webcal://")
    return u


def feed_name(body: bytes) -> str | None:
    m = _CALNAME.search(body[:65536].decode("utf-8", "replace"))
    n = m.group(1).strip().replace("\\,", ",") if m else ""
    return n or None


def _check_feed(body: bytes) -> None:
    if not body.lstrip(b"\xef\xbb\xbf \t\r\n")[:15].upper().startswith(b"BEGIN:VCALENDAR"):
        raise SyncError(ErrorCode.PARSE_ERROR, "the link did not return a calendar")


def default_color(account_id: str) -> str:
    return DEFAULT_COLORS[int(hashlib.sha1(account_id.encode()).hexdigest(), 16) % len(DEFAULT_COLORS)]


def _conditional(tag: str | None) -> dict:
    if not tag or tag.startswith("sha:"):
        return {}
    if tag.startswith("lm:"):
        return {"If-Modified-Since": tag[3:]}
    return {"If-None-Match": tag}


def _validator(headers: dict, body: bytes) -> str:
    if headers.get("etag"):
        return headers["etag"]
    if headers.get("last-modified"):
        return "lm:" + headers["last-modified"]
    return "sha:" + hashlib.sha256(body).hexdigest()


class IcsProvider:
    name = "ics"
    display_name = "Calendar subscription (ICS link)"
    exact_auth_hosts = True

    def auth_hosts(self, account=None):
        return ()                                   # no Authorization header, ever

    def discover(self, fields, secret, client=None):
        url = normalize_feed(secret.reveal())
        client = client or HttpClient()
        r = client.request("GET", url)
        _check_feed(r.body)
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.hostname}/"
        name = (fields.get("name") or "").strip() or feed_name(r.body) or p.hostname
        rc = RemoteCalendar(href="feed", name=name, color=normalize_color(fields.get("color")))
        return Discovery("", origin, name, [rc])

    def sync(self, account, secret, store, window, force=False, client=None, tz=None):
        from calpi.sync import fetch
        from calpi.sync.fetch import AccountResult, CalendarResult
        if tz is None:
            from calpi.data import timeutil
            tz = timeutil.display_tz()
        cid = f"{account.id}:feed"
        t0 = time.monotonic()
        ms = lambda: int((time.monotonic() - t0) * 1000)      # noqa: E731
        name = account.display_name
        try:
            url = normalize_feed(secret.reveal())
            host = urlsplit(url).hostname
            client = client or HttpClient()
            store.upsert_calendar(Calendar(
                id=cid, account_id=account.id, remote_href=None, remote_name=name,
                remote_color=normalize_color(account.options.get("color")) or default_color(account.id)))
            ctag, token, ws, we = store.sync_state(cid)
            covered = fetch._covers((ctag, token, ws, we), window)
            if not force and covered and token and token.startswith("t:"):
                try:
                    if 0 <= time.time() - int(token[2:]) < MIN_INTERVAL:
                        return _ok(account, cid, name, "unchanged", 0, ms())
                except ValueError:
                    pass
            log.info("ics: %s fetching", host)
            use_tag = None if (force or not covered) else ctag
            r = client.request("GET", url, headers=_conditional(use_tag), ok_statuses=(304,))
            now_tok = f"t:{int(time.time())}"
            if r.status == 304:
                store.set_sync_token(cid, now_tok)
                return _ok(account, cid, name, "unchanged", 0, ms())
            _check_feed(r.body)
            new_tag = _validator(r.headers, r.body)
            if new_tag == use_tag:
                store.set_sync_token(cid, now_tok)
                return _ok(account, cid, name, "unchanged", 0, ms())
            events, stats = fetch.parse_resources([r.body], cid, window, tz)
            if stats.resources and stats.parse_errors == stats.resources:
                return AccountResult(account.id, None, "", [CalendarResult(
                    cid, name, "error", error=ErrorCode.PARSE_ERROR,
                    detail="the feed could not be parsed", duration_ms=ms(), stats=stats)])
            n = store.apply_calendar_sync(cid, events, new_tag, now_tok, window)
            log.info("ics: %s ok, %d occurrences", host, n)
            return AccountResult(account.id, None, "", [CalendarResult(
                cid, name, "ok", events=n, duration_ms=ms(), stats=stats)])
        except SyncError as e:
            log.warning("ics: %s failed: %s", _safe_host(secret), e.code.value)
            return AccountResult(account.id, e.code, e.detail, [])


def _safe_host(secret) -> str:
    try:
        return urlsplit(secret.reveal()).hostname or "?"
    except Exception:
        return "?"


def _ok(account, cid, name, status, n, ms):
    from calpi.sync.fetch import AccountResult, CalendarResult
    return AccountResult(account.id, None, "", [CalendarResult(cid, name, status, events=n,
                                                              duration_ms=ms)])


PROVIDER = IcsProvider()
