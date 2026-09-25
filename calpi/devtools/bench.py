"""Scripted benchmark driver (US-36). Dev-only: enabled by CALPI_BENCH=1, never in normal operation.

Runs the D2 scenarios through GLib timeouts (the main loop runs normally between steps), prints one
`CALPI_BENCH_RESULT {json}` line, writes <runtime_dir>/bench.json and quits the app.
A marker <runtime_dir>/bench.done stops systemd's restart from starting a second run (scripts/pi perf removes it).

Env: CALPI_BENCH_SCENARIOS (comma list), CALPI_BENCH_STEP_MS (default 400), CALPI_BENCH_IDLE_S (default 300),
     CALPI_BENCH_N (scale iteration counts down for local smoke runs, default 1.0).
"""
from __future__ import annotations

import json
import logging
import os
import platform
import time
from datetime import timedelta

from gi.repository import GLib, Gtk

from calpi import paths, perf

log = logging.getLogger("calpi.bench")

DEFAULT_SCENARIOS = "startup,month_nav,day_open,settings_open,osk,idle"
ALL_SCENARIOS = DEFAULT_SCENARIOS + ",week_nav,during_sync"
WARMUP = 5
_DONE = "bench.done"


def _iters(n: int) -> int:
    f = float(os.environ.get("CALPI_BENCH_N", "1"))
    return max(WARMUP + 2, int(n * f)) if f < 1 else n


