"""WeatherService (US-41): schedules fetches, owns the cache, notifies widgets.

Main-thread object. The blocking request runs through `run_async` (default:
calpi.tasks.run_in_thread). Weather never raises user-facing errors: failures are logged (once per
state change) and kept in `status` for Settings and the Status screen.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from gi.repository import GLib

from calpi import tasks
from calpi.data import settings_store as ss
from calpi.tasks import run_in_thread, safe_callback
from calpi.weather import cache, client, schedule
from calpi.weather.client import WeatherError

log = logging.getLogger("calpi.weather")


@dataclass
class WeatherStatus:
    last_success: float | None = None        # epoch seconds
    last_error: str | None = None            # WeatherError.kind
    last_error_at: float | None = None


def _glib_add(seconds: float, cb) -> int:
    return GLib.timeout_add(int(seconds * 1000), safe_callback(cb, repeat=False))


class WeatherService:
    def __init__(self, app, *, state_dir=None, transport=client.default_transport,
                 add_timer=_glib_add, cancel_timer=GLib.source_remove,
                 run_async=None, clock=None, online: Callable[[], bool] = lambda: True):
        from calpi import paths
        self.app = app
        self.settings = app.settings
        self.path = cache.cache_path(state_dir or paths.state_dir())
        self._transport = transport
        self._add_timer, self._cancel_timer = add_timer, cancel_timer
        self._run_async = run_async or (lambda work, done, err: run_in_thread(
            work, on_done=done, on_error=err, name="weather-fetch"))
        from calpi.data import timeutil
        self._clock = clock or (lambda: timeutil.now().timestamp())   # honours CALPI_FAKE_NOW
        self._online = online
        self.callbacks: list[Callable[["WeatherService"], None]] = []
        self.current: cache.CachedForecast | None = None
        self.status = WeatherStatus()
        self._timer = 0
        self._inflight = False
        self._dirty = False
        self._failures = 0
        self._started = False
        self._token = None

    # ---- settings view ----
    def config(self) -> dict:
        return self.settings.get(ss.K_WEATHER)

    @property
    def active(self) -> bool:
        c = self.config()
        return (bool(c["enabled"]) and c["lat"] is not None and c["lon"] is not None
                and not getattr(self.app, "safe_mode", False))

    def forecast(self):
        """The Forecast to display now, or None (disabled, no data, stale, other location)."""
        if not self.active or self.current is None:
            return None
        c = self.config()
        if not cache.matches(self.current, c["lat"], c["lon"], c["units"]):
            return None
        return self.current.forecast if cache.is_fresh(self.current, self._clock()) else None

    # ---- lifecycle ----
    def start(self, startup_delay: float = schedule.STARTUP_DELAY_S) -> None:
        if self._started:
            return
        self._started = True
        self.current = cache.load(self.path)
        if self.current is not None:
            self.status.last_success = self.current.fetched_at
        self._token = self.settings.subscribe(ss.K_WEATHER, lambda _k, _v: self._on_settings())
        if self.active:
            self._arm(startup_delay)
        self._notify()

    def stop(self) -> None:
        self._disarm()
        if self._token is not None:
            self.settings.unsubscribe(self._token)
            self._token = None
        self._started = False

    def _arm(self, seconds: float) -> None:
        self._disarm()
        self._timer = self._add_timer(seconds, self._on_timer)
        tasks.register_periodic("weather", self._timer, seconds)     # US-37 wakeup audit

    def _disarm(self) -> None:
        if self._timer:
            try:
                self._cancel_timer(self._timer)
            except Exception:
                pass
            self._timer = 0
        tasks.unregister_periodic("weather")

    def _on_timer(self):
        self._timer = 0
        tasks.unregister_periodic("weather")
        self.refresh()

    def _on_settings(self) -> None:
        if not self.active:
            self._disarm()
            self._failures = 0
            self._notify()
            return
        c = self.config()
        if not cache.matches(self.current, c["lat"], c["lon"], c["units"]):
            self._failures = 0
            self.refresh()
        self._notify()

    def on_network_up(self) -> None:
        """US-17: called when connectivity returns."""
        if self.active and not self._inflight:
            self.refresh()

    # ---- fetching ----
    def refresh(self) -> None:
        if not self.active:
            return
        if self._inflight:
            self._dirty = True
            return
        if not self._online():
            log.debug("weather: offline, retry later")
            self._arm(schedule.next_delay(max(self._failures, 1)))
            return
        c = self.config()
        lat, lon, units = c["lat"], c["lon"], c["units"]
        self._disarm()
        self._inflight = True
        self._run_async(lambda: client.fetch_raw(lat, lon, units, transport=self._transport),
                        lambda raw: self._done(raw, lat, lon, units),
                        self._failed)

    def _done(self, raw, lat, lon, units) -> None:
        self._inflight = False
        now = self._clock()
        c = self.config()
        if (self.active and (c["lat"], c["lon"], c["units"]) == (lat, lon, units)):
            try:
                cache.save(self.path, raw, now, lat, lon, units)
            except OSError:
                log.warning("weather: could not write cache", exc_info=True)
            self.current = cache.CachedForecast(client.parse_forecast(raw), now, lat, lon, units, raw)
            if self.status.last_error:
                log.info("weather: recovered")
            self.status = WeatherStatus(last_success=now)
            self._failures = 0
            self._notify()
        self._reschedule()

    def _failed(self, exc: BaseException) -> None:
        self._inflight = False
        kind = exc.kind if isinstance(exc, WeatherError) else "server"
        if kind != self.status.last_error:
            log.info("weather: update failed (%s)", kind)
        self.status = WeatherStatus(self.status.last_success, kind, self._clock())
        self._failures += 1
        self._notify()
        self._reschedule()

    def _reschedule(self) -> None:
        if self._dirty:
            self._dirty = False
            self.refresh()
        elif self.active:
            self._arm(schedule.next_delay(self._failures))

    def _notify(self) -> None:
        for cb in list(self.callbacks):
            try:
                cb(self)
            except Exception:
                log.exception("weather callback failed")

    # ---- text for Settings / Status ----
    def status_text(self) -> str:
        return status_text(self.status, self._clock(), self.active)


def _hhmm(ts: float) -> str:
    from calpi.data import formatting, timeutil
    from datetime import datetime
    return formatting.short_time(datetime.fromtimestamp(ts, timeutil.display_tz()))


def status_text(status: WeatherStatus, now: float, active: bool = True) -> str:
    if status.last_error:
        since = f" since {_hhmm(status.last_success)}" if status.last_success else ""
        return (f"Not updated{since} ({client.reason_text(status.last_error)}). "
                f"Last try {_hhmm(status.last_error_at)}.")
    if status.last_success:
        return f"Updated {_hhmm(status.last_success)}"
    return "Not updated yet" if active else "Off"
