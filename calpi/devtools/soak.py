"""Soak driver (US-37). Dev-only: enabled by CALPI_SOAK=1 (scripts/pi soak start), never in normal operation.

Speeds up ordinary use so days of activity fit into hours, and runs until the service is stopped:

    every   5 min  a sync (forced every 4th time; the engine also runs on CALPI_SYNC_INTERVAL_OVERRIDE)
    every  30 s    month navigation: random +-3 months, then back to today (alternating)
    every   2 min  open a day detail and go back
    every  10 min  open Settings and visit every section, then go back
    every  10 min  show and hide the on-screen keyboard on a demo entry
    every   1 h    a dim preview cycle (if US-30's controller exists)
    every   6 h    a mini benchmark (month navigation 20x); the result goes to the health log

One registered 5 s tick checks which entries are due (one timer, not ten). Random choices use a seeded
random.Random (CALPI_SOAK_SEED, else drawn and logged) so a run can be reproduced.
Env: CALPI_SOAK_SPEED=<n> divides every interval (tests / local smoke runs).
     CALPI_SOAK_ONLY=a,b  run only the named actions (sync,month_nav,day,settings,osk,dim,minirun)
     CALPI_SOAK_SELFTEST=<ticks> runs on VIRTUAL time (one 5 s tick per 50 ms), takes a census (widget count,
     callback-list sizes, timer names, fds, threads) after a warm-up and again after <ticks> more ticks, logs
     `SOAK_SELFTEST {json}` and quits: the leak check used by tests/test_leaks_gtk.py and the 6 h rehearsal.
"""
from __future__ import annotations

import gc
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

log = logging.getLogger("calpi.soak")

TICK_S = 5
MINI_RUN_NAV = 20
DAY = 24 * 3600


@dataclass
class Entry:
    name: str
    every_s: float
    fn: Callable[[], None]
    next_due: float = 0.0


class Scheduler:
    """Pure: a list of (every, action) entries; run_due(now) runs what is due. Never raises."""

    def __init__(self, entries: list[Entry], now: float = 0.0, stagger: bool = True):
        self.entries = entries
        for i, e in enumerate(entries):          # stagger the first runs so they don't all fire together
            e.next_due = now + (e.every_s * (i + 1) / (len(entries) + 1) if stagger else e.every_s)
        self.later: list[tuple[float, Callable[[], None]]] = []
        self.errors = 0

    def call_later(self, now: float, seconds: float, fn: Callable[[], None]) -> None:
        self.later.append((now + seconds, fn))

    def run_due(self, now: float) -> list[str]:
        ran = []
        due, self.later = [x for x in self.later if x[0] <= now], [x for x in self.later if x[0] > now]
        for _t, fn in sorted(due, key=lambda x: x[0]):
            self._safe("later", fn)
        for e in self.entries:
            if now >= e.next_due:
                e.next_due = now + e.every_s
                self._safe(e.name, e.fn)
                ran.append(e.name)
        return ran

    def _safe(self, name: str, fn) -> None:
        try:
            fn()
        except Exception:
            self.errors += 1
            log.exception("soak: action %s failed", name)


def percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    v = sorted(vals)
    k = min(len(v) - 1, max(0, int(round(p / 100 * (len(v) - 1)))))
    return v[k]


