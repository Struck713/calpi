"""Account sync: list calendars -> ctag check -> REPORT -> parse -> store. No gi imports.

`sync_account` never raises for expected failures: they are returned in AccountResult /
CalendarResult (US-18 records them). Runs in the sync process (US-16).
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timezone
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from calpi.data.credentials import Secret
from calpi.data.event_store import EventStore
from calpi.data.models import Account, Calendar, RemoteCalendar
from calpi.sync import caldav, icloud
from calpi.sync.caldav import NS, qname
from calpi.sync.errors import ErrorCode, SyncError
from calpi.sync.http import HttpClient
from calpi.sync.ical_parse import ParseStats, parse_resources

log = logging.getLogger("calpi.sync.fetch")

_CAL_PROPS = ["d:displayname", "d:resourcetype", "c:supported-calendar-component-set",
              "a:calendar-color", "a:calendar-order", "cs:getctag", "d:sync-token",
              "d:current-user-privilege-set"]


@dataclass
class CalendarResult:
    calendar_id: str
    name: str
    status: str                      # "ok" | "unchanged" | "error"
    events: int = 0
    error: ErrorCode | None = None
    detail: str = ""
    duration_ms: int = 0
    stats: ParseStats | None = None


@dataclass
class AccountResult:
    account_id: str
    error: ErrorCode | None
    detail: str
    calendars: list[CalendarResult] = field(default_factory=list)


def provider_hosts(provider: str, account: Account | None = None) -> tuple[str, ...]:
    """Hosts that may receive credentials (US-20: from the provider registry)."""
    from calpi.sync import providers
    return providers.get(provider).auth_hosts(account)


def calendar_id_for(account_id: str, href: str) -> str:
    """Stable id: hash of the absolute href with a trailing slash (D4)."""
    href = href.rstrip("/") + "/"
    return f"{account_id}:{hashlib.sha1(href.encode()).hexdigest()[:16]}"


def _add_months(y: int, m: int, n: int) -> tuple[int, int]:
    t = y * 12 + (m - 1) + n
    return t // 12, t % 12 + 1


def compute_window(today: date, tz: ZoneInfo, back: int = 2, forward: int = 12,
                   extra: tuple[date, date] | None = None) -> tuple[datetime, datetime]:
    """[first day of (month-back), first day of (month+forward+1)) as local midnights, in UTC.

    `extra` = (first_day, end_day_exclusive) is included if it reaches outside.
    """
    y0, m0 = _add_months(today.year, today.month, -back)
    y1, m1 = _add_months(today.year, today.month, forward + 1)
    first, end = date(y0, m0, 1), date(y1, m1, 1)
    if extra:
        first, end = min(first, extra[0]), max(end, extra[1])
    mid = lambda d: datetime.combine(d, dtime.min, tz).astimezone(timezone.utc)   # noqa: E731
    return mid(first), mid(end)


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_report(window: tuple[datetime, datetime]) -> bytes:
    root = ET.Element(qname("c:calendar-query"))
    prop = ET.SubElement(root, qname("d:prop"))
    ET.SubElement(prop, qname("d:getetag"))
    ET.SubElement(prop, qname("c:calendar-data"))
    filt = ET.SubElement(root, qname("c:filter"))
    vc = ET.SubElement(filt, qname("c:comp-filter"), name="VCALENDAR")
    ve = ET.SubElement(vc, qname("c:comp-filter"), name="VEVENT")
    ET.SubElement(ve, qname("c:time-range"), start=_fmt(window[0]), end=_fmt(window[1]))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _list_from_home(client: HttpClient, home: str, auth) -> list[RemoteCalendar]:
    rs = caldav.propfind(client, home, _CAL_PROPS, 1, auth)
    cals = []
    for r in rs:
        if icloud._slash(r.href) == icloud._slash(home) or not icloud._is_event_calendar(r):
            continue
        name = caldav.text(r, "d:displayname") or r.href.rstrip("/").rsplit("/", 1)[-1]
        cals.append(RemoteCalendar(
            href=r.href, name=name, color=icloud.normalize_color(caldav.text(r, "a:calendar-color")),
            ctag=caldav.text(r, "cs:getctag"), sync_token=caldav.text(r, "d:sync-token"),
            order=icloud._parse_order(caldav.text(r, "a:calendar-order")),
            read_only=icloud._read_only(r)))
    cals.sort(key=lambda c: (c.order is None, c.order or 0, c.name.casefold()))
    return cals


def list_calendars(client: HttpClient, account: Account, auth) -> list[RemoteCalendar]:
    try:
        return _list_from_home(client, account.calendar_home_url, auth)
    except SyncError as e:
        if e.code is not ErrorCode.NOT_FOUND:
            raise
        log.info("calendar home not found; rediscovering")
        from calpi.sync import providers
        d = providers.get(account.provider).discover(
            {"username": account.username, "server_url": account.server_url,
             "principal_url": account.options.get("principal_url_override", "")}, auth[1], client)
        return list(d.calendars)


def _fetch_blobs(client: HttpClient, auth, href: str, window) -> list[bytes]:
    r = client.request("REPORT", href, body=build_report(window), headers={"Depth": "1"}, auth=auth)
    blobs = []
    for resp in caldav.parse_multistatus(r.body, base_url=r.url):
        el = resp.props.get("c:calendar-data")
        if el is not None and el.text and el.text.strip():
            blobs.append(el.text.encode("utf-8"))                      # D9
    return blobs


def _covers(state, window) -> bool:
    _ctag, _tok, ws, we = state
    return ws is not None and we is not None and ws <= int(window[0].timestamp()) \
        and we >= int(window[1].timestamp())


def _sync_one(client, auth, store: EventStore, cid: str, rc: RemoteCalendar, window, tz,
              force: bool) -> CalendarResult:
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)      # noqa: E731
    try:
        state = store.sync_state(cid)
        if (not force and rc.ctag and rc.ctag == state[0] and _covers(state, window)):
            return CalendarResult(cid, rc.name, "unchanged", duration_ms=ms())
        blobs = _fetch_blobs(client, auth, rc.href, window)
        events, stats = parse_resources(blobs, cid, window, tz)
        if stats.resources and stats.parse_errors == stats.resources:
            return CalendarResult(cid, rc.name, "error", error=ErrorCode.PARSE_ERROR,
                                  detail="no resource could be parsed", duration_ms=ms(), stats=stats)
        n = store.apply_calendar_sync(cid, events, rc.ctag, rc.sync_token, window)
        return CalendarResult(cid, rc.name, "ok", events=n, duration_ms=ms(), stats=stats)
    except SyncError as e:
        log.warning("calendar %s failed: %s %s", rc.name, e.code.value, e.detail)
        return CalendarResult(cid, rc.name, "error", error=e.code, detail=e.detail, duration_ms=ms())
    except sqlite3.OperationalError as e:              # locked/busy: a per-calendar error
        log.warning("calendar %s: database busy: %s", rc.name, e)
        return CalendarResult(cid, rc.name, "error", error=ErrorCode.UNKNOWN, detail=str(e)[:200],
                              duration_ms=ms())
    except sqlite3.DatabaseError:
        raise                                           # corruption: the sync process exits (US-12)
    except Exception as e:
        log.exception("calendar %s failed unexpectedly", rc.name)
        return CalendarResult(cid, rc.name, "error", error=ErrorCode.UNKNOWN, detail=str(e)[:200],
                              duration_ms=ms())


def sync_account(account: Account, secret: Secret, store: EventStore,
                 window: tuple[datetime, datetime], *, force: bool = False,
                 client: HttpClient | None = None, tz: ZoneInfo | None = None) -> AccountResult:
    """Dispatch to the account's provider (US-20)."""
    from calpi.sync import providers
    try:
        prov = providers.get(account.provider)
    except SyncError as e:
        return AccountResult(account.id, e.code, e.detail, [])
    return prov.sync(account, secret, store, window, force=force, client=client, tz=tz)


