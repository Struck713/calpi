import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from calpi.data import settings_store as ss
from calpi.weather import client
from calpi.weather.client import WeatherError
from calpi.weather.service import WeatherService, WeatherStatus, status_text

RAW = (Path(__file__).parent / "fixtures" / "weather" / "forecast.json").read_bytes()


class Harness:
    def __init__(self, tmp_path, enabled=True, safe_mode=False, located=True):
        self.settings = ss.SettingsStore(tmp_path / "s")
        (tmp_path / "s").mkdir(exist_ok=True)
        cfg = {"enabled": enabled, "name": "Berlin" if located else None,
               "lat": 52.52 if located else None, "lon": 13.41 if located else None,
               "units": "celsius"}
        self.settings.set(ss.K_WEATHER, cfg)
        self.app = SimpleNamespace(settings=self.settings, safe_mode=safe_mode)
        self.now = 1000.0
        self.timers = {}
        self.next = 1
        self.pending = []            # queued (work, done, err)
        self.requests = []
        self.fail = None
        self.online = True
        self.svc = WeatherService(
            self.app, state_dir=tmp_path, transport=self.transport,
            add_timer=self.add, cancel_timer=lambda h: self.timers.pop(h, None),
            run_async=lambda w, d, e: self.pending.append((w, d, e)),
            clock=lambda: self.now, online=lambda: self.online)

    def transport(self, url, timeout):
        self.requests.append(url)
        if self.fail:
            raise WeatherError(self.fail)
        return RAW

    def add(self, seconds, cb):
        h = self.next
        self.next += 1
        self.timers[h] = (seconds, cb)
        return h

    def run_pending(self):
        while self.pending:
            w, d, e = self.pending.pop(0)
            try:
                res = w()
            except BaseException as exc:
                e(exc)
            else:
                d(res)

    def fire(self):
        (h, (_s, cb)), = self.timers.items()
        del self.timers[h]
        cb()

    @property
    def delay(self):
        (_h, (s, _cb)), = self.timers.items()
        return s


def test_disabled_makes_no_requests(tmp_path):
    h = Harness(tmp_path, enabled=False)
    h.svc.start()
    assert not h.timers and not h.pending and h.svc.forecast() is None
    h.svc.on_network_up()
    h.svc.refresh()
    assert not h.pending and not h.requests


def test_safe_mode_and_no_location(tmp_path):
    for kw in ({"safe_mode": True}, {"located": False}):
        h = Harness(tmp_path, **kw)
        h.svc.start()
        assert not h.timers and not h.pending


def test_startup_then_success_schedules_30_min(tmp_path):
    h = Harness(tmp_path)
    notes = []
    h.svc.callbacks.append(lambda s: notes.append(s.forecast() is not None))
    h.svc.start()
    assert h.delay == 10
    h.fire()
    h.run_pending()
    assert h.svc.forecast().temp == 15.2 and notes[-1] is True
    assert h.delay == 1800
    assert (tmp_path / "weather.json").exists()
    assert h.svc.status.last_success == 1000.0 and h.svc.status_text().startswith("Updated")


def test_failure_backoff_and_recovery(tmp_path):
    h = Harness(tmp_path)
    h.fail = "offline"
    h.svc.start()
    delays = []
    for _ in range(5):
        h.fire()
        h.run_pending()
        delays.append(h.delay)
    assert delays == [60, 300, 900, 1800, 1800]
    assert h.svc.status.last_error == "offline" and h.svc.forecast() is None
    assert "no internet" in h.svc.status_text()
    h.fail = None
    h.fire()
    h.run_pending()
    assert h.svc.status.last_error is None and h.delay == 1800


def test_cache_loaded_at_start_and_goes_stale(tmp_path):
    h = Harness(tmp_path)
    h.svc.start()
    h.fire()
    h.run_pending()
    h.now += 3600
    h2 = Harness(tmp_path)          # reuses the same state dir/settings file
    h2.now = h.now
    h2.svc.start()
    assert h2.svc.forecast() is not None            # shows at once, before any fetch
    h2.now += 6 * 3600
    assert h2.svc.forecast() is None                # stale: hidden


def test_failure_keeps_cached_data_until_stale(tmp_path):
    h = Harness(tmp_path)
    h.svc.start()
    h.fire()
    h.run_pending()
    h.fail = "timeout"
    h.now += 1800
    h.fire()
    h.run_pending()
    assert h.svc.forecast() is not None
    h.now += 6 * 3600
    assert h.svc.forecast() is None


def test_settings_change_refetches_and_units_in_url(tmp_path):
    h = Harness(tmp_path)
    h.svc.start()
    h.fire()
    h.run_pending()
    cfg = h.settings.get(ss.K_WEATHER)
    cfg["units"] = "fahrenheit"
    h.settings.set(ss.K_WEATHER, cfg)
    assert h.svc.forecast() is None                 # old units' data is not shown
    h.run_pending()
    assert "temperature_unit=fahrenheit" in h.requests[-1]
    assert h.svc.forecast() is not None


def test_change_during_inflight_is_refetched(tmp_path):
    h = Harness(tmp_path)
    h.svc.start()
    h.fire()                                        # request queued, not run
    cfg = h.settings.get(ss.K_WEATHER)
    cfg["lat"] = 10.0
    h.settings.set(ss.K_WEATHER, cfg)
    h.run_pending()                                 # first result is for the old place: discarded, refetch
    h.run_pending()
    assert len(h.requests) == 2 and "latitude=10.0000" in h.requests[-1]
    assert h.svc.current.lat == 10.0


def test_disable_cancels_timer_and_hides(tmp_path):
    h = Harness(tmp_path)
    h.svc.start()
    h.fire()
    h.run_pending()
    cfg = h.settings.get(ss.K_WEATHER)
    cfg["enabled"] = False
    h.settings.set(ss.K_WEATHER, cfg)
    assert not h.timers and h.svc.forecast() is None


def test_network_up_triggers_fetch_and_offline_defers(tmp_path):
    h = Harness(tmp_path)
    h.svc.start()
    h.svc.on_network_up()
    h.run_pending()
    assert len(h.requests) == 1
    h.online = False
    h.svc.refresh()
    assert not h.pending and h.timers


def test_status_text_variants():
    assert status_text(WeatherStatus(), 0) == "Not updated yet"
    assert status_text(WeatherStatus(), 0, active=False) == "Off"
    assert "Not updated since" in status_text(WeatherStatus(1000, "parse", 2000), 0)


def test_weather_setting_validation(tmp_path):
    store = ss.SettingsStore(tmp_path)
    assert store.get(ss.K_WEATHER)["enabled"] is False          # off by default
    ok = {"enabled": True, "name": "X", "lat": 1.5, "lon": -170, "units": "fahrenheit"}
    store.set(ss.K_WEATHER, ok)
    for bad in ({**ok, "lat": 91}, {**ok, "lon": 181}, {**ok, "units": "kelvin"},
                {**ok, "name": "x" * 101}, {**ok, "enabled": 1}, {"enabled": True}):
        with pytest.raises(ValueError):
            store.set(ss.K_WEATHER, bad)
