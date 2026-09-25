"""iCalendar bytes -> Event occurrences for a window. No gi imports; only the sync process imports this.

Recurrence expansion is done by `recurring_ical_events` (never by hand). We feed it sanitised
components and map its output to the store's representation (aware UTC / floating dates).

Library behaviour notes (icalendar 6.0.1, recurring-ical-events 3.3.3, checked by tests):
- occurrences carry no RECURRENCE-ID, so override identity is recovered from the source components;
- cancelled instances are returned with STATUS:CANCELLED and are dropped here;
- an unknown TZID comes back as a naive datetime (TZID parameter lost) -> floating; we count it
  from the source components;
- Windows zone names ("W. Europe Standard Time") are mapped by icalendar itself;
- mixed DATE/DATETIME DTSTART/DTEND makes the library raise, so we sanitise first.
"""
from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

try:
    import icalendar
    import recurring_ical_events
except ImportError:                                     # D2 fallback: vendored copies
    from calpi._vendor import icalendar, recurring_ical_events   # type: ignore  # noqa: F401

from calpi.data.models import Event

# skip_bad_series is recurring-ical-events >= 2.1; Bookworm ships 2.0.1
_OF_KW = ({"skip_bad_series": True}
          if "skip_bad_series" in inspect.signature(recurring_ical_events.of).parameters else {})

log = logging.getLogger("calpi.sync.ical")

MAX_SUMMARY, MAX_LOCATION, MAX_DESCRIPTION = 500, 300, 4000
_UID_RE = re.compile(rb"^UID[^:]*:(.{0,200})", re.MULTILINE)
_UTC = timezone.utc


@dataclass
class ParseStats:
    resources: int = 0
    occurrences: int = 0
    parse_errors: int = 0
    cancelled: int = 0
    unknown_tz: int = 0
    capped: bool = False


def _peek_uid(blob: bytes) -> str | None:
    m = _UID_RE.search(blob[:200_000])
    return m.group(1).decode("utf-8", "replace").strip() if m else None


def _text(v, limit: int) -> str:
    return str(v).strip()[:limit] if v is not None else ""


def _norm(v, tz: ZoneInfo):
    """date stays date; naive -> display tz; aware -> UTC."""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=tz)
        return v.astimezone(_UTC)
    return v


def _iso(v) -> str:
    return v.isoformat()


def _prop_dt(comp, name):
    p = comp.get(name)
    return p.dt if p is not None and hasattr(p, "dt") else None


def _sanitize(cal, stats: ParseStats) -> None:
    """Fix components the expansion library cannot digest."""
    for c in cal.walk("VEVENT"):
        start, end = _prop_dt(c, "DTSTART"), _prop_dt(c, "DTEND")
        if start is None:
            continue
        for name in ("DTSTART", "DTEND"):
            p = c.get(name)
            if p is not None and isinstance(p.dt, datetime) and p.dt.tzinfo is None \
                    and p.params.get("TZID"):
                stats.unknown_tz += 1
                log.debug("unknown TZID %r treated as floating", p.params.get("TZID"))
                break
        start_is_dt = isinstance(start, datetime)
        if end is not None and start_is_dt != isinstance(end, datetime):
            log.debug("mixed DATE/DATETIME start/end; treating as all-day")
            if start_is_dt:
                c["DTSTART"] = icalendar.vDDDTypes(start.date())
                start = start.date()
            end = end.date() if isinstance(end, datetime) else end
            c["DTEND"] = icalendar.vDDDTypes(end)
            start_is_dt = False
        if end is not None and not start_is_dt and end <= start:
            log.debug("all-day event with end <= start; using 1 day")
            del c["DTEND"]
        elif end is not None and start_is_dt and end < start:
            del c["DTEND"]
            if "DURATION" in c:
                del c["DURATION"]


