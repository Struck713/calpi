from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from calpi import dimming
from calpi.data.settings_store import DEFAULT_DIM_SCHEDULE, Key, REGISTRY, K_DIM_SCHEDULE
from calpi.dimming import (DAY, NIGHT, NIGHT_AWAKE, DimController, DimSchedule, Effect,
                           in_window, parse_hhmm)

BERLIN = ZoneInfo("Europe/Berlin")


def at(h, m=0, day=(2026, 1, 15), tz=BERLIN):
    return datetime(*day, h, m, tzinfo=tz)


def cfg(**kw):
    return {**DEFAULT_DIM_SCHEDULE, "enabled": True, **kw}


def test_in_window_crossing_midnight():
    s, e = time(22, 30), time(6, 30)
    assert not in_window(at(22, 29), s, e)
    assert in_window(at(22, 30), s, e)
    assert in_window(at(3), s, e)
    assert in_window(at(6, 29), s, e)
    assert not in_window(at(6, 30), s, e)
    assert not in_window(at(12), s, e)


def test_in_window_same_day_and_empty():
    s, e = time(13), time(14)
    assert in_window(at(13), s, e) and in_window(at(13, 59), s, e)
    assert not in_window(at(14), s, e) and not in_window(at(12, 59), s, e)
    assert not in_window(at(13), time(13), time(13))


@pytest.mark.parametrize("day", [(2026, 3, 29), (2026, 10, 25)])
def test_in_window_dst_days_use_wall_time(day):
    s, e = time(22, 30), time(6, 30)
    assert in_window(at(22, 30, day), s, e)
    assert not in_window(at(22, 29, day), s, e)
    assert in_window(at(6, 29, day), s, e)
    assert not in_window(at(6, 30, day), s, e)
    assert in_window(at(3, 30, day), s, e)


def test_state_machine_cycle():
    sc, c = DimSchedule(), cfg()
    assert sc.evaluate(at(12), c) == Effect("normal")
    assert sc.state == DAY
    assert sc.evaluate(at(22, 30), c) == Effect("dim", 10, True)
    assert sc.state == NIGHT
    assert sc.evaluate(at(23), c) == Effect("dim", 10, True)     # no change
    assert sc.activity(at(23, 1), c) == Effect("normal")
    assert sc.state == NIGHT_AWAKE
    assert sc.evaluate(at(23, 2), c) == Effect("normal")          # stays awake on minute ticks
    assert sc.idle_timeout(at(23, 6), c) == Effect("dim", 10, True)
    assert sc.state == NIGHT
    assert sc.evaluate(at(6, 30), c) == Effect("normal")
    assert sc.state == DAY


def test_awake_then_window_ends():
    sc, c = DimSchedule(), cfg()
    sc.evaluate(at(23), c)
    sc.activity(at(23, 1), c)
    sc.evaluate(at(6, 30), c)
    assert sc.state == DAY
    sc.evaluate(at(22, 30), c)
    assert sc.state == NIGHT                                       # next night starts asleep


def test_activity_in_day_does_nothing():
    sc, c = DimSchedule(), cfg()
    sc.evaluate(at(12), c)
    assert sc.activity(at(12), c) == Effect("normal") and sc.state == DAY


def test_off_mode_effect():
    sc = DimSchedule()
    assert sc.evaluate(at(23), cfg(mode="off")) == Effect("off", None, True)


def test_settings_change_mid_night():
    sc = DimSchedule()
    sc.evaluate(at(23), cfg())
    assert sc.config_changed(at(23, 5), cfg(night_level=20)) == Effect("dim", 20, True)
    assert sc.config_changed(at(23, 5), cfg(mode="off")).kind == "off"
    assert sc.config_changed(at(23, 5), cfg(enabled=False)) == Effect("normal")
    assert sc.state == DAY
    assert sc.config_changed(at(23, 6), cfg()).kind == "dim"       # re-enabled inside window
    assert sc.config_changed(at(23, 6), cfg(start="00:00", end="01:00")).kind == "normal"