class Bench:
    def __init__(self, app, scenarios: list[str]):
        self.app, self.win = app, app.window
        self.scenarios = scenarios
        self.step_ms = int(os.environ.get("CALPI_BENCH_STEP_MS", "400"))
        self.results: dict = {}
        self.meta: dict = {}

    # ------------------------------------------------------------------ helpers
    def _do(self, name: str, fn) -> None:
        """Run fn (the 'input') and record input -> next painted frame under `name`."""
        t0 = time.perf_counter()
        fn()
        perf.record(name + "_sync", (time.perf_counter() - t0) * 1000)     # main-thread cost, no paint
        perf.until_paint(name, self.win, t0)

    def _summary(self, *names: str) -> dict:
        rep = perf.report()
        out = {}
        for n in names:
            for k in (n, n + "_sync"):
                if k in rep:
                    out[k] = perf.stats(k, skip=WARMUP)
        return out

    def _clear(self, *names: str) -> None:
        with perf._lock:
            for n in names:
                perf._samples.pop(n, None)
                perf._no_paint.pop(n, None)

    # ------------------------------------------------------------------ scenarios
    def sc_startup(self):
        yield 1500                                  # marks arrive on the first paints
        self.results["startup"] = {n: perf.stats(n) for n in
                                   ("start_to_first_paint", "boot_to_first_paint", "start_to_events_paint")
                                   if perf.stats(n)["n"]}

    def _month_nav(self, name: str, key: str):
        self._clear(name)
        mv = self.win.month_view
        self.win.navigator.reset("calendar")
        n = _iters(60)
        rss = [_r(perf.rss_mb())]
        for delta in (+1, -1):
            for _ in range(n):
                self._do(name, lambda d=delta: mv.go_relative(d, "bench"))
                yield self.step_ms
            rss.append(_r(perf.rss_mb()))
        self.results[key] = {**self._summary(name, "month_render"), "rss_mb": rss}

    def sc_month_nav(self):
        yield from self._month_nav("month_change", "month_nav")

    def sc_week_nav(self):
        wv, name = self.win.week_view, "week_change"
        self._clear(name, "week_render")
        self.win.show_view("week", reason="bench")
        yield self.step_ms
        n = _iters(30)
        for delta in (+1, -1):
            for _ in range(n):
                self._do(name, lambda d=delta: wv.go_relative(d, "bench"))
                yield self.step_ms
        self.win.show_view("month", reason="bench")
        self.results["week_nav"] = self._summary(name, "week_render")

    def sc_during_sync(self):
        eng = getattr(self.app, "sync", None)
        if eng is None:
            self.results["during_sync"] = {"skipped": "no sync engine"}
            return
        eng.request_sync("bench", force=True)
        yield 300
        self.results["during_sync_running"] = bool(eng.is_running)
        yield from self._month_nav("month_change_sync", "during_sync")

    def sc_day_open(self):
        from calpi.data import timeutil
        nav, mv = self.win.navigator, self.win.month_view
        mv.show_month(*timeutil.today().timetuple()[:2])
        yield self.step_ms
        first, end = mv.visible_range()
        tz = timeutil.display_tz()
        evs = self.app.store.events_for_days(first, end, tz)
        days = sorted({d for d in (self._event_day(e, tz) for e in evs) if first <= d < end}) or [timeutil.today()]
        self._clear("day_open", "screen_calendar", "screen_day")
        for i in range(_iters(30)):
            d = days[i % len(days)]
            self._do("day_open_bench", lambda d=d: self.win.day_detail.open_day(d))
            yield self.step_ms
            self._do("back_to_calendar", lambda: nav.back())
            yield self.step_ms
        self.results["day_open"] = self._summary("day_open", "day_open_bench", "back_to_calendar")

    @staticmethod
    def _event_day(e, tz):
        s = e.start
        return s if e.all_day else s.astimezone(tz).date()

    def sc_settings_open(self):
        nav = self.win.navigator
        screen = nav.get("settings")
        self._clear("settings_open", "settings_back")
        self._do("settings_open_first", lambda: nav.show("settings"))
        yield self.step_ms
        for spec in list(getattr(screen, "_specs", [])):     # first open of each section
            self._do(f"settings_section_first_{spec.id}", lambda s=spec.id: screen.select(s))
            yield self.step_ms
        nav.back()
        yield self.step_ms
        for _ in range(_iters(30)):
            self._do("settings_open", lambda: nav.show("settings"))
            yield self.step_ms
            self._do("settings_back", lambda: nav.back())
            yield self.step_ms
        rep = perf.report()
        self.results["settings_open"] = {
            **self._summary("settings_open", "settings_back"),
            "first": {k: v for k, v in rep.items() if k.startswith(("settings_open_first", "settings_section_first_"))}}

    def sc_osk(self):
        from calpi.data.keyboard_layouts import Key
        kb, nav = self.win.keyboard, self.win.navigator
        box = Gtk.Box(css_classes=["screen"], valign=Gtk.Align.START)
        entry = Gtk.Entry(placeholder_text="bench", hexpand=True)
        box.append(entry)
        kb.attach(entry, "text", "Done")
        nav.add("bench_osk", box)
        nav.show("bench_osk")
        yield self.step_ms
        self._clear("osk_show_first", "osk_show", "osk_key")
        for _ in range(_iters(10)):
            self._do("osk_focus", lambda: entry.grab_focus())
            yield self.step_ms
            kb.hide()
            yield self.step_ms
            entry.set_focus_on_click(True)
            self.win.set_focus(None)
            yield 100
        kb._show_for(entry, "text", "Done", None)
        yield self.step_ms
        for i in range(_iters(50)):
            kb._apply(Key("a", insert="a"))
            yield self.step_ms
        kb.hide()
        nav.back()
        self.results["osk"] = {n: perf.stats(n) for n in ("osk_show_first", "osk_show", "osk_key")
                               if perf.stats(n)["n"]}

    def sc_idle(self):
        secs = float(os.environ.get("CALPI_BENCH_IDLE_S", "300"))
        tck = os.sysconf("SC_CLK_TCK")
        me, cage = "self", os.getppid()
        t0, a0, c0 = time.monotonic(), perf.cpu_ticks(me), perf.cpu_ticks(cage)
        w0 = _ctx_switches()
        yield int(secs * 1000)
        dt = time.monotonic() - t0
        a1, c1 = perf.cpu_ticks(me), perf.cpu_ticks(cage)
        w1 = _ctx_switches()
        res = {"seconds": round(dt, 1)}
        if a0 is not None and a1 is not None:
            res["app_cpu_pct"] = round((a1 - a0) / tck / dt * 100, 2)
        if c0 is not None and c1 is not None and cage > 1:
            res["parent_cpu_pct"] = round((c1 - c0) / tck / dt * 100, 2)
            res["parent_cmd"] = _comm(cage)
        if "app_cpu_pct" in res:
            res["total_cpu_pct"] = round(res["app_cpu_pct"] + res.get("parent_cpu_pct", 0), 2)
        if w0 is not None and w1 is not None:
            res["app_wakeups_per_s"] = round((w1 - w0) / dt, 2)     # voluntary context switches
        self.results["idle"] = res

    # ------------------------------------------------------------------ driver
    def _gen(self):
        self.meta = self._meta("before")
        for name in self.scenarios:
            fn = getattr(self, "sc_" + name, None)
            if fn is None:
                self.results[name] = {"error": "unknown scenario"}
                continue
            log.info("bench: scenario %s", name)
            try:
                yield from fn()
            except Exception as e:
                log.exception("bench scenario %s failed", name)
                self.results[name] = {"error": repr(e)}
            self.meta.setdefault("rss_mb_after", {})[name] = _r(perf.rss_mb())
        self.meta.update(self._meta("after"))

    def _meta(self, when: str) -> dict:
        out = {}
        try:
            from calpi.system import device_info
            di = device_info.collect()
            out[f"throttled_{when}"] = {k: v for k, v in di.throttled.items() if v} if di.power_known else None
            out[f"temp_c_{when}"] = di.temp_c
        except Exception:
            pass
        if when == "before":
            from calpi.app import _build_stamp
            out.update(build=_build_stamp(), python=platform.python_version(),
                       gtk=f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}",
                       renderer=os.environ.get("GSK_RENDERER"), events=self.app.store.count_events(),
                       state_dir=str(paths.state_dir()), scenarios=self.scenarios,
                       rss_mb_start=_r(perf.rss_mb()), machine=platform.machine())
        return out

    def run(self) -> None:
        gen = self._gen()

        def step():
            try:
                delay = next(gen)
            except StopIteration:
                self._finish()
                return GLib.SOURCE_REMOVE
            except Exception:
                log.exception("bench driver failed")
                self._finish()
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(max(1, int(delay)), step)
            return GLib.SOURCE_REMOVE
        GLib.timeout_add(3000, step)                # let startup settle

    def _finish(self) -> None:
        self.meta["rss_mb_end"] = _r(perf.rss_mb())
        out = {"report": perf.report(), "scenarios": self.results, "meta": self.meta}
        text = json.dumps(out, sort_keys=True)
        print("CALPI_BENCH_RESULT " + text, flush=True)
        try:
            (paths.runtime_dir() / "bench.json").write_text(text)
            (paths.runtime_dir() / _DONE).write_text("done\n")
        except OSError:
            log.exception("bench: could not write results")
        self.app.quit()


def _r(v):
    return None if v is None else round(v, 1)


def _ctx_switches() -> int | None:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("voluntary_ctxt_switches:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def _comm(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return "?"


def start(app, scenarios: str = DEFAULT_SCENARIOS) -> None:
    if (paths.runtime_dir() / _DONE).exists():
        log.info("bench: %s exists, not running again", _DONE)
        return
    names = [s.strip() for s in scenarios.split(",") if s.strip()]
    Bench(app, names).run()
