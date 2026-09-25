import json
import urllib.parse
from datetime import date
from pathlib import Path

import pytest

from calpi.weather import client
from calpi.weather.client import WeatherError

FIX = Path(__file__).parent / "fixtures" / "weather"
FORECAST = json.loads((FIX / "forecast.json").read_text())
GEO = json.loads((FIX / "geocoding.json").read_text())

DOCUMENTED = [0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77,
              80, 81, 82, 85, 86, 95, 96, 99]


def test_parse_forecast_fixture():
    f = client.parse_forecast(FORECAST)
    assert f.temp == 15.2 and f.code == 3 and f.is_day
    assert len(f.daily) == 7
    d = f.daily[date(2026, 9, 25)]
    assert (d.max, d.min, d.code, d.precip) == (15.2, 11.7, 3, 25)


@pytest.mark.parametrize("bad", [{}, {"current": {}, "daily": {}}, None, "x",
                                 {"current": {}, "daily": {"time": ["nope"]}}])
def test_parse_forecast_bad(bad):
    with pytest.raises(WeatherError) as e:
        client.parse_forecast(bad)
    assert e.value.kind == "parse"


def test_null_values_tolerated():
    data = json.loads(json.dumps(FORECAST))
    data["daily"]["temperature_2m_max"][0] = None
    f = client.parse_forecast(data)
    assert f.daily[date(2026, 9, 25)].max is None
    assert client.daily_text(f.daily[date(2026, 9, 25)]).endswith("–/12°")


def test_forecast_url_params():
    q = urllib.parse.parse_qs(urllib.parse.urlparse(client.forecast_url(52.5, 13.4, "fahrenheit")).query)
    assert q["current"] == ["temperature_2m,weather_code,is_day"]
    assert q["daily"] == ["weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"]
    assert q["forecast_days"] == ["7"] and q["timezone"] == ["auto"]
    assert q["temperature_unit"] == ["fahrenheit"] and q["latitude"] == ["52.5000"]


def test_fetch_uses_transport_and_timeout():
    seen = []

    def transport(url, timeout):
        seen.append((url, timeout))
        return json.dumps(FORECAST).encode()
    f = client.fetch_forecast(1, 2, "celsius", transport=transport)
    assert f.temp == 15.2 and seen[0][1] == 10 and seen[0][0].startswith(client.FORECAST_URL)


def test_fetch_rejects_non_json_and_bad_shape():
    with pytest.raises(WeatherError) as e:
        client.fetch_raw(1, 2, "celsius", transport=lambda u, t: b"<html>")
    assert e.value.kind == "parse"
    with pytest.raises(WeatherError):
        client.fetch_raw(1, 2, "celsius", transport=lambda u, t: b"{}")


def test_search_places_labels():
    places = client.search_places("Springfield", transport=lambda u, t: json.dumps(GEO).encode())
    assert places[0].label == "Springfield, Missouri, United States"
    assert len({p.label for p in places}) > 1
    assert client.search_places("a", transport=lambda u, t: 1 / 0) == []     # too short: no request


def test_geocoding_url():
    u = client.geocoding_url("Saint Louis")
    assert "name=Saint+Louis" in u and "count=10" in u and "format=json" in u


@pytest.mark.parametrize("code", DOCUMENTED)
def test_every_documented_code_has_glyph_and_label(code):
    assert client.glyph(code) != client.UNKNOWN_GLYPH
    assert client.label(code) not in ("", "—")


def test_glyph_groups_and_fallback():
    assert client.glyph(0) == "☀" and client.glyph(0, is_day=False) == "☾"
    assert client.glyph(3) == "☁" and client.glyph(45) == "≋"
    assert client.glyph(63) == "☂" and client.glyph(75) == "❄" and client.glyph(95) == "⚡"
    assert client.glyph(1234) == client.UNKNOWN_GLYPH and client.glyph(None) == client.UNKNOWN_GLYPH
    assert client.label(1234) == "—"


def test_degrees_and_texts():
    assert client.degrees(-0.4) == "0°" and client.degrees(14.6) == "15°"
    assert client.degrees(None) == "–"
    f = client.parse_forecast(FORECAST)
    assert client.header_text(f, date(2026, 9, 25)) == "☁ 15° · 15°/12°"
    assert client.header_text(f, date(2030, 1, 1)) == "☁ 15°"
    assert client.daily_text(f.daily[date(2026, 9, 29)]) == "☀ 23°/13°"


def test_default_transport_classifies(monkeypatch):
    import socket
    import urllib.error
    import urllib.request

    def boom(exc):
        def f(*a, **k):
            raise exc
        return f
    for exc, kind in [(urllib.error.URLError(socket.gaierror(-2, "x")), "offline"),
                      (socket.timeout(), "timeout"),
                      (urllib.error.HTTPError("u", 503, "x", {}, None), "server")]:
        monkeypatch.setattr(urllib.request, "urlopen", boom(exc))
        with pytest.raises(WeatherError) as e:
            client.default_transport("https://x", 1)
        assert e.value.kind == kind


def test_no_gi_in_pure_modules():
    import subprocess
    import sys
    code = "import sys; import calpi.weather.client, calpi.weather.cache, calpi.weather.schedule; " \
           "assert 'gi' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True,
                   cwd=Path(__file__).resolve().parent.parent)
