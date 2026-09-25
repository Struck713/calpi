"""Weather cache: <state>/weather.json, written atomically. No gi imports (US-41)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from calpi.data.atomic import atomic_write_json
from calpi.weather.client import Forecast, WeatherError, parse_forecast

log = logging.getLogger("calpi.weather")

MAX_AGE_S = 6 * 3600
FILE = "weather.json"


@dataclass(frozen=True)
class CachedForecast:
    forecast: Forecast
    fetched_at: float            # epoch seconds
    lat: float
    lon: float
    units: str
    raw: dict


def cache_path(state_dir) -> Path:
    return Path(state_dir) / FILE


def save(path, raw: dict, fetched_at: float, lat: float, lon: float, units: str) -> None:
    atomic_write_json(path, {"fetched_at": fetched_at, "lat": lat, "lon": lon,
                             "units": units, "response": raw})


def load(path) -> CachedForecast | None:
    """Tolerant: missing, corrupt or malformed files give None."""
    try:
        obj = json.loads(Path(path).read_text("utf-8"))
        raw = obj["response"]
        return CachedForecast(parse_forecast(raw), float(obj["fetched_at"]), float(obj["lat"]),
                              float(obj["lon"]), str(obj["units"]), raw)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError, WeatherError):
        log.warning("weather cache unreadable; ignoring it")
        return None


def age_s(cached: CachedForecast, now: float) -> float:
    return now - cached.fetched_at


def is_fresh(cached: CachedForecast | None, now: float, max_age: float = MAX_AGE_S) -> bool:
    """A timestamp in the future (clock jump) counts as stale-safe: fresh only if within +-max_age."""
    return cached is not None and abs(now - cached.fetched_at) <= max_age


def matches(cached: CachedForecast | None, lat, lon, units) -> bool:
    return (cached is not None and lat is not None and abs(cached.lat - lat) < 1e-3
            and abs(cached.lon - lon) < 1e-3 and cached.units == units)
