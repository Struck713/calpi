"""Overnight dim / display-off schedule (US-30).

`DimSchedule` is a pure state machine (DAY, NIGHT, NIGHT_AWAKE) that yields the desired `Effect`.
`DimController` applies effects (brightness override, display power, wake catcher) and is fully
injectable, so it is tested without gi. `create_controller()` wires it to the real app and is the
only place that touches gtk. Evaluation is always from `timeutil.now()` on minute ticks, so DST
and NTP jumps need no special handling.
"""
from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Callable

from calpi.data.settings_store import DEFAULT_DIM_SCHEDULE, K_DIM_SCHEDULE

log = logging.getLogger("calpi.dimming")

DAY, NIGHT, NIGHT_AWAKE = "DAY", "NIGHT", "NIGHT_AWAKE"
PREVIEW_SECONDS = 10
BOOT_DELAY_S = 30
MIN_FALLBACK_LEVEL = 5          # BrightnessController clamps to its own minimum


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_window(now: datetime, start: time, end: time) -> bool:
    """Local wall-clock window; start > end means it crosses midnight; start == end is empty."""
    t = now.timetz().replace(tzinfo=None)
    if start < end:
        return start <= t < end
    if start > end:
        return t >= start or t < end
    return False


def full_config(cfg: dict | None) -> dict:
    return {**DEFAULT_DIM_SCHEDULE, **(cfg or {})}


@dataclass(frozen=True)
class Effect:
    kind: str                  # "normal" | "dim" | "off"
    level: int | None = None   # dim only
    catcher: bool = False      # is the wake catcher shown


NORMAL = Effect("normal")


class DimSchedule:
    """Pure. All times are timezone-aware 'now' values passed in by the caller."""

    def __init__(self):
        self.state = DAY
        self.preview_until: datetime | None = None

    def _inside(self, now, cfg) -> bool:
        return bool(cfg["enabled"]) and in_window(now, parse_hhmm(cfg["start"]),
                                                  parse_hhmm(cfg["end"]))

    def previewing(self, now=None) -> bool:
        return self.preview_until is not None and (now is None or now < self.preview_until)

    def effect(self, cfg) -> Effect:
        if self.state != NIGHT:
            return NORMAL
        if cfg["mode"] == "off":
            return Effect("off", None, True)
        return Effect("dim", int(cfg["night_level"]), True)

    def evaluate(self, now, cfg) -> Effect:
        if self.previewing(now):
            self.state = NIGHT
            return self.effect(cfg)
        self.preview_until = None
        if not self._inside(now, cfg):
            self.state = DAY
        elif self.state == DAY:
            self.state = NIGHT
        return self.effect(cfg)

    config_changed = evaluate

    def preview(self, now, cfg, seconds: float = PREVIEW_SECONDS) -> Effect:
        self.preview_until = now + timedelta(seconds=seconds)
        self.state = NIGHT
        return self.effect(cfg)

    def activity(self, now, cfg) -> Effect:
        if self.preview_until is not None:
            self.preview_until = None
            self.state = NIGHT_AWAKE if self._inside(now, cfg) else DAY
        elif self.state == NIGHT:
            self.state = NIGHT_AWAKE
        return self.effect(cfg)

    def idle_timeout(self, now, cfg) -> Effect:
        if self.state == NIGHT_AWAKE:
            self.state = NIGHT if self._inside(now, cfg) else DAY
        return self.effect(cfg)


