"""iCloud CalDAV discovery. No gi imports."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from calpi.data.credentials import Secret
from calpi.data.models import RemoteCalendar
from calpi.sync import caldav
from calpi.sync.caldav import NS, DavResponse, href_in, text
from calpi.sync.errors import ErrorCode, SyncError
from calpi.sync.http import HttpClient

log = logging.getLogger("calpi.sync.icloud")

ICLOUD_ROOT = "https://caldav.icloud.com/"
ALLOWED = ("icloud.com",)

_COLOR_RE = re.compile(r"#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?")


@dataclass(frozen=True)
class Discovery:
    principal_url: str
    calendar_home_url: str
    display_name: str | None
    calendars: list


def normalize_color(s: str | None) -> str | None:
    if not s:
        return None
    m = _COLOR_RE.fullmatch(s.strip())
    return "#" + m.group(1).lower() if m else None


def _slash(u: str) -> str:
    return u.rstrip("/") + "/"


def _is_event_calendar(r: DavResponse) -> bool:
    rt = r.props.get("d:resourcetype")
    if rt is None or rt.find("c:calendar", NS) is None:
        return False
    comps = r.props.get("c:supported-calendar-component-set")
    if comps is None:
        return True
    names = {c.get("name", "").upper() for c in comps.findall("c:comp", NS)}
    return "VEVENT" in names


def _read_only(r: DavResponse) -> bool:
    priv = r.props.get("d:current-user-privilege-set")
    if priv is None:
        return False
    for p in priv.iter():
        if p.tag in ("{DAV:}write", "{DAV:}write-content", "{DAV:}all"):
            return False
    return True


def _parse_order(s: str | None) -> int | None:
    try:
        return int(float(s)) if s else None
    except ValueError:
        return None


def discover(username: str, secret: Secret, client: HttpClient | None = None) -> Discovery:
    client = client or HttpClient(allowed_auth_hosts=ALLOWED)
    auth = (username.strip(), secret)

    # 1. principal
    principal = display = None
    for url in (ICLOUD_ROOT, ICLOUD_ROOT + ".well-known/caldav"):
        try:
            rs = caldav.propfind(client, url, ["d:current-user-principal", "d:displayname"], 0, auth)
        except SyncError as e:
            if e.code is ErrorCode.NOT_FOUND and url == ICLOUD_ROOT:
                continue
            raise
        for r in rs:
            principal = href_in(r, "d:current-user-principal")
            if principal:
                display = text(r, "d:displayname")
                break
        if principal:
            break
    if not principal:
        raise SyncError(ErrorCode.PARSE_ERROR, "no current-user-principal in response")

    # 2. calendar home
    rs = caldav.propfind(client, principal, ["c:calendar-home-set", "d:displayname"], 0, auth)
    home = None
    for r in rs:
        home = href_in(r, "c:calendar-home-set")
        if home:
            display = text(r, "d:displayname") or display
            break
    if not home:
        raise SyncError(ErrorCode.PARSE_ERROR, "no calendar-home-set in response")

    # 3. calendars
    props = ["d:displayname", "d:resourcetype", "c:supported-calendar-component-set",
             "a:calendar-color", "a:calendar-order", "cs:getctag", "d:sync-token",
             "d:current-user-privilege-set"]
    rs = caldav.propfind(client, home, props, 1, auth)
    cals = []
    for r in rs:
        if _slash(r.href) == _slash(home) or not _is_event_calendar(r):
            continue
        name = text(r, "d:displayname") or r.href.rstrip("/").rsplit("/", 1)[-1]
        cals.append(RemoteCalendar(
            href=r.href, name=name, color=normalize_color(text(r, "a:calendar-color")),
            ctag=text(r, "cs:getctag"), sync_token=text(r, "d:sync-token"),
            order=_parse_order(text(r, "a:calendar-order")), read_only=_read_only(r)))
    cals.sort(key=lambda c: (c.order is None, c.order or 0, c.name.casefold()))
    return Discovery(principal, home, display, cals)
