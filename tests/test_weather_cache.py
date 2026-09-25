import json
from pathlib import Path

from calpi.weather import cache, schedule

RAW = json.loads((Path(__file__).parent / "fixtures" / "weather" / "forecast.json").read_text())


def test_roundtrip(tmp_path):
    p = tmp_path / "weather.json"
    cache.save(p, RAW, 1000.0, 52.52, 13.41, "celsius")
    c = cache.load(p)
    assert c.fetched_at == 1000.0 and c.units == "celsius" and c.forecast.temp == 15.2
    assert cache.matches(c, 52.52, 13.41, "celsius")
    assert not cache.matches(c, 52.52, 13.41, "fahrenheit")
    assert not cache.matches(c, 10, 13.41, "celsius")
    assert not cache.matches(None, 1, 1, "celsius")


def test_load_tolerates_problems(tmp_path):
    p = tmp_path / "weather.json"
    assert cache.load(p) is None
    p.write_text("{not json")
    assert cache.load(p) is None
    p.write_text(json.dumps({"fetched_at": 1, "lat": 1, "lon": 1, "units": "celsius", "response": {}}))
    assert cache.load(p) is None
    p.write_text("[]")
    assert cache.load(p) is None


def test_freshness():
    c = cache.CachedForecast(None, 1000.0, 0, 0, "celsius", {})
    assert cache.is_fresh(c, 1000 + 6 * 3600)
    assert not cache.is_fresh(c, 1000 + 6 * 3600 + 1)
    assert not cache.is_fresh(c, 1000 - 7 * 3600)        # clock far behind: don't trust it
    assert not cache.is_fresh(None, 5)


def test_backoff():
    assert [schedule.next_delay(n) for n in (0, 1, 2, 3, 4, 9)] == [1800, 60, 300, 900, 1800, 1800]
