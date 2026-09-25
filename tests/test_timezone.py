from datetime import datetime, timezone

import pytest

from calpi.data.settings_store import REGISTRY, K_TIMEZONE, K_TIME_FORMAT, K_WEEK_START
from calpi.system import timezone as tz

SAMPLE = ["posix/Europe/Paris", "right/Europe/Paris", "Etc/GMT+5", "US/Eastern", "UTC",
          "America/Argentina/Buenos_Aires", "Europe/Paris", "Asia/Kolkata", "Canada/Pacific",
          "Europe", "EST5EDT", "America/St_Johns"]


def test_filter():
    out = tz.filter_zones(SAMPLE)
    assert out == ["America/Argentina/Buenos_Aires", "America/St_Johns", "Asia/Kolkata",
                   "Europe/Paris", "UTC"]


def test_group_and_labels():
    g = tz.group_by_region(tz.filter_zones(SAMPLE))
    assert list(g) == ["America", "Asia", "Europe", "UTC"]
    assert g["America"] == ["America/Argentina/Buenos_Aires", "America/St_Johns"]
    assert tz.city_label("America/Argentina/Buenos_Aires") == "Argentina / Buenos Aires"
    assert tz.city_label("Europe/Paris") == "Paris"
    assert tz.city_label("UTC") == "UTC"


def test_offsets():
    jan = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    jul = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
    assert tz.offset_label("Asia/Kolkata", jan) == "UTC+05:30"
    assert tz.offset_label("America/St_Johns", jan) == "UTC−03:30"
    assert tz.offset_label("America/St_Johns", jul) == "UTC−02:30"
    assert tz.offset_label("Europe/Paris", jul) == "UTC+02:00"
    assert tz.offset_label("UTC", jan) == "UTC"


def test_index_builds_real_zones():
    idx = tz.build_zone_index(["Europe/Paris", "Bogus/Nowhere", "UTC"])
    assert "Europe/Paris" in idx.zones and idx.regions == ["Europe", "UTC"]


def test_validators():
    k = REGISTRY[K_TIMEZONE]
    assert k.validate(None) and k.validate("Europe/Paris")
    with pytest.raises(Exception):
        k.validate("Not/AZone")
    assert not REGISTRY[K_WEEK_START].validate(3)
    assert all(REGISTRY[K_WEEK_START].validate(v) for v in (0, 5, 6))
    assert REGISTRY[K_TIME_FORMAT].validate("12h") and not REGISTRY[K_TIME_FORMAT].validate("13h")


def test_settings_reject_bad_values(tmp_path):
    from calpi.data.settings_store import SettingsStore
    s = SettingsStore(tmp_path)
    with pytest.raises(ValueError):
        s.set(K_TIMEZONE, "Not/AZone")
    with pytest.raises(ValueError):
        s.set(K_WEEK_START, 3)
    s.set(K_TIMEZONE, "Europe/Paris")
    assert s.get(K_TIMEZONE) == "Europe/Paris"