def test_preview():
    sc, c = DimSchedule(), cfg(enabled=False)
    now = at(12)
    assert sc.preview(now, c).kind == "dim"
    assert sc.evaluate(now + timedelta(seconds=5), c).kind == "dim"
    assert sc.evaluate(now + timedelta(seconds=11), c) == Effect("normal")
    assert sc.state == DAY
    sc.preview(now, c)
    assert sc.activity(now + timedelta(seconds=2), c) == Effect("normal")
    assert sc.state == DAY and sc.preview_until is None


def test_validator():
    ok = REGISTRY[K_DIM_SCHEDULE].validate
    assert ok(DEFAULT_DIM_SCHEDULE) and ok({"enabled": True})
    assert not ok({"start": "22:15"})
    assert not ok({"start": "25:00"})
    assert not ok({"start": "10:00", "end": "10:00"})
    assert not ok({"night_level": 4}) and not ok({"night_level": 51})
    assert not ok({"wake_minutes": 3}) and not ok({"mode": "sleep"})
    assert not ok({"bogus": 1}) and not ok({"enabled": 1})


# ---------- controller with fakes ----------

class FakeCatcher:
    def __init__(self):
        self.active, self.on_wake = False, None

    def set_active(self, a):
        self.active = a


class FakeBrightness:
    backend = None

    def __init__(self):
        self.calls = []

    def set_override(self, v):
        self.calls.append(v)


class FakeSettings:
    def __init__(self, v):
        self.v, self.subs = v, []

    def get(self, key):
        return dict(self.v)

    def set(self, key, v):
        self.v = dict(v)
        for cb in self.subs:
            cb(key, v)

    def subscribe(self, key, cb):
        self.subs.append(cb)


class FakeMethod:
    trusted, main_thread = True, False

    def __init__(self, name, fail_off=False, fail_on=0):
        self.name, self.calls, self.fail_off, self.fail_on = name, [], fail_off, fail_on

    def off(self):
        self.calls.append("off")
        if self.fail_off:
            raise OSError("nope")

    def on(self):
        self.calls.append("on")
        if self.fail_on > 0:
            self.fail_on -= 1
            raise OSError("nope")


class Rig:
    def __init__(self, methods, cfg_, boot=0):
        self.now = at(12)
        self.settings = FakeSettings(cfg_)
        self.catcher, self.bright = FakeCatcher(), FakeBrightness()
        self.timers, self.idle_timeouts, self.sleeps = [], [], []
        self.fallback_on_calls = 0
        overlay = FakeMethod("overlay")
        overlay.main_thread = True
        self.overlay = overlay
        self.jobs = []

        def run_worker(fn, done, err):          # synchronous
            try:
                r = fn()
            except Exception as e:
                err(e)
            else:
                done(r)
        self.ctl = DimController(
            settings=self.settings, brightness=self.bright, catcher=self.catcher,
            black_overlay=overlay, now_fn=lambda: self.now, run_worker=run_worker,
            schedule=lambda s, fn: self.timers.append((s, fn)),
            add_idle_callback=lambda s, cb: 1, set_idle_timeout=lambda h, s: self.idle_timeouts.append(s),
            probe_fn=lambda backend: methods + [overlay], boot_delay_s=boot,
            sleep=self.sleeps.append, fallback_on=self._fb)

    def _fb(self):
        self.fallback_on_calls += 1

    def set_time(self, h, m=0):
        self.now = at(h, m)
        self.ctl.on_minute()


def test_controller_dim_cycle_only_applies_on_change():
    r = Rig([], cfg())
    r.set_time(12)
    r.set_time(22, 30)
    assert r.bright.calls[-1] == 10 and r.catcher.active
    n = len(r.bright.calls)
    r.set_time(22, 31)
    r.set_time(22, 32)
    assert len(r.bright.calls) == n
    r.ctl.wake()
    assert r.bright.calls[-1] is None and not r.catcher.active and r.ctl.state == NIGHT_AWAKE
    r.ctl._on_idle()
    assert r.ctl.state == NIGHT and r.catcher.active and r.bright.calls[-1] == 10
    r.set_time(6, 30)
    assert r.ctl.state == DAY and r.bright.calls[-1] is None and not r.catcher.active