def _to_event(occ, overrides: dict, recurring_uids: set, calendar_id: str,
              tz: ZoneInfo, stats: ParseStats) -> Event | None:
    if str(occ.get("STATUS", "")).upper() == "CANCELLED":
        stats.cancelled += 1
        return None
    raw_start = _prop_dt(occ, "DTSTART")
    if raw_start is None:
        return None
    all_day = not isinstance(raw_start, datetime)
    start = _norm(raw_start, tz)
    raw_end = _prop_dt(occ, "DTEND")
    if raw_end is None and occ.get("DURATION") is not None:
        raw_end = raw_start + occ["DURATION"].dt
    if raw_end is None:
        end = start + timedelta(days=1) if all_day else start
    else:
        end = _norm(raw_end, tz)
        if all_day and isinstance(end, datetime):
            end = end.date()
    # recurring-ical-events 2.0.1 (Bookworm) fills a missing all-day DTEND with DTSTART
    if end < start or (all_day and end == start):
        end = start + timedelta(days=1) if all_day else start
    uid = str(occ.get("UID", "")).strip()
    rid = overrides.get((uid, _iso(start)))
    if rid is None:
        rid = _iso(start) if uid in recurring_uids else ""
    status = "TENTATIVE" if str(occ.get("STATUS", "")).upper() == "TENTATIVE" else "CONFIRMED"
    tzid = None
    p = occ.get("DTSTART")
    if p is not None and not all_day:
        tzid = p.params.get("TZID") or None
    return Event(calendar_id=calendar_id, uid=uid, recurrence_id=rid,
                 summary=_text(occ.get("SUMMARY"), MAX_SUMMARY),
                 location=_text(occ.get("LOCATION"), MAX_LOCATION),
                 description=_text(occ.get("DESCRIPTION"), MAX_DESCRIPTION),
                 status=status, all_day=all_day, start=start, end=end, tzid=tzid)


def _overlaps(e: Event, window: tuple[datetime, datetime], tz: ZoneInfo) -> bool:
    w0, w1 = window
    if e.all_day:
        d0, d1 = w0.astimezone(tz).date(), w1.astimezone(tz).date()
        return e.start < d1 and e.end > d0
    if e.end == e.start:
        return w0 <= e.start < w1
    return e.start < w1 and e.end > w0


def parse_resources(blobs: Iterable[bytes], calendar_id: str,
                    window: tuple[datetime, datetime], display_tz: ZoneInfo,
                    cap: int = 5000) -> tuple[list[Event], ParseStats]:
    stats = ParseStats()
    out: list[Event] = []
    # Widen the query by a day either side (floating times are compared in UTC by the library),
    # then filter exactly on our converted values.
    q0, q1 = window[0] - timedelta(days=1), window[1] + timedelta(days=1)
    for blob in blobs:
        stats.resources += 1
        try:
            cal = icalendar.Calendar.from_ical(blob)
            _sanitize(cal, stats)
            overrides, recurring = {}, set()
            for c in cal.walk("VEVENT"):
                uid = str(c.get("UID", "")).strip()
                rp = c.get("RECURRENCE-ID")
                if rp is not None:
                    s = _prop_dt(c, "DTSTART")
                    if s is not None:
                        overrides[(uid, _iso(_norm(s, display_tz)))] = _iso(_norm(rp.dt, display_tz))
                elif "RRULE" in c or "RDATE" in c:
                    recurring.add(uid)
            for occ in recurring_ical_events.of(cal, **_OF_KW).between(q0, q1):
                ev = _to_event(occ, overrides, recurring, calendar_id, display_tz, stats)
                if ev is None or not _overlaps(ev, window, display_tz):
                    continue
                out.append(ev)
                stats.occurrences += 1
                if stats.occurrences >= cap:
                    stats.capped = True
                    log.warning("occurrence cap %d hit for %s", cap, calendar_id)
                    return out, stats
        except Exception as e:
            stats.parse_errors += 1
            log.warning("unparseable resource in %s (uid=%s): %s", calendar_id, _peek_uid(blob), e)
    return out, stats
