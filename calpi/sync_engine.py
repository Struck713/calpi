"""SyncEngine (US-16): schedules and launches the sync process, applies its result. Main thread only.

The heavy work happens in `python3 -m calpi.sync.worker` (a separate process, so parsing never
stutters the UI). IPC is one JSON line on stdout plus the SQLite database.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timezone

from gi.repository import Gio, GLib

from calpi import paths, watchdog
from calpi.data import timeutil
from calpi.data.settings_store import (K_ACCOUNTS, K_SYNC_INTERVAL_MINUTES, K_SYNC_WINDOW_BACK,
                                       K_SYNC_WINDOW_FORWARD)
from calpi.sync import retry
from calpi.sync.worker import RESULT_PREFIX
from calpi.tasks import safe_callback

log = logging.getLogger("calpi.sync_engine")


@dataclass
class Request:
    reason: str
    force: bool = False
    extra: tuple[date, date] | None = None

    def merge(self, other: "Request") -> "Request":
        if self.extra and other.extra:
            extra = (min(self.extra[0], other.extra[0]), max(self.extra[1], other.extra[1]))
        else:
            extra = self.extra or other.extra
        reason = self.reason if other.reason == self.reason else \
            "coalesced:" + ",".join(dict.fromkeys(
                r for x in (self.reason, other.reason) for r in x.removeprefix("coalesced:").split(",")))
        return Request(reason, self.force or other.force, extra)


def build_argv(req: Request, python: str | None = None) -> list[str]:
    argv = []
    for exe, args in (("/usr/bin/nice", ["-n", "10"]), ("/usr/bin/ionice", ["-c", "3"])):
        if os.path.exists(exe):
            argv += [exe, *args]
    argv += [python or sys.executable, "-m", "calpi.sync.worker", "--reason", req.reason]
    if req.force:
        argv.append("--force")
    if req.extra:
        argv += ["--extra-range", f"{req.extra[0].isoformat()}:{req.extra[1].isoformat()}"]
    return argv


def parse_result_line(text: str | None) -> dict | None:
    """The last CALPI_SYNC_RESULT line of the worker's stdout, or None if absent/malformed."""
    for line in reversed((text or "").splitlines()):
        if line.startswith(RESULT_PREFIX):
            try:
                r = json.loads(line[len(RESULT_PREFIX):])
            except ValueError:
                return None
            return r if isinstance(r, dict) and r.get("status") else None
    return None


def _parse_window(w) -> tuple[datetime, datetime] | None:
    try:
        a, b = (datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) for x in w)
        return a, b
    except (TypeError, ValueError):
        return None


