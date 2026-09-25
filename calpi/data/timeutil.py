"""The single source of 'now'. Everything that needs the current time or display zone asks here."""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger("calpi.time")
_override_tz: ZoneInfo | None = None
_fake_offset = None     # timedelta or None


def _init_fake_clock() -> None:
    global _fake_offset
    _fake_offset = None
    raw = os.environ.get("CALPI_FAKE_NOW")
    if not raw:
        return
    fake = datetime.fromisoformat(raw)
    if fake.tzinfo is None:
        fake = fake.replace(tzinfo=display_tz())
    _fake_offset = fake - datetime.now(timezone.utc)
    log.warning("FAKE CLOCK active: now=%s (offset %s)", fake.isoformat(), _fake_offset)


def system_tz_name() -> str:
    env = os.environ.get("CALPI_TZ")
    if env:
        return env
    try:
        target = os.readlink("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:
        return Path("/etc/timezone").read_text().strip() or "UTC"
    except OSError:
        return "UTC"


def display_tz() -> ZoneInfo:
    if _override_tz is not None:
        return _override_tz
    name = system_tz_name()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("unknown system time zone %r, using UTC", name)
        return ZoneInfo("UTC")


def set_display_tz(name: str | None) -> None:
    """US-28 calls this from settings. None = follow the system zone."""
    global _override_tz
    _override_tz = ZoneInfo(name) if name else None


def now() -> datetime:
    utc = datetime.now(timezone.utc)
    if _fake_offset is not None:
        utc = utc + _fake_offset
    return utc.astimezone(display_tz())


def today() -> date:
    return now().date()


_init_fake_clock()