def sync_caldav_account(account: Account, secret: Secret, store: EventStore,
                        window: tuple[datetime, datetime], *, force: bool = False,
                        client: HttpClient | None = None, tz: ZoneInfo | None = None) -> AccountResult:
    """Shared CalDAV loop for the icloud and caldav providers."""
    if tz is None:
        from calpi.data import timeutil
        tz = timeutil.display_tz()
    try:
        if client is None:
            from calpi.sync import providers
            client = providers.make_client(account)
        auth = (account.username, secret)
        remotes = list_calendars(client, account, auth)
    except SyncError as e:
        return AccountResult(account.id, e.code, e.detail, [])
    seen, results = set(), []
    for rc in remotes:
        href = urljoin(account.calendar_home_url, rc.href)
        cid = calendar_id_for(account.id, href)
        seen.add(cid)
        store.upsert_calendar(Calendar(id=cid, account_id=account.id, remote_href=href,
                                       remote_name=rc.name, remote_color=rc.color,
                                       sort_order=rc.order or 0))
        results.append(_sync_one(client, auth, store, cid, rc, window, tz, force))
    for cal in store.calendars_for_account(account.id):
        if cal.id not in seen:
            log.info("calendar removed on server: %s", cal.remote_name)
            store.delete_calendar(cal.id)
    return AccountResult(account.id, None, "", results)