def test_controller_boot_delay():
    r = Rig([], cfg(), boot=30)
    r.now = at(23)
    r.ctl.on_minute()
    assert r.ctl.state == DAY and r.bright.calls == []
    r.timers[0][1]()
    assert r.ctl.state == NIGHT and r.bright.calls[-1] == 10


def test_controller_off_uses_best_method_and_wakes():
    m = FakeMethod("wlopm")
    r = Rig([m], cfg(mode="off"))
    r.set_time(23)
    assert m.calls == ["off"] and r.catcher.active
    r.ctl.wake()
    assert m.calls == ["off", "on"] and not r.catcher.active
    r.ctl._on_idle()
    assert m.calls == ["off", "on", "off"]
    r.set_time(6, 30)
    assert m.calls[-1] == "on"


def test_controller_off_without_real_method_uses_overlay():
    r = Rig([], cfg(mode="off"))
    r.set_time(23)
    assert r.overlay.calls == ["off"]
    assert not r.ctl.has_real_off_method()
    r.set_time(6, 30)
    assert r.overlay.calls == ["off", "on"]


def test_untrusted_method_needs_confirmation():
    m = FakeMethod("ddc")
    m.trusted = False
    r = Rig([m], cfg(mode="off"))
    r.set_time(23)
    assert m.calls == [] and r.overlay.calls == ["off"]
    r.ctl.confirm_method("ddc")                     # settings change re-evaluates
    assert m.calls == ["off"] and r.overlay.calls == ["off", "on"]


def test_off_failure_falls_back_to_dim_for_the_night():
    m = FakeMethod("wlopm", fail_off=True)
    r = Rig([m], cfg(mode="off"))
    r.set_time(23)
    assert r.bright.calls[-1] == dimming.MIN_FALLBACK_LEVEL
    r.ctl.wake()
    r.ctl._on_idle()
    assert m.calls.count("off") == 1                # fallback persists: no second off attempt
    assert r.bright.calls[-1] == dimming.MIN_FALLBACK_LEVEL
    r.set_time(6, 30)
    assert r.ctl._fallback is False


def test_on_failure_retries_then_fallback():
    m = FakeMethod("wlopm", fail_on=2)
    r = Rig([m], cfg(mode="off"))
    r.set_time(23)
    r.ctl.wake()
    assert m.calls == ["off", "on", "on", "on"] and r.fallback_on_calls == 0
    m2 = FakeMethod("wlopm", fail_on=99)
    r2 = Rig([m2], cfg(mode="off"))
    r2.set_time(23)
    r2.ctl.wake()
    assert m2.calls.count("on") == 3 and r2.fallback_on_calls == 1
    assert r2.sleeps == [5.0, 5.0]


def test_disable_mid_night_returns_to_day_immediately():
    m = FakeMethod("wlopm")
    r = Rig([m], cfg(mode="off"))
    r.set_time(23)
    r.settings.set(K_DIM_SCHEDULE, cfg(mode="off", enabled=False))
    assert r.ctl.state == DAY and m.calls == ["off", "on"] and not r.catcher.active


def test_wake_minutes_change_updates_idle_timeout():
    r = Rig([], cfg())
    r.settings.set(K_DIM_SCHEDULE, cfg(wake_minutes=15))
    assert r.idle_timeouts == [900]


def test_preview_and_end():
    r = Rig([], cfg(enabled=False))
    r.ctl.preview()
    assert r.ctl.state == NIGHT and r.bright.calls[-1] == 10
    r.now = r.now + timedelta(seconds=11)
    r.timers[-1][1]()
    assert r.ctl.state == DAY and r.bright.calls[-1] is None
