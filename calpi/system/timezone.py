"""Time zone index, labels and SetTimezone via systemd-timedated (US-28).

The pure part has no gi imports. `load_zone_index()` walks tzdata, so call it through
`run_in_thread` (it caches the first result). `set_async` imports Gio lazily.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable
from zoneinfo import ZoneInfo, available_timezones

log = logging.getLogger("calpi.timezone")

REGIONS = ("Africa", "America", "Antarctica", "Arctic", "Asia", "Atlantic",
           "Australia", "Europe", "Indian", "Pacific")
UTC_ZONE = "UTC"


def filter_zones(names: Iterable[str]) -> list[str]:
    """Canonical Region/City names only, plus "UTC" (D3). Sorted."""
    out = {n for n in names if "/" in n and n.split("/", 1)[0] in REGIONS}
    out.add(UTC_ZONE)
    return sorted(out)


def region_of(zone: str) -> str:
    return zone.split("/", 1)[0] if "/" in zone else zone


def group_by_region(zones: Iterable[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for z in zones:
        groups.setdefault(region_of(z), []).append(z)
    for v in groups.values():
        v.sort(key=city_label)
    return dict(sorted(groups.items()))


def city_label(zone: str) -> str:
    """America/Argentina/Buenos_Aires -> "Argentina / Buenos Aires"; UTC -> "UTC"."""
    if "/" not in zone:
        return zone
    return zone.split("/", 1)[1].replace("_", " ").replace("/", " / ")


def format_offset(seconds: int) -> str:
    if seconds == 0:
        return "UTC"
    sign = "+" if seconds > 0 else "−"
    minutes = abs(int(seconds)) // 60
    return f"UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def offset_label(zone: str, now_utc: datetime | None = None) -> str:
    now_utc = now_utc or datetime.now(timezone.utc)
    off = now_utc.astimezone(ZoneInfo(zone)).utcoffset()
    return format_offset(int(off.total_seconds()) if off else 0)


def is_valid_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


@dataclass
class ZoneIndex:
    zones: list[str] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)
    offsets: dict[str, str] = field(default_factory=dict)

    @property
    def regions(self) -> list[str]:
        return list(self.groups)

    def label(self, zone: str) -> str:
        return f"{city_label(zone)} ({self.offsets.get(zone) or offset_label(zone)})"


_cache: ZoneIndex | None = None
_lock = threading.Lock()


def build_zone_index(names: Iterable[str], now_utc: datetime | None = None) -> ZoneIndex:
    now_utc = now_utc or datetime.now(timezone.utc)
    zones = filter_zones(names)
    offsets = {}
    good = []
    for z in zones:
        try:
            offsets[z] = offset_label(z, now_utc)
            good.append(z)
        except Exception:
            log.debug("skipping unloadable zone %s", z)
    return ZoneIndex(good, group_by_region(good), offsets)


def load_zone_index() -> ZoneIndex:
    global _cache
    with _lock:
        if _cache is None:
            _cache = build_zone_index(available_timezones())
        return _cache


def set_async(name: str, on_done: Callable[[], None] | None = None,
              on_error: Callable[[Exception], None] | None = None) -> None:
    """Ask systemd-timedated to set the system zone. Callbacks run on the main loop."""
    from gi.repository import Gio, GLib

    def finished(conn, res):
        try:
            conn.call_finish(res)
        except Exception as e:  # noqa: BLE001
            log.warning("system time zone not set: %s", e)
            if on_error:
                on_error(e)
            return
        log.info("system time zone set to %s", name)
        if on_done:
            on_done()

    def got_bus(_src, res):
        try:
            conn = Gio.bus_get_finish(res)
        except Exception as e:  # noqa: BLE001
            log.warning("system bus unavailable: %s", e)
            if on_error:
                on_error(e)
            return
        conn.call("org.freedesktop.timedate1", "/org/freedesktop/timedate1",
                  "org.freedesktop.timedate1", "SetTimezone",
                  GLib.Variant("(sb)", (name, False)), None,
                  Gio.DBusCallFlags.NONE, 10000, None, finished)

    Gio.bus_get(Gio.BusType.SYSTEM, None, got_bus)