class SyncEngine:
    TIMEOUT_S = 180
    FIRST_DELAY_S = 10
    ACCOUNTS_DEBOUNCE_S = 2
    BROWSE_DEBOUNCE_S = 3

    def __init__(self, app, spawn=None, timeout_add=None, source_remove=None, monotonic=None):
        self.app = app
        self._spawn = spawn or self._spawn_real            # (Request, on_done(stdout|None)) -> handle
        self._timeout_add = timeout_add or GLib.timeout_add_seconds
        self._source_remove = source_remove or GLib.source_remove
        self._mono = monotonic or time.monotonic
        self._running = None                               # handle with .force_exit()
        self._pending: Request | None = None
        self._timer_id = 0
        self._timeout_id = 0
        self._timed_out = False
        self._debounce: dict[str, tuple[int, Request]] = {}
        self._last_end_mono: float | None = None
        self._started = False
        self.next_run_mono: float | None = None           # US-27: monotonic deadline of the armed timer
        self._first_force = False
        self.last_result: dict | None = None
        self.last_success_wall: datetime | None = None
        self.policy = retry.RetryPolicy()                  # US-17
        self.offline = False                               # US-17: last run failed with network errors
        self._offline_since: float | None = None
        self.synced_window: tuple[datetime, datetime] | None = None
        self.result_callbacks: list = []
        self.state_callbacks: list = []                    # (running: bool) -> None

    @property
    def is_running(self) -> bool:
        return self._running is not None

    # --- lifecycle ---
    def start(self) -> None:
        if getattr(self.app, "safe_mode", False):
            log.warning("sync: safe mode, automatic sync disabled")
            return
        if self._started:
            return
        self._started = True
        log.info("sync: startup, first run in %ss, interval %s min", self.FIRST_DELAY_S, self.interval_minutes())
        self._arm(self.FIRST_DELAY_S)
        st = self.app.settings
        st.subscribe(K_SYNC_INTERVAL_MINUTES, lambda *_: self._reschedule())
        st.subscribe(K_ACCOUNTS, lambda *_: self._debounced("accounts", self.ACCOUNTS_DEBOUNCE_S,
                                                            Request("accounts-changed")))
        clock = getattr(self.app, "clock", None)
        if clock is not None:
            clock.subscribe_day_changed(lambda _o, _n: self.request_sync("day-changed"))
            clock.subscribe_tz_changed(lambda: self.request_sync("tz-changed", force=True))
        win = getattr(self.app, "window", None)
        if win is not None and hasattr(win, "month_view"):
            win.month_view.month_changed_callbacks.append(self._on_month_changed)
        if os.environ.get("CALPI_TEST_SYNC_ON_START") == "force":   # dev/Pi test hook
            self._first_force = True

    def interval_minutes(self) -> int:
        return self.app.settings.get(K_SYNC_INTERVAL_MINUTES)

    # --- timers ---
    def _arm(self, seconds: float) -> None:
        if self._timer_id:
            self._source_remove(self._timer_id)
        self._timer_id = self._timeout_add(max(1, int(seconds + 0.999)), self._on_timer)

    @safe_callback(repeat=False)
    def _on_timer(self):
        self._timer_id = 0
        self.next_run_mono = self._mono() + seconds          # US-27: read by the Sync settings section

    def next_run_in_seconds(self) -> float | None:
        """Seconds until the next scheduled run, or None if none is scheduled (running / paused)."""
        if self.next_run_mono is None:
            return None
        return max(0.0, self.next_run_mono - self._mono())
        first = self._last_end_mono is None
        self.request_sync("startup" if first else "interval", force=first and self._first_force)

    def _reschedule(self) -> None:
        if not self._started or self._running or self._pending or self._last_end_mono is None:
            return                                          # re-armed when the run ends / first run pending
        due = self._last_end_mono + self.interval_minutes() * 60 - self._mono()
        self._arm(max(0, due))
        log.info("sync: interval changed to %s min, next in %ds", self.interval_minutes(), max(1, due))

    def _debounced(self, name: str, seconds: float, req: Request) -> None:
        old = self._debounce.pop(name, None)
        if old:
            self._source_remove(old[0])

        def fire(_name=name):
            _id, r = self._debounce.pop(_name, (0, None))
            if r is not None:
                self.request_sync(r.reason, r.force, r.extra)
            return GLib.SOURCE_REMOVE
        fire = safe_callback(fire, repeat=False)
        self._debounce[name] = (self._timeout_add(max(1, int(seconds)), fire), req)

    # --- requests ---
    def request_sync(self, reason: str, force: bool = False, extra=None) -> None:
        req = Request(reason, force, extra)
        if self._running is not None:
            self._pending = req if self._pending is None else self._pending.merge(req)
            log.info("sync: already running; queued %s", reason)
            return
        if self._timer_id:                     # a manual/trigger run replaces the pending scheduled one
            self._source_remove(self._timer_id)
            self._timer_id = 0
        self._launch(req)

    def _launch(self, req: Request) -> None:
        log.info("sync: starting (%s%s)", req.reason, ", forced" if req.force else "")
        self._timed_out = False
        try:
            self._running = self._spawn(req, self._on_done)
        except Exception:
            log.exception("sync: could not start the worker")
        self.next_run_mono = None
            self._running = object()           # so _finish sees a run in progress
            self._finish(None)
            return
        self._timeout_id = self._timeout_add(self.TIMEOUT_S, self._on_timeout)
        self._notify_state(True)

    @safe_callback(repeat=False)
    def _on_timeout(self):
        self._timeout_id = 0
        log.warning("sync: worker exceeded %ss, killing it", self.TIMEOUT_S)
        self._timed_out = True
        run = self._running
        if run is not None and hasattr(run, "force_exit"):
            run.force_exit()

    def _on_done(self, stdout: str | None) -> None:
        try:
            self._finish(stdout)
        except Exception:
            log.exception("sync: handling the worker result failed")
            self._running = None
            self._arm(self.interval_minutes() * 60)

    def _finish(self, stdout: str | None) -> None:
        if self._timeout_id:
            self._source_remove(self._timeout_id)
            self._timeout_id = 0
        r = None if self._timed_out else parse_result_line(stdout)
        if r is None:
            code = "TIMEOUT" if self._timed_out else "UNKNOWN"
            log.error("sync: worker produced no usable result (%s)", code)
            r = self._synthetic(code)
        self._running = None
        self._last_end_mono = self._mono()
        delay = self._apply_policy(r)
        self._handle_result(r)
        self._notify_state(False)
        if self._pending is not None:
            req, self._pending = self._pending, None
            self._launch(req)
        else:
            self._arm(delay)

    def _apply_policy(self, r: dict) -> int:
        """US-17: next delay from the retry policy; tracks the offline flag and logs transitions."""
        interval = self.interval_minutes() * 60
        kind = retry.classify(r)
        delay = self.policy.next_delay(kind, retry.max_retry_after(r), interval)
        now_off = retry.is_offline(r)
        if now_off and not self.offline:
            codes = sorted({a.get("error") for a in r.get("accounts", []) if a.get("error")})
            log.info("sync: offline (%s); retrying in %dm", ",".join(codes), max(1, round(delay / 60)))
            self._offline_since = self._mono()
        elif now_off:
            log.debug("sync: still offline; retrying in %ds", delay)
        elif self.offline:
            since = self._offline_since
            mins = round((self._mono() - since) / 60) if since is not None else 0
            log.info("sync: back online after %dm", mins)
            self._offline_since = None
        elif kind == "transient":
            log.debug("sync: transient failure; retrying in %ds", delay)
        self.offline = now_off
        return delay

    NETWORK_UP_DEBOUNCE_S = 5

    def on_network_change(self, old, new) -> None:
        """US-17: NetworkMonitor callback. Coming online triggers a sync 5 s later (bypasses backoff)."""
        if getattr(new, "name", "") == "ONLINE" and getattr(old, "name", "") != "ONLINE":
            self._debounced("network", self.NETWORK_UP_DEBOUNCE_S, Request("network-up"))

    def schedule_retry(self, delay_s: float) -> None:
        """Arm the next scheduled run `delay_s` from now (no-op while a run is active)."""
        if self._started and self._running is None and self._pending is None:
            self._arm(delay_s)

    def _synthetic(self, code: str) -> dict:
        try:
            from calpi.data.accounts import list_accounts
            ids = [a.id for a in list_accounts(self.app.settings)]
        except Exception:
            ids = []
        return {"v": 1, "status": "crashed", "reason": "worker", "changed": False,
                "accounts": [{"account_id": i, "error": code, "detail": "sync process failed",
                              "retry_after": None, "calendars": []} for i in ids]}

    def _handle_result(self, r: dict) -> None:
        self.last_result = r
        if r.get("status") == "done":
            w = _parse_window(r.get("window"))
            if w:
                sw = self.synced_window
                self.synced_window = w if sw is None else (min(sw[0], w[0]), max(sw[1], w[1]))
            accts = r.get("accounts", [])
            if not accts or any(a.get("error") is None for a in accts):
                self.last_success_wall = timeutil.now()
                watchdog.status(f"last sync {self.last_success_wall:%H:%M}")
            if r.get("changed"):
                try:
                    self.app.on_data_changed()
                except Exception:
                    log.exception("on_data_changed failed")
        for cb in list(self.result_callbacks):
            try:
                cb(r)
            except Exception:
                log.exception("sync result callback failed")
        log.info("sync: %s %s in %s ms, changed=%s, errors=%s", r.get("status"), r.get("reason"),
                 r.get("duration_ms"), r.get("changed"),
                 [a["error"] for a in r.get("accounts", []) if a.get("error")])

    def _notify_state(self, running: bool) -> None:
        for cb in list(self.state_callbacks):
            try:
                cb(running)
            except Exception:
                log.exception("sync state callback failed")

    # --- browsing outside the synced window ---
    def _default_window(self):
        from calpi.sync.fetch import compute_window
        st = self.app.settings
        return compute_window(timeutil.today(), timeutil.display_tz(),
                              st.get(K_SYNC_WINDOW_BACK), st.get(K_SYNC_WINDOW_FORWARD))

    def _inside_synced_window(self, first: date, end: date) -> bool:
        w = self.synced_window or self._default_window()
        tz = timeutil.display_tz()
        mid = lambda d: datetime.combine(d, dtime.min, tz).astimezone(timezone.utc)   # noqa: E731
        return mid(first) >= w[0] and mid(end) <= w[1]

    def _on_month_changed(self, _y, _m) -> None:
        first, end = self.app.window.month_view.visible_range()
        if self._inside_synced_window(first, end):
            return
        self._debounced("browse", self.BROWSE_DEBOUNCE_S, Request("browse", extra=(first, end)))

    # --- real spawner ---
    def _spawn_real(self, req: Request, on_done):
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE)   # stderr inherited -> journal
        launcher.set_cwd(str(paths.app_dir().parent))
        launcher.unsetenv("NOTIFY_SOCKET")                  # D1: the worker must never ping the watchdog
        proc = launcher.spawnv(build_argv(req))

        def cb(p, res, _data=None):
            try:
                _ok, out, _err = p.communicate_utf8_finish(res)
            except GLib.Error as e:
                log.error("sync: reading worker output failed: %s", e)
                out = None
            on_done(out)
        proc.communicate_utf8_async(None, None, cb, None)
        return proc