class Soak:
    def __init__(self, app, speed: float | None = None, seed: int | None = None):
        self.app, self.win = app, app.window
        self.selftest_ticks = int(os.environ.get("CALPI_SOAK_SELFTEST", "0"))
        self.virtual = self.selftest_ticks > 0
        self._vt = 0.0                     # virtual clock (selftest): +TICK_S per driver tick
        self.speed = speed or float(os.environ.get("CALPI_SOAK_SPEED", "20" if self.virtual else "1"))
        seed = seed if seed is not None else int(os.environ.get("CALPI_SOAK_SEED", "0")) or random.randrange(1, 10**9)
        self.seed = seed
        self.rng = random.Random(seed)
        self.counts: dict[str, int] = {}
        self.away = False                  # month navigation alternates: away / back to today
        self._sync_n = 0
        self._osk_screen = None
        self._minirun_running = False
        self.busy_until = 0.0              # a multi-step sequence (settings tour) owns the UI
        s = self.speed
        entries = [
            Entry("sync", 300 / s, self.act_sync),
            Entry("month_nav", 30 / s, self.act_month_nav),
            Entry("day", 120 / s, self.act_day),
            Entry("settings", 600 / s, self.act_settings),
            Entry("osk", 600 / s, self.act_osk),
            Entry("dim", 3600 / s, self.act_dim),
            Entry("minirun", 6 * 3600 / s, self.act_minirun),
        ]
        only = os.environ.get("CALPI_SOAK_ONLY")           # bisecting a leak: CALPI_SOAK_ONLY=month_nav,day
        if only:
            keep = {x.strip() for x in only.split(",")}
            entries = [e for e in entries if e.name in keep]
        self.sched = Scheduler(entries, now=self._now())
        self.step_s = TICK_S / s

    def _now(self) -> float:
        return self._vt if self.virtual else time.monotonic()

    def start(self) -> None:
        from calpi import tasks
        if self.virtual:
            self._start_selftest()
            return
        log.warning("soak: driver on (seed=%d speed=%s): dev only, activity is speeded up", self.seed, self.speed)
        tasks.add_periodic_seconds("soak", max(1, int(round(self.step_s))),
                                   tasks.safe_callback(self.tick, repeat=True), )

    def tick(self):
        for name in self.sched.run_due(self._now()):
            self.counts[name] = self.counts.get(name, 0) + 1
        from gi.repository import GLib
        return GLib.SOURCE_CONTINUE

    # ------------------------------------------------------------------ census / selftest
    def census(self) -> dict:
        """Everything that must stay flat when the same activity repeats (US-37 leak hunting)."""
        from calpi import health, perf, tasks
        gc.collect()
        app, win = self.app, self.win

        def widgets(w) -> int:
            n, c = 1, w.get_first_child()
            while c is not None:
                n += widgets(c)
                c = c.get_next_sibling()
            return n

        def size(x) -> int:
            return len(x) if x is not None else -1
        nav = win.navigator
        lists = {
            "sync.result_callbacks": size(getattr(app.sync, "result_callbacks", None)),
            "sync.state_callbacks": size(getattr(app.sync, "state_callbacks", None)),
            "app.status_callbacks": size(app.status_callbacks),
            "network.callbacks": size(getattr(app.network, "callbacks", None)),
            "clock_trust.callbacks": size(getattr(app.clock_trust, "callbacks", None)),
            "weather.callbacks": size(getattr(app.weather, "callbacks", None)),
            "navigator.changed": size(nav.changed_callbacks),
            "navigator.history": size(nav._history),
            "clock.minute": size(app.clock._minute), "clock.day": size(app.clock._day),
            "clock.tz": size(app.clock._tz),
            "settings.observers": size(app.settings._observers),
            "hub.hooks": size(win.hub.event_hooks),
            "month.changed": size(win.month_view.month_changed_callbacks),
        }
        inact = getattr(win, "inactivity", None)
        if inact is not None:
            lists["inactivity.listeners"] = size(inact.tracker._listeners)
        gtk_types: dict[str, int] = {}
        for o in gc.get_objects():
            t = type(o)
            if t.__module__.startswith("gi.repository"):
                gtk_types[t.__name__] = gtk_types.get(t.__name__, 0) + 1
        return {
            "widgets": {name: widgets(w) for name, w in sorted(nav._screens.items())},
            "window_widgets": widgets(win),
            "lists": lists,
            "sources": sorted(tasks.periodic_sources()),
            "fds": health.count_fds(), "threads": health.os_threads(),
            "sync_procs": health.child_processes()[0],
            "perf_samples": sum(len(v) for v in perf._samples.values()),
            "perf_listeners": len(perf._listeners),
            "gtk_objects": gtk_types,
            "py_objects": len(gc.get_objects()),
            "rss_mb": round(health.read_rss_mb(), 1),
        }

    def _settle(self) -> None:
        self.busy_until = 0.0
        self.sched.later.clear()
        self.win.keyboard.hide()
        self.win.navigator.reset("calendar")
        self.win.month_view.go_today("soak")
        self.away = False

    def _start_selftest(self) -> None:
        from gi.repository import GLib
        from calpi import tasks
        log.warning("soak: SELFTEST on virtual time (seed=%d speed=%s ticks=%d)", self.seed, self.speed,
                    self.selftest_ticks)
        warm = max(50, self.selftest_ticks // 2)
        state = {"n": 0, "a": None}

        def step():
            self._vt += TICK_S
            state["n"] += 1
            for name in self.sched.run_due(self._vt):
                self.counts[name] = self.counts.get(name, 0) + 1
            if self._minirun_running:
                return GLib.SOURCE_CONTINUE            # let a mini-run finish before measuring
            if state["a"] is None and state["n"] >= warm:
                self._settle()
                state["a"] = self.census()
                state["end"] = state["n"] + self.selftest_ticks
            elif state["a"] is not None and state["n"] >= state["end"]:
                self._settle()
                out = {"before": state["a"], "after": self.census(), "counts": self.counts,
                       "errors": self.sched.errors, "seed": self.seed}
                print("SOAK_SELFTEST " + json.dumps(out, sort_keys=True), flush=True)
                self.app.quit()
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        GLib.timeout_add(50, tasks.safe_callback(step, repeat=True))

    # ------------------------------------------------------------------ helpers
    def _on_calendar(self) -> bool:
        return self.win.navigator.current in ("calendar", None) and self._now() >= self.busy_until

    def _later(self, seconds: float, fn) -> None:
        self.sched.call_later(self._now(), seconds if self.virtual else seconds / self.speed, fn)

    # ------------------------------------------------------------------ actions
    def act_sync(self) -> None:
        eng = getattr(self.app, "sync", None)
        if eng is None:
            return
        self._sync_n += 1
        force = self._sync_n % 4 == 0
        eng.request_sync("soak", force=force)

    def act_month_nav(self) -> None:
        if not self._on_calendar():
            return
        mv = self.win.month_view
        if self.away:
            mv.go_today("soak")
            self.away = False
        else:
            delta = self.rng.choice([-3, -2, -1, 1, 2, 3])
            mv.go_relative(delta, "soak")
            self.away = True

    def act_day(self) -> None:
        if not self._on_calendar():
            return
        mv = self.win.month_view
        first, end = mv.visible_range()
        d = first + timedelta(days=self.rng.randrange(max(1, (end - first).days)))
        self.win.day_detail.open_day(d)
        self._later(4, lambda: self.win.navigator.back() if self.win.navigator.current == "day" else None)

    def act_settings(self) -> None:
        if not self._on_calendar():
            return
        nav = self.win.navigator
        screen = nav.get("settings")
        ids = [s.id for s in getattr(screen, "_specs", [])]
        nav.show("settings")
        self.busy_until = self._now() + (5 * (len(ids) + 2)) / (1 if self.virtual else self.speed)
        for i, sid in enumerate(ids):
            self._later(5 * (i + 1), lambda s=sid: screen.select(s) if nav.current == "settings" else None)
        self._later(5 * (len(ids) + 1), lambda: nav.back() if nav.current == "settings" else None)

    def act_osk(self) -> None:
        if not self._on_calendar():
            return
        from gi.repository import Gtk
        nav, kb = self.win.navigator, self.win.keyboard
        if self._osk_screen is None:               # created ONCE (a new screen every time would leak)
            box = Gtk.Box(css_classes=["screen"], valign=Gtk.Align.START)
            self._entry = Gtk.Entry(placeholder_text="soak", hexpand=True)
            box.append(self._entry)
            kb.attach(self._entry, "text", "Done")
            nav.add("soak_osk", box)
            self._osk_screen = box
        nav.show("soak_osk")
        self.busy_until = self._now() + 8 / (1 if self.virtual else self.speed)
        self._later(2, lambda: self._entry.grab_focus())
        self._later(5, lambda: (kb.hide(), nav.back() if nav.current == "soak_osk" else None))

    def act_dim(self) -> None:
        ctl = getattr(self.app, "dimming", None)
        if ctl is None or not hasattr(ctl, "preview"):
            return
        ctl.preview()

    def act_minirun(self) -> None:
        if self._minirun_running or not self._on_calendar():
            return
        from calpi import perf
        self._minirun_running = True
        samples: list[float] = []
        name = "month_change_soak"

        def listener(n, ms):
            if n == name:
                samples.append(ms)
        perf.add_listener(listener)
        mv = self.win.month_view
        self.win.navigator.reset("calendar")
        mv.go_today("soak")
        self.busy_until = float("inf")
        n = MINI_RUN_NAV
        step = {"i": 0}
        from gi.repository import GLib
        from calpi import tasks

        def finish():
            perf.remove_listener(listener)
            vals = samples[3:] or samples
            log.info("health: minirun month_nav n=%d p50=%.1fms p90=%.1fms", len(vals),
                     percentile(vals, 50), percentile(vals, 90))
            mv.go_today("soak")
            self.busy_until = 0.0
            self._minirun_running = False

        def go():
            if step["i"] >= n:
                finish()
                return GLib.SOURCE_REMOVE
            try:
                t0 = time.perf_counter()
                mv.go_relative(+1 if step["i"] % 2 == 0 else -1, "soak-minirun")
                perf.until_paint(name, self.win, t0)
            except Exception:
                log.exception("soak: mini-run step failed")
                step["i"] = n                       # end the run cleanly on the next step
            step["i"] += 1
            return GLib.SOURCE_CONTINUE
        GLib.timeout_add(max(20, int(400 / self.speed)), tasks.safe_callback(go, repeat=None))


_instance: Soak | None = None


def start(app) -> Soak:
    global _instance
    _instance = Soak(app)
    _instance.start()
    return _instance
