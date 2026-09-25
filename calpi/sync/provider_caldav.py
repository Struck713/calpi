"""Generic CalDAV provider (Fastmail, Nextcloud, Radicale, ...). No gi imports.

Credentials go only to the configured server host (exact match, https).
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin, urlsplit

from calpi.sync import caldav, icloud
from calpi.sync.caldav import href_in, text
from calpi.sync.errors import ErrorCode, SyncError
from calpi.sync.http import HttpClient

log = logging.getLogger("calpi.sync.caldav")


def normalize_server(s: str) -> str:
    s = (s or "").strip()
    if not s:
        raise SyncError(ErrorCode.UNKNOWN, "server address is empty")
    if "://" not in s:
        s = "https://" + s
    parts = urlsplit(s)
    if parts.scheme != "https" or not parts.hostname:
        raise SyncError(ErrorCode.UNKNOWN, "server address must be an https:// address")
    return s


def _probe(client, url, auth):
    """PROPFIND one URL: (principal, home, display_name); missing parts are None."""
    rs = caldav.propfind(client, url, ["d:current-user-principal", "c:calendar-home-set",
                                       "d:displayname"], 0, auth)
    principal = home = display = None
    for r in rs:
        principal = principal or href_in(r, "d:current-user-principal")
        home = home or href_in(r, "c:calendar-home-set")
        display = display or text(r, "d:displayname")
    return principal, home, display


class CalDavProvider:
    name = "caldav"
    display_name = "Other CalDAV server"
    exact_auth_hosts = True

    def auth_hosts(self, account):
        h = urlsplit(account.server_url).hostname if account else None
        return (h.lower(),) if h else ()

    def discover(self, fields, secret, client=None):
        base = normalize_server(fields["server_url"])
        host = urlsplit(base).hostname
        client = client or HttpClient(allowed_auth_hosts=(host,), exact_auth_hosts=True)
        auth = (fields["username"].strip(), secret)
        candidates = [urljoin(base, "/.well-known/caldav"), base]
        if fields.get("principal_url"):
            candidates.append(urljoin(base, fields["principal_url"]))
        principal = home = display = None
        last: SyncError | None = None
        for url in candidates:
            try:
                principal, home, display = _probe(client, url, auth)
            except SyncError as e:
                if e.code is ErrorCode.AUTH_FAILED:
                    raise
                last = e
                continue
            if principal or home:
                break
        if not (principal or home):
            raise last or SyncError(ErrorCode.PARSE_ERROR, "no current-user-principal in response")
        if not home:
            _p, home, d2 = _probe(client, principal, auth)
            display = d2 or display
            if not home:
                raise SyncError(ErrorCode.PARSE_ERROR, "no calendar-home-set in response")
        from calpi.sync import fetch
        cals = fetch._list_from_home(client, home, auth)
        return icloud.Discovery(principal or home, home, display, cals)

    def sync(self, account, secret, store, window, force=False, client=None, tz=None):
        from calpi.sync import fetch
        return fetch.sync_caldav_account(account, secret, store, window, force=force,
                                         client=client, tz=tz)


PROVIDER = CalDavProvider()