class DimController:
    """Applies the schedule. Every collaborator is injected (see create_controller)."""

    def __init__(self, *, settings, brightness, catcher, black_overlay, now_fn, run_worker,
                 schedule, add_idle_callback, set_idle_timeout, probe_fn, run_probe=None,
                 boot_delay_s: float = BOOT_DELAY_S, retry_delay_s: float = 5.0,
                 sleep: Callable[[float], None] = _time.sleep, fallback_on=None):
        self.settings, self.brightness, self.catcher = settings, brightness, catcher
        self.sched = DimSchedule()
        self._now, self._run_worker, self._schedule = now_fn, run_worker, schedule
        self._set_idle_timeout, self._sleep, self._retry_delay = set_idle_timeout, sleep, retry_delay_s
        self._fallback_on = fallback_on          # last-resort `on` (wlr-randr --on), worker thread
        self.methods: list = [black_overlay]
        self.probed = False
        self._applied: Effect = NORMAL
        self._active_method = None
        self._fallback = False                   # off() failed tonight: dim instead
        self.started = boot_delay_s <= 0
        catcher.on_wake = self.wake
        cfg = self.config()
        self._idle_handle = add_idle_callback(cfg["wake_minutes"] * 60, self._on_idle)
        self._wake_minutes = cfg["wake_minutes"]
        settings.subscribe(K_DIM_SCHEDULE, lambda *_: self._on_settings())
        (run_probe or run_worker)(lambda: probe_fn(brightness.backend), self._on_probed,
                                  self._probe_failed)
        if not self.started:
            schedule(boot_delay_s, self._boot)
        else:
            self._evaluate()

    # ---- public ----
    @property
    def state(self) -> str:
        return self.sched.state

    def config(self) -> dict:
        return full_config(self.settings.get(K_DIM_SCHEDULE))

    def wake(self) -> None:
        cfg = self.config()
        if self.sched.state != DAY or self.sched.previewing():
            self._apply(self.sched.activity(self._now(), cfg))

    def usable_methods(self) -> list:
        confirmed = self.config()["confirmed_method"]
        return [m for m in self.methods if m.trusted or m.name == confirmed]

    def preview_method(self):
        """The method Preview will exercise: the best candidate even if unconfirmed."""
        return self.methods[0]

    def has_real_off_method(self) -> bool:
        return any(m.name != "overlay" for m in self.usable_methods())

    def preview(self) -> None:
        self.started = True
        self._apply(self.sched.preview(self._now(), self.config()))
        self._schedule(PREVIEW_SECONDS + 0.5, self._evaluate)

    def confirm_method(self, name: str) -> None:
        cfg = dict(self.config())
        cfg["confirmed_method"] = name
        self.settings.set(K_DIM_SCHEDULE, cfg)

    # ---- inputs ----
    def _boot(self) -> None:
        self.started = True
        self._evaluate()

    def _on_settings(self) -> None:
        cfg = self.config()
        if cfg["wake_minutes"] != self._wake_minutes:
            self._wake_minutes = cfg["wake_minutes"]
            self._set_idle_timeout(self._idle_handle, cfg["wake_minutes"] * 60)
        self.started = True
        self._evaluate()

    def on_minute(self, *_a) -> None:
        self._evaluate()

    def _evaluate(self) -> None:
        if not self.started:
            return
        self._apply(self.sched.evaluate(self._now(), self.config()))

    def _on_idle(self) -> None:
        if self.started:
            self._apply(self.sched.idle_timeout(self._now(), self.config()))

    def _on_probed(self, methods) -> None:
        self.methods, self.probed = list(methods), True
        if self._applied.kind == "off":
            self._apply(self._applied, force=True)       # switch from the overlay to the real one

    def _probe_failed(self, exc) -> None:
        log.warning("dim: display power probe failed (%s); using the black overlay", exc)
        self.probed = True

    # ---- effects ----
    def _method_for_off(self):
        pool = self.methods if self.sched.previewing() else self.usable_methods()
        return pool[0]

    def _apply(self, eff: Effect, force: bool = False) -> None:
        prev = self._applied
        want = self._method_for_off() if eff.kind == "off" and not self._fallback else None
        if eff == prev and not force and want is self._active_method:
            return
        self._applied = eff
        self.catcher.set_active(eff.catcher)
        if self._active_method is not None and want is not self._active_method:
            self._power_on(self._active_method)
            self._active_method = None
        if eff.kind == "off":
            if self._fallback:
                self.brightness.set_override(MIN_FALLBACK_LEVEL)
            elif self._active_method is None:
                self.brightness.set_override(None)
                self._active_method = want
                self._power_off(want)
        elif eff.kind == "dim":
            self.brightness.set_override(eff.level)
        else:
            if self.sched.state == DAY:
                self._fallback = False           # "the rest of the night" ends with the night
            self.brightness.set_override(None)
        self._log(prev, eff, want)

    def _log(self, prev: Effect, eff: Effect, method) -> None:
        if eff.kind == "normal":
            log.info("dim: %s", "awake" if self.sched.state == NIGHT_AWAKE else "day")
        elif eff.kind == "dim":
            log.info("dim: night (mode=dim, level=%s)", eff.level)
        else:
            log.info("dim: night (mode=off, method=%s)",
                     "dim-fallback" if self._fallback else method.name)

    def _power_off(self, method) -> None:
        if method.main_thread:
            try:
                method.off()
            except Exception as e:  # noqa: BLE001
                self._off_failed(method, e)
            return
        self._run_worker(method.off, lambda _r: None, lambda e: self._off_failed(method, e))

    def _off_failed(self, method, exc) -> None:
        log.warning("dim: %s off failed (%s); dimming instead for the rest of the night",
                    method.name, exc)
        self._fallback = True
        if self._applied.kind == "off" and self._active_method is method:
            self._active_method = None
            self.brightness.set_override(MIN_FALLBACK_LEVEL)
            self._power_on(method)           # make sure it is not half-off

    def _power_on(self, method) -> None:
        if method.main_thread:
            try:
                method.on()
            except Exception:  # noqa: BLE001
                log.exception("dim: overlay on failed")
            return

        def work():
            for i in range(3):
                try:
                    method.on()
                    return
                except Exception as e:  # noqa: BLE001
                    log.warning("dim: %s on failed (attempt %d/3): %s", method.name, i + 1, e)
                    if i < 2:
                        self._sleep(self._retry_delay)
            log.error("dim: %s could not turn the display on; trying wlr-randr --on", method.name)
            if self._fallback_on is not None:
                try:
                    self._fallback_on()
                except Exception as e:  # noqa: BLE001
                    log.error("dim: wlr-randr --on failed too: %s", e)
        self._run_worker(work, lambda _r: None, lambda e: log.error("dim: on failed: %s", e))


