"""Open-Meteo client (US-41). No gi imports; the network transport is injectable for tests.

Weather data by Open-Meteo.com (CC BY 4.0). No API key. See docs/providers.md.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Callable

from calpi import __version__
from calpi.sync.errors import ErrorCode, classify_exception

log = logging.getLogger("calpi.weather")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
MAX_BYTES = 1024 * 1024
TIMEOUT_S = 10
UNITS = ("celsius", "fahrenheit")

Transport = Callable[[str, float], bytes]      # (url, timeout) -> body


class WeatherError(Exception):
    """kind: offline | timeout | server | parse"""

    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind


REASON_TEXT = {
    "offline": "no internet connection",
    "timeout": "the weather service took too long to answer",
    "server": "the weather service had a problem",
    "parse": "the weather service sent something unexpected",
}


def reason_text(kind: str) -> str:
    return REASON_TEXT.get(kind, "unknown problem")


@dataclass(frozen=True)
class Daily:
    max: float | None
    min: float | None
    code: int | None
    precip: int | None = None


@dataclass(frozen=True)
class Forecast:
    temp: float | None
    code: int | None
    is_day: bool
    daily: dict[date, Daily]


@dataclass(frozen=True)
class Place:
    name: str
    region: str
    country: str
    lat: float
    lon: float

    @property
    def label(self) -> str:
        return ", ".join(p for p in (self.name, self.region, self.country) if p)


def default_transport(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"calpi/{__version__}",
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            chunks, total = [], 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES:
                    raise WeatherError("server", "response too large")
                chunks.append(chunk)
            return b"".join(chunks)
    except WeatherError:
        raise
    except urllib.error.HTTPError as e:
        raise WeatherError("server", f"HTTP {e.code}") from None
    except Exception as e:  # noqa: BLE001 - classified
        code = classify_exception(e).code
        kind = ("offline" if code in (ErrorCode.NETWORK_DOWN, ErrorCode.DNS_FAILED)
                else "timeout" if code == ErrorCode.TIMEOUT else "server")
        raise WeatherError(kind, type(e).__name__) from None


def forecast_url(lat: float, lon: float, units: str) -> str:
    q = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
         "current": "temperature_2m,weather_code,is_day",
         "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
         "forecast_days": "7", "timezone": "auto",
         "temperature_unit": units if units in UNITS else "celsius"}
    return FORECAST_URL + "?" + urllib.parse.urlencode(q, safe=",")


def geocoding_url(query: str) -> str:
    return GEOCODING_URL + "?" + urllib.parse.urlencode(
        {"name": query, "count": 10, "language": "en", "format": "json"})


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _int(v):
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse_forecast(data) -> Forecast:
    try:
        cur = data["current"]
        d = data["daily"]
        times = d["time"]
        cols = {k: d.get(k) or [None] * len(times) for k in
                ("weather_code", "temperature_2m_max", "temperature_2m_min",
                 "precipitation_probability_max")}
        daily = {}
        for i, t in enumerate(times):
            daily[date.fromisoformat(t)] = Daily(
                _num(cols["temperature_2m_max"][i]), _num(cols["temperature_2m_min"][i]),
                _int(cols["weather_code"][i]), _int(cols["precipitation_probability_max"][i]))
        return Forecast(_num(cur.get("temperature_2m")), _int(cur.get("weather_code")),
                        bool(cur.get("is_day", 1)), daily)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as e:
        raise WeatherError("parse", f"bad forecast: {type(e).__name__}") from None


def _load_json(body: bytes):
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise WeatherError("parse", "not JSON") from None


def fetch_raw(lat: float, lon: float, units: str, timeout: float = TIMEOUT_S,
              transport: Transport = default_transport) -> dict:
    data = _load_json(transport(forecast_url(lat, lon, units), timeout))
    parse_forecast(data)           # validate before it is cached
    return data


def fetch_forecast(lat, lon, units, timeout: float = TIMEOUT_S,
                   transport: Transport = default_transport) -> Forecast:
    return parse_forecast(fetch_raw(lat, lon, units, timeout, transport))


def parse_places(data) -> list[Place]:
    out = []
    try:
        for r in data.get("results") or []:
            lat, lon = _num(r.get("latitude")), _num(r.get("longitude"))
            if lat is None or lon is None or not r.get("name"):
                continue
            out.append(Place(str(r["name"]), str(r.get("admin1") or ""),
                             str(r.get("country") or ""), lat, lon))
    except AttributeError:
        raise WeatherError("parse", "bad geocoding response") from None
    return out


def search_places(query: str, timeout: float = TIMEOUT_S,
                  transport: Transport = default_transport) -> list[Place]:
    query = query.strip()
    if len(query) < 2:
        return []
    return parse_places(_load_json(transport(geocoding_url(query), timeout)))


# ---- WMO weather codes (D3) ----
_GLYPHS = [
    ((0,), "☀", "Clear"),
    ((1, 2), "☀", "Partly cloudy"),     # U+26C5 is not in DejaVu Sans: use the sun
    ((3,), "☁", "Cloudy"),
    ((45, 48), "≋", "Fog"),
    ((51, 53, 55, 56, 57), "☂", "Drizzle"),
    ((61, 63, 65, 66, 67, 80, 81, 82), "☂", "Rain"),
    ((71, 73, 75, 77, 85, 86), "❄", "Snow"),
    ((95, 96, 99), "⚡", "Thunderstorm"),
]
_BY_CODE = {c: (g, lbl) for codes, g, lbl in _GLYPHS for c in codes}
NIGHT_CLEAR = "☾"
UNKNOWN_GLYPH = "·"


def glyph(code, is_day: bool = True) -> str:
    if code == 0 and not is_day:
        return NIGHT_CLEAR
    return _BY_CODE.get(code, (UNKNOWN_GLYPH, ""))[0]


def label(code) -> str:
    return _BY_CODE.get(code, ("", "—"))[1]


def degrees(v) -> str:
    if v is None:
        return "–"
    n = round(v)
    return f"{0 if n == 0 else n}°"


def daily_text(d: Daily) -> str:
    return f"{glyph(d.code)} {degrees(d.max)}/{degrees(d.min)}"


def header_text(f: Forecast, today: date) -> str:
    """'<glyph> <temp>° · <max>°/<min>°'; today's high/low are left off when the day is missing."""
    head = f"{glyph(f.code, f.is_day)} {degrees(f.temp)}"
    d = f.daily.get(today)
    if d is not None:
        head += f" · {degrees(d.max)}/{degrees(d.min)}"
    return head
