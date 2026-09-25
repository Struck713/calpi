# US-16 — Scheduled background sync

| | |
|---|---|
| **Epic** | 2. Calendar Syncing |
| **Priority** | P0 |
| **Blocked by** | US-05 Settings store, US-15 Event fetching and parsing |
| **Blocks** | US-17 Offline resilience, US-18 Sync status tracking, US-19 Manual refresh, US-27 Sync settings, US-36 Performance targets, US-37 Long-running stability |
| **Phase** | 2. Syncing |

## Story

> As a user, I want events refreshed on my chosen schedule without the display stuttering or freezing.

## Context

US-15 can sync an account when it's run by hand. This story makes it **run by itself**, on a schedule, **without ever affecting the display**. It's the heart of the "Always current" goal.

The architecture (see the README) runs sync in a **separate, short-lived process**:
```
UI process (GTK main loop)                     sync process (one per run)
  SyncEngine ──spawn (Gio.Subprocess)──▶  nice ionice python3 -m calpi.sync.worker --reason interval
     ▲                                           │ reads settings.json, credentials, writes calpi.sqlite3
     └──── one JSON line on stdout ◀─────────────┘ exits
  → app.on_data_changed() if anything changed → month view / day detail reload from SQLite
```
Why a process and not a thread (decided, don't reopen): CPU-heavy iCalendar parsing would hold the GIL and make the UI stutter on the Pi 3B. Memory is fully returned when the process exits (US-37). A crash or hang in parsing can't take down the display (US-12), and the UI process never imports the heavy libraries (US-36).

This story builds:
1. `calpi/sync/worker.py`: the sync process entry point (no gi).
2. `calpi/sync_engine.py`: `SyncEngine` in the UI process. It schedules runs, starts the worker asynchronously, enforces a timeout, **coalesces** requests, parses the result, and triggers the UI reload.
3. The `sync_interval_minutes` setting (the UI to change it is US-27).
4. A minimal sync indicator in the header ("Updated 14:05" / "Updating…"). US-17, US-18, US-19, and US-38 build on it.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-05** Settings store | `SettingsStore` with `subscribe`, the key registry, and `app.settings` | `grep -n "def subscribe" calpi/data/settings_store.py`. The settings tests pass. |
| **US-15** Event fetching and parsing | `fetch.sync_account`, `compute_window`, `AccountResult`/`CalendarResult`, `EventStore.apply_calendar_sync`, the window keys, the CLI `fetch` **working against the real account** | `/usr/bin/python3 -m pytest tests/test_fetch.py tests/test_ical_parse.py` passes, **and** `cli fetch --account <id>` on the Pi succeeds (US-15 acceptance criterion 11). |

### Soft dependencies

| Soft blocker | Why | If it isn't done |
|---|---|---|
| **US-07** (grid) + `MonthView.reload()` | The UI reload after a sync | Required in practice. It's on the critical path before this story. |
| **US-09** `MainWindow.on_data_changed()` | Reloads the day detail too | Call `month_view.reload()` directly, and leave a note. |
| **US-10** `app.clock.subscribe_day_changed` | The window rolls at midnight | Skip that trigger and note it. |
| **US-12** `app.safe_mode`, the watchdog | No automatic sync in safe mode, and `watchdog.status()` | Add the check if `safe_mode` exists. |
| **US-13** `install_log_redaction()` | Must be called in the worker | It exists (US-14 → US-13). |
| **US-03** | Checking on the Pi | Required for acceptance criteria 8–9. |

### External blockers
- **The owner's account saved on the Pi** (from US-14/15), for the real checks.
- **`ionice` and `nice`** on the Pi (`util-linux` and `coreutils`, always there on Pi OS). Check `which ionice nice`.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| The worker's logs don't appear in the journal | The worker's stderr must be **inherited** from the UI process (whose stderr is the journal). With `Gio.Subprocess`, use `STDOUT_PIPE` only, and **not** `STDERR_PIPE` or `STDERR_SILENCE`. |
| `Gio.Subprocess.communicate_utf8_async` callback signature confusion | In PyGObject: `proc.communicate_utf8_async(None, cancellable, callback, user_data)`, then in the callback `ok, stdout, stderr = proc.communicate_utf8_finish(result)`. Check it with a trivial `echo` subprocess in the devcontainer first. |
| `database is locked` in the worker while the UI reads | WAL readers don't block writers, but `busy_timeout` (5 s) covers checkpoints. If it still happens, the UI is holding a read transaction open. Make sure the UI never leaves a cursor open (fetch everything with `fetchall()`). |
| Two syncs at once (the CLI and the app, or two app triggers) | The worker takes an exclusive `flock` on `/run/calpi/sync.lock`. A second worker exits at once with `status: "busy"`. The engine coalesces its own requests. |

---

## Scope

### In scope
- `calpi/sync/worker.py` and its stdout JSON protocol.
- `calpi/sync_engine.py`: `SyncEngine` (scheduling, triggers, coalescing, timeout, the result hand-off).
- The settings key `K_SYNC_INTERVAL_MINUTES` (default 15).
- Triggers: startup, interval, a change to the account list, a zone change (forced), midnight (the window rolls), and browsing outside the synced window (the extra range).
- The minimal header indicator.
- Measurements showing the UI doesn't stutter.

### Out of scope
- Backoff and retry on errors, network detection (US-17); storing per-calendar status (US-18: but the engine exposes the results through callbacks); the manual refresh button (US-19: but `request_sync(reason="manual")` exists); the interval UI (US-27); error messages for users (US-38).

---

## Acceptance criteria

1. The worker: `python3 -m calpi.sync.worker [--reason R] [--force] [--extra-range YYYY-MM-DD:YYYY-MM-DD] [--account ID]` syncs every account (or one), and prints **exactly one line** to stdout: `CALPI_SYNC_RESULT {json}` (the schema is in D3). The exit code is 0 when the run finished (even with account errors), 3 when another sync holds the lock, and 1 when the worker itself crashed. All logs go to stderr.
2. The worker runs at a lower priority (`nice -n 10`, `ionice -c 3`), takes `flock` on `<runtime_dir>/sync.lock`, calls `install_log_redaction()`, reads settings and credentials fresh, and applies the display zone from settings (`timeutil.set_display_tz`) before computing the window.
3. `SyncEngine.request_sync(reason, force=False, extra_range=None)`: if no sync is running, it starts one. If one **is** running, it records **one** pending request (merging `force` with OR, and extra ranges by union), which starts as soon as the current run finishes. There are never two workers at once from the same app.
4. **The schedule**: the first sync starts **10 s after the first frame** (not before, so boot isn't slowed). Then every `sync_interval_minutes` measured **from the end of the previous run** (monotonic). Changing the setting reschedules at once (the next run = the last end + the new interval, or now if that's already past).
5. Triggers: a change to `K_ACCOUNTS` → a sync in 2 s (debounced). A change to the display zone → a forced sync. A day change (US-10) → a sync (the window rolls). **A month change that shows dates outside the synced window** → a sync with `extra_range = visible range`, debounced 3 s (so browsing quickly through months starts one sync, not ten).
6. **Timeout**: a worker running longer than **180 s** is killed (`force_exit`), and the run is treated as `TIMEOUT` for every account. The next scheduled run is unaffected.
7. **After each run**: if `result.changed` is true, `app.on_data_changed()` is called **once**. The result is passed to every `engine.result_callbacks` subscriber. The header shows `Updated HH:MM` (the local time the last successful run finished), or `Updating…` while a run is active.
8. **No stutter** (on the Pi): while a forced full sync runs, month changes (a test hook changing months every 1.5 s, or the owner clicking) still render in **p90 < 150 ms**, and the watchdog never fires. Record the `perf: month_render` numbers with and without the sync running.
9. **No leaks per run**: 100 consecutive syncs (interval temporarily set to 1 minute, **or** a test hook that requests a sync every 20 s) → the UI process RSS doesn't grow by more than 5 MB, the fd count (`ls /proc/<pid>/fd | wc -l`) is stable, and there are no zombie processes (`ps -o stat= --ppid <ui pid>` shows no `Z`).
10. In safe mode (US-12), no automatic sync is scheduled. `request_sync(reason="manual")` still works.
11. A malformed worker output (no result line, bad JSON, or a crash) is logged at ERROR, handled as `UNKNOWN` for every account, and the schedule continues.
12. Tests: the engine is tested with a **fake spawner** (no real processes), covering coalescing, scheduling, timeouts, and debouncing. The worker's `run()` is tested with injected dependencies (a fake transport, a temporary state directory).

---

## Design decisions (already made)

- **D1. Command line**: `["/usr/bin/nice", "-n", "10", "/usr/bin/ionice", "-c", "3", sys.executable, "-m", "calpi.sync.worker", ...]`, with `cwd` = the app directory (`/opt/calpi`), so `-m calpi...` resolves. The environment is inherited (`STATE_DIRECTORY`, `RUNTIME_DIRECTORY`, `CALPI_*`, `NOTIFY_SOCKET`). **Remove `NOTIFY_SOCKET` from the child's environment** (use `Gio.SubprocessLauncher.unsetenv`), so the worker can never send watchdog messages by accident.
- **D2. Only one kind of IPC**: stdout JSON at the end, plus the database. **No** progress streaming, pipes, D-Bus, or sockets. Simple and robust.
- **D3. The result JSON** (version 1):
  ```json
  {"v":1,"reason":"interval","started":"2026-09-25T14:05:00Z","finished":"2026-09-25T14:05:07Z","duration_ms":7012,
   "status":"done",                               // done | busy | crashed
   "changed":true, "revision_before":41, "revision_after":44,
   "window":["2026-07-01T00:00:00Z","2027-10-01T00:00:00Z"],
   "accounts":[{"account_id":"icloud-1a2b3c4d","error":null,"detail":"","retry_after":null,
                "calendars":[{"calendar_id":"icloud-1a2b3c4d:9f…","name":"Family","status":"ok","events":213,
                              "error":null,"detail":"","duration_ms":2310,"parse_errors":0}]}]}
  ```
  `changed` = `revision_after != revision_before` (the US-04 revision counter).
- **D4. The engine's states**: `IDLE`, `RUNNING`. It holds `self._pending: Request | None`, `self._timer_id`, `self._last_end_mono`, `self._last_success_wall`. **All engine methods run on the main thread.**
- **D5. Missing credentials**: if `CredentialStore.status()` is `unreadable`, or the secret for an account is missing, the worker reports `error="CREDENTIALS_UNREADABLE"` for that account without any network call.
- **D6. The extra range**: when `MonthView.visible_range()` isn't inside the synced window. The engine keeps the last window it got from a result (`result.window`) to decide. Before the first result, it assumes the default window.
- **D7. The header indicator** is a `Gtk.Label` (css `sync-status`) in `header.end_slot`, as the **first** child. There's no spinner (no animation): the word "Updating…" is enough. The text is updated only when it changes.

---

## Implementation plan

### Step 1 — The settings key
`K_SYNC_INTERVAL_MINUTES = "sync_interval_minutes"`, type int, default 15, validator `v in (5, 10, 15, 30, 60, 120, 240)`. US-27 shows exactly these choices. **Keep the tuple in one place** (`SYNC_INTERVAL_CHOICES`) and import it in US-27.

### Step 2 — `calpi/sync/worker.py`
```python
RESULT_PREFIX = "CALPI_SYNC_RESULT "

def main(argv=None) -> int:
    setup_logging(); install_log_redaction()
    args = parse_args(argv)
    lock = _acquire_lock()                 # fcntl.flock(LOCK_EX | LOCK_NB) on runtime_dir()/sync.lock
    if lock is None:
        _emit({"v":1,"status":"busy","reason":args.reason}); return 3
    try:
        result = run(args, deps=Deps.default())
        _emit(result); return 0
    except Exception as e:
        log.exception("sync worker crashed")
        _emit({"v":1,"status":"crashed","reason":args.reason,"detail":type(e).__name__}); return 1

def run(args, deps) -> dict:
    settings = deps.settings()             # SettingsStore(read-only use)
    timeutil.set_display_tz(settings.get(K_TIMEZONE) if K_TIMEZONE in REGISTRY else None)
    store, creds = deps.store(), deps.credentials()
    window = compute_window(timeutil.today(), timeutil.display_tz(),
                            settings.get(K_SYNC_WINDOW_BACK), settings.get(K_SYNC_WINDOW_FORWARD),
                            extra=args.extra_range)
    rev0 = store.revision(); started = utcnow()
    accounts = [a for a in list_accounts(settings) if not args.account or a.id == args.account]
    out = []
    for acc in accounts:
        secret = creds.get(acc.id) if creds.status() != "unreadable" else None
        if secret is None:
            out.append(_account_error(acc, "CREDENTIALS_UNREADABLE", "no readable credentials")); continue
        out.append(_serialize(sync_account(acc, secret, store, window, force=args.force, client=deps.client(acc))))
    rev1 = store.revision()
    return {"v":1,"status":"done","reason":args.reason, "started":..., "finished":..., "duration_ms":...,
            "changed": rev1 != rev0, "revision_before": rev0, "revision_after": rev1,
            "window":[window[0].isoformat(), window[1].isoformat()], "accounts": out}

if __name__ == "__main__":
    raise SystemExit(main())
```
- `_emit` prints `RESULT_PREFIX + json.dumps(obj, separators=(",",":"))` and flushes. **Make sure nothing else prints to stdout**: all logging goes to stderr (set `stream=sys.stderr` in the worker's `setup_logging` call, or give `logging_setup` a parameter).
- `K_TIMEZONE` may not exist yet (US-28). Guard it as shown, or register it now with default `None` (that's allowed: US-28 then only adds the UI).
- `Deps` is a small dataclass of factories, so tests can inject a temporary state directory and a fake HTTP transport.
- `sys.path`: when it's run with `-m` from `cwd=/opt/calpi`, `calpi` is importable. Also add the `run.py`-style `sys.path` guard for safety.

### Step 3 — `calpi/sync_engine.py`
```python
@dataclass
class Request:
    reason: str
    force: bool = False
    extra: tuple[date, date] | None = None
    def merge(self, other): ...           # force OR, extra = union (min start, max end), reason = "coalesced:" + ...

class SyncEngine:
    TIMEOUT_S = 180
    FIRST_DELAY_S = 10

    def __init__(self, app, spawn=None):
        self.app = app
        self._spawn = spawn or self._spawn_real          # test seam
        self._running = None                              # handle of the running proc
        self._pending: Request | None = None
        self._timer_id = 0
        self._timeout_id = 0
        self._last_end_mono: float | None = None
        self.last_result: dict | None = None
        self.last_success_wall: datetime | None = None
        self.synced_window: tuple[datetime, datetime] | None = None
        self.result_callbacks: list = []
        self.state_callbacks: list = []                   # (running: bool) -> None, for the header/US-19

    def start(self):
        if self.app.safe_mode: log.warning("sync: safe mode, automatic sync disabled"); return
        self._arm(self.FIRST_DELAY_S)
        self.app.settings.subscribe(K_SYNC_INTERVAL_MINUTES, lambda *_: self._reschedule())
        self.app.settings.subscribe(K_ACCOUNTS, lambda *_: self._debounced("accounts", 2))
        ...

    def request_sync(self, reason, force=False, extra=None):
        req = Request(reason, force, extra)
        if self._running:
            self._pending = req if self._pending is None else self._pending.merge(req)
            log.info("sync: already running; queued %s", reason); return
        self._launch(req)
```
- `_arm(seconds)`: remove any existing timer, then `GLib.timeout_add_seconds(seconds, self._on_timer)`. `_on_timer` → `request_sync("interval")`, and return `SOURCE_REMOVE` (it's re-armed after the run ends).
- `_launch(req)`: build argv (D1), spawn with `Gio.SubprocessLauncher(flags=Gio.SubprocessFlags.STDOUT_PIPE)`, `launcher.set_cwd(str(paths.app_dir().parent))` (the directory containing `calpi/`), `launcher.unsetenv("NOTIFY_SOCKET")`, `proc = launcher.spawnv(argv)`. Then `proc.communicate_utf8_async(None, None, self._on_done, None)`. Arm a timeout with `GLib.timeout_add_seconds(TIMEOUT_S, self._on_timeout)`. Notify `state_callbacks(True)`.
- `_on_timeout`: `proc.force_exit()` and log a WARNING. `_on_done` then still runs with an incomplete stdout and marks the run TIMEOUT.
- `_on_done(proc, res, _)`: `ok, out, _ = proc.communicate_utf8_finish(res)` (in a try). Remove the timeout. Parse the **last** line starting with `RESULT_PREFIX`. If there isn't one, synthesise `{"status":"crashed"}` or TIMEOUT. Set `_running = None` and `_last_end_mono = time.monotonic()`. Handle the result (step 4). Then if there's a pending request, launch it, **else** `_arm(interval)`.
- **Zombies**: `communicate_utf8_async` waits for the process, and `Gio.Subprocess` reaps it. Check this (acceptance criterion 9).

### Step 4 — Handling results
```python
def _handle_result(self, r: dict):
    self.last_result = r
    if r.get("status") == "done":
        self.synced_window = _parse_window(r.get("window"))
        if any(a.get("error") is None for a in r["accounts"]) or not r["accounts"]:
            self.last_success_wall = timeutil.now()
        if r.get("changed"):
            self.app.on_data_changed()
    for cb in list(self.result_callbacks):
        try: cb(r)
        except Exception: log.exception("sync result callback failed")
    log.info("sync: %s in %s ms, changed=%s, errors=%s", r.get("reason"), r.get("duration_ms"), r.get("changed"),
             [a["error"] for a in r.get("accounts", []) if a.get("error")])
```
"Success" for the indicator = at least one account synced without an account-level error. US-18 refines this per calendar. Add `watchdog.status(f"last sync {hh:mm}")` if US-12's watchdog exists.

### Step 5 — The other triggers
- **Day change**: `app.clock.subscribe_day_changed(lambda o, n: self.request_sync("day-changed"))`.
- **Zone change**: `app.clock.subscribe_tz_changed(lambda: self.request_sync("tz-changed", force=True))`. Forced because floating times and window edges depend on the zone.
- **Browsing outside the window**: `month_view.month_changed_callbacks.append(self._on_month_changed)`:
  ```python
  def _on_month_changed(self, y, m):
      first, end = self.app.window.month_view.visible_range()
      if self._inside_synced_window(first, end): return
      self._debounced("browse", 3, extra=(first, end))
  ```
  `_debounced(name, seconds, **req)` keeps one GLib timer per name. Re-arming it replaces the previous one, so the request fires `seconds` after the **last** call.

### Step 6 — The header indicator (D7)
```python
self.sync_label = Gtk.Label(css_classes=["sync-status"])
month_view.header.end_slot.prepend(self.sync_label)
engine.state_callbacks.append(lambda running: self._update_sync_label())
engine.result_callbacks.append(lambda r: self._update_sync_label())
app.clock.subscribe_minute(lambda now: self._update_sync_label())   # keeps "Updated 14:05" correct if the format depends on the day
```
Text: running → "Updating…". Otherwise, with `last_success_wall` → `f"Updated {formatting.short_time(t)}"` (or "Updated yesterday 22:15" if it isn't today). Otherwise → "" (hidden). CSS: `font-size: 20px; color: @text_faint;`. US-17 and US-38 extend it with offline and error states. **Put the label logic in a small `SyncIndicator` widget class** (`calpi/widgets/sync_indicator.py`), so those stories have one place to extend.

### Step 7 — Wiring in the app
In `CalpiApp._on_activate`, after the window and the clock exist:
```python
self.sync = SyncEngine(self)
self.sync.start()
```
`on_data_changed()` lives on the app or the window (US-09). Make sure it exists: if US-09 isn't done, add it here, calling `month_view.reload()`.

### Step 8 — Tests
`tests/test_sync_engine.py`: needs `GLib` but **no display**. Use a fake spawner that records requests and lets the test finish them synchronously (`fake.finish(result_dict)`). Drive time with `GLib.MainContext.iteration` plus short intervals, **or** make the timer functions injectable (`timeout_add=...`) and call the callbacks directly. **Prefer injectable timers**: deterministic and fast.
- The first run is scheduled with a 10 s delay. After the run ends, the next is armed with the interval.
- A request while running → exactly one pending. Three requests while running → still one, merged (force OR, extra union).
- A timeout → `force_exit` called, and the result treated as TIMEOUT.
- A settings change of the interval → rearmed.
- Debounce: 5 month changes outside the window within 1 s → one request, 3 s after the last.
- Safe mode → `start()` arms nothing.
- `changed=false` → `on_data_changed` not called. `changed=true` → called once.
- A bad worker output → handled, and the schedule continues.

`tests/test_worker.py`:
- `run()` with a temporary state directory, one account, a fake transport serving the US-15 fixtures → the result JSON has the expected shape, `changed=True`. Run again → `changed=False` (ctag unchanged).
- Missing credentials → `CREDENTIALS_UNREADABLE` for that account.
- Lock held (take the flock in the test) → `main()` returns 3 and prints `status: busy`.
- Nothing but the result line on stdout (`capsys`).

### Step 9 — Checks on the Pi
1. Deploy. `scripts/pi logs -f` and watch: `sync: startup ...` about 10 s after `calpi ready`, then every 15 minutes. **Temporarily** set the interval to 5 minutes (edit settings through a tiny script as `kiosk`, or use US-27 if it's done) to watch several runs, **and set it back**.
2. The stutter test (acceptance criterion 8): enable `CALPI_PERF=1` and a dev hook `CALPI_TEST_NAV_LOOP=1.5` (changes month every 1.5 s) in a **temporary drop-in**, trigger a forced sync (a dev hook, or `request_sync` from `CALPI_TEST_SYNC_ON_START=force`), and collect the `perf: month_render` numbers for 60 s with and without the sync. **Remove the drop-in afterwards.**
3. The leak test (acceptance criterion 9): with the interval at 5 minutes, or a dev hook for a 20 s cadence, leave it running 2 hours or more. Sample `ps -o rss=`, the fd count, and zombies every 10 minutes (a small loop over `scripts/pi ssh`). Record the table.
4. Change an event on the owner's phone → within one interval it appears on the device, without a restart.

---

## Files

| File | Change |
|---|---|
| `calpi/sync/worker.py` | New |
| `calpi/sync_engine.py` | New |
| `calpi/widgets/sync_indicator.py` | New |
| `calpi/logging_setup.py` | A `stream` parameter (the worker logs to stderr) |
| `calpi/data/settings_store.py` | `K_SYNC_INTERVAL_MINUTES`, `SYNC_INTERVAL_CHOICES` (and `K_TIMEZONE` with default None if US-28 hasn't done it) |
| `calpi/app.py` | Creates and starts `SyncEngine`, `on_data_changed` |
| `calpi/style.css` | `.sync-status` |
| `tests/test_sync_engine.py`, `tests/test_worker.py` | New |

---

## Pitfalls

- **Blocking waits** (`proc.wait()`, `subprocess.run`) on the main thread. Always use the async Gio API.
- **Parsing stdout while logs also go to stdout.** The worker logs to stderr only.
- **Capturing stderr with a pipe you never read**: the worker blocks when the pipe buffer (64 KB) fills. Inherit stderr instead.
- **Arming the interval timer when the run *starts*** instead of when it *ends*. Slow syncs then pile up.
- **Forgetting to remove the timeout source** after a normal finish. It would later kill the *next* run.
- **Leaving test drop-ins** on the Pi.
- **Syncing in safe mode automatically.**

---

## Definition of done

- [ ] All acceptance criteria met. The engine and worker tests pass.
- [ ] The Pi stutter numbers (with and without sync) and the leak table recorded.
- [ ] A phone change was seen appearing on the device on its own.
- [ ] Test drop-ins removed, and the interval back to the default.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `app.sync.request_sync(reason, force=False, extra=None)` | US-17 (network up, retries), US-19 (manual), US-25 (account added), US-27 |
| `app.sync.result_callbacks` (the D3 dict), `state_callbacks(running)` | US-17, US-18, US-19, US-31, US-38 |
| `app.sync.last_result`, `last_success_wall`, `synced_window`, `is_running` | US-17, US-19, US-31 |
| `SyncEngine._arm`/the scheduling hooks: US-17 adds `schedule_retry(seconds)` | US-17 |
| The worker's CLI and the `CALPI_SYNC_RESULT` JSON (v1) | US-18 (the worker writes the status table), US-20 |
| `K_SYNC_INTERVAL_MINUTES`, `SYNC_INTERVAL_CHOICES` | US-27, US-32 |
| `SyncIndicator` widget in the header | US-17, US-19, US-38 |
| `<runtime_dir>/sync.lock` (only one sync at a time system-wide) | the CLI (US-14/15) should take it too: add it to `cli fetch` |