def create_controller(app, window) -> DimController:
    """Wire a DimController to the real app. Called last in MainWindow.__init__ (topmost overlay)."""
    from concurrent.futures import ThreadPoolExecutor
    from gi.repository import Gdk, GLib

    from calpi.data import timeutil
    from calpi.system import display_power
    from calpi.tasks import call_on_main, safe_callback
    from calpi.widgets.wake_catcher import WakeCatcher
    import os

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="display-power")

    def run_worker(fn, done, err):
        def job():
            try:
                res = fn()
            except BaseException as e:  # noqa: BLE001
                call_on_main(err, e)
                return
            call_on_main(done, res)
        pool.submit(job)

    def schedule(seconds, fn):
        GLib.timeout_add(int(seconds * 1000), safe_callback(fn, repeat=False))

    overlay = display_power.BlackOverlay(window._apply_dim, lambda: app.brightness.apply())
    catcher = WakeCatcher(window)          # added to the overlay now: must stay the LAST overlay

    holder: dict = {}

    def fallback_on():
        m = holder["ctl"].methods
        display_power.WlrRandr(display_power.output_name(m)).on()

    def probe_fn(backend):
        return display_power.probe(backend, overlay)

    def probe_when_ready(fn, done, err):
        # brightness may still be probing: wait for it so its backend can offer bl_power/DDC
        def go():
            run_worker(lambda: fn(), done, err)
        if app.brightness.backend is None:
            def cb():
                app.brightness.ready_callbacks.remove(cb)
                go()
            app.brightness.ready_callbacks.add(cb)
        else:
            go()

    try:
        boot = float(os.environ.get("CALPI_DIM_BOOT_DELAY_S", BOOT_DELAY_S))
    except ValueError:
        boot = BOOT_DELAY_S
    ctl = DimController(
        settings=app.settings, brightness=app.brightness, catcher=catcher, black_overlay=overlay,
        now_fn=timeutil.now, run_worker=run_worker, run_probe=probe_when_ready,
        schedule=schedule,
        add_idle_callback=window.inactivity.add_idle_callback,
        set_idle_timeout=window.inactivity.tracker.set_timeout,
        probe_fn=probe_fn, boot_delay_s=boot, fallback_on=fallback_on)
    holder["ctl"] = ctl
    app.clock.subscribe_minute(ctl.on_minute)
    app.clock.subscribe_tz_changed(ctl._evaluate)
    motion_or_key = {Gdk.EventType.MOTION_NOTIFY, Gdk.EventType.KEY_PRESS}

    def on_event(event):
        if (ctl.state == NIGHT or ctl.sched.previewing()) \
                and event.get_event_type() in motion_or_key:
            ctl.wake()
    window.hub.event_hooks.append(on_event)
    return ctl
