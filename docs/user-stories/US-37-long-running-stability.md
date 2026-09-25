# US-37 — Long-running stability

| | |
|---|---|
| **Epic** | 4. Touch and Polish |
| **Priority** | P1 |
| **Blocked by** | US-16 Scheduled background sync, US-36 Performance targets |
| **Blocks** | — |
| **Phase** | 4. Touch and Polish |

## Story

> As the owner, I want the device to run for weeks without slowing down, using more memory, or needing a restart.

## Context

A wall calendar is switched on once and then left alone for months. Problems that never show up in a 10-minute test show up after days: a memory leak of 1 MB per hour is 700 MB after a month, which is more than the Pi 3B's whole budget; file descriptors leak with every subprocess; a timer gets registered twice after every midnight; the SQLite WAL file grows without limit because a read transaction never ends; the journal fills up; a slow drift makes month changes 3× slower after two weeks.

This story **proves** that the device is stable over weeks, and fixes whatever the proof turns up:
1. **Self-monitoring**: the app logs its own health (RSS, fds, threads, GLib sources, sync process count, database and WAL size) every hour, so trends are visible in the journal.
2. **A soak mode**: a dev driver that speeds up the activity (frequent syncs, month navigation, opening days and Settings, dim cycles), so days of normal use fit into hours.
3. **Collection and analysis**: `scripts/pi soak-sample` collects samples into a CSV on the dev machine, and a small analysis script computes the trends (slopes) with pass/fail thresholds.
4. **A 14-day run** on the real device: the first days in soak mode, then normal operation.
5. **A last-resort safety valve**, which must never fire during the soak test.

It builds on US-36's `perf` tools (the latency has to stay flat over time) and on US-16's sync process design (memory used by syncing is freed when the process exits).

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-16** Scheduled background sync | The recurring background activity that most often leaks (subprocesses, pipes, callbacks), `engine.result_callbacks`, and the interval setting to speed up the soak | `grep -n "communicate_utf8_async" calpi/sync_engine.py`. Syncs run on the Pi. |
| **US-36** Performance targets | `calpi/perf.py` (bounded sample buffers, `report()`), the bench driver framework (`calpi/devtools/bench.py`), `scripts/pi perf`, the baseline numbers in `docs/performance.md` | `scripts/pi perf` gives a report. `docs/performance.md` exists. |

### Soft dependencies
- **Every feature that exists** at soak time should be exercised: US-09 (day detail), US-22+ (Settings), US-21 (OSK), US-30 (dimming), US-17 (offline and retry: include a network outage in the soak if you can), US-10 (midnight: happens every day anyway), US-41 (weather, if it exists).
- **US-12**: the watchdog must not fire. The crash counter must stay empty. The journal cap (32 MB) is part of the check.
- **US-31** `device_info.collect()` for the temperature and throttling.

### External blockers

| Blocker | What to do |
|---|---|
| **The device has to be left alone for 14 days** (the owner agrees, a stable power supply, the network available most of the time) | Plan it with the owner. Deploys during the soak **reset** it. Agree on a code freeze for the soak period (small doc changes are fine, but no app deploys). |
| **The dev machine can reach the Pi periodically** to collect samples | If the devcontainer isn't running all the time, the app's own hourly health log (D1) in the journal is the source of truth. Collect it at the end with `journalctl` (the journal is capped at 32 MB, which at a modest log rate should hold 14 days: **check the log volume per day early**, and reduce INFO noise if needed). |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| RSS grows slowly and it's not clear where | Use the leak tools (step 5): `tracemalloc` snapshots diffed on demand (SIGUSR2, dev flag), object counts by type, GLib source counts. Python-level growth shows in tracemalloc. Native GTK growth doesn't: compare `gc` object counts of GTK types (`Gtk.Label` and so on) instead. |
| The journal fills up before 14 days | Too much INFO logging. Find the chattiest logger (`journalctl -u calpi-kiosk -o cat \| awk '{print $2}' \| sort \| uniq -c \| sort -rn \| head`), and move per-run lines to DEBUG or merge them. The target is < 1 MB/day of journal from the app in normal operation. |
| The soak run is interrupted by a power cut | Good test data for US-12, but restart the soak clock. Note it. |

---

## Scope

### In scope
- `calpi/health.py`: periodic self-monitoring (hourly INFO line + on demand), plus the safety valve.
- The leak-hunting tools (dev only): `tracemalloc` snapshot/diff on SIGUSR2, object-type census, GLib source count.
- `calpi/devtools/soak.py`: the soak driver (speeded-up activity).
- `scripts/pi soak start|stop|sample|collect`, and `scripts/soak-analyze.py` (on the dev machine: CSV → slopes → pass/fail).
- A SQLite WAL check (bounded growth) and a periodic checkpoint in the sync worker.
- The 14-day run, with the results in `docs/stability.md`.
- Fixing every leak or growth found.

### Out of scope
- Performance optimisations not related to growth (US-36).
- Scheduled "just in case" restarts. The goal is **not** needing them (the safety valve is only a last resort).

---

## Acceptance criteria

1. Every hour (and on `SIGUSR2` in dev), the app logs **one** INFO line: `health: rss=87.3MB fds=23 threads=3 sources=9 sync_procs=0 db=1.2MB wal=0.1MB journal=18MB uptime=3d04h`.
2. **Soak mode** (`CALPI_SOAK=1`, dev only, through `scripts/pi soak start`) runs these, for as long as it's enabled: a sync every **5 min** (forced every 4th time), month navigation every **30 s** (random ±3 months, then back to today), opening a day and going back every **2 min**, opening Settings and visiting each section every **10 min**, the OSK shown and hidden every **10 min**, a dim preview cycle every **hour** (if US-30), and a US-36 benchmark mini-run (`month_nav` 20×) every **6 h**, whose results go to the health log.
3. **The 14-day run** (at least 5 days in soak mode, then normal mode) passes these thresholds, computed by `scripts/soak-analyze.py` on the hourly samples after a 12-hour warm-up:
   - UI **RSS slope ≤ 0.5 MB/day**, and the maximum ≤ 150 MB,
   - **fds**, **threads**, and **GLib sources** flat (the maximum − the minimum ≤ 2 after the warm-up),
   - **no zombie** processes. `sync_procs` is 0 at every sample taken outside a sync,
   - **the database size** flat (±20 %) and **WAL ≤ 8 MB** always,
   - **journal usage** ≤ the 32 MB cap, with the app's log volume ≤ 1 MB/day in normal mode,
   - **month-render p90 in the 6-hourly mini-runs** within +20 % of the day-1 value,
   - **no** watchdog restarts, crashes, or safe-mode entries (`journalctl` shows no `Watchdog timeout`, `uncaught exception`, or `SAFE MODE`). The service's `NRestarts` is 0 (`systemctl show -p NRestarts calpi-kiosk`),
   - the calendar still shows the right "today" every morning (the midnight rollover worked **every** day: count the `clock: day changed` lines, one per day),
   - syncs keep succeeding (US-18 status: no stuck failures except real outages).
4. **The safety valve**: if the UI RSS goes over **350 MB**, or the fds over **500**, the app logs ERROR `health: resource limit exceeded (...), restarting` and exits with code 75 (systemd restarts it). It only acts between 02:00 and 05:00 local time **unless** the RSS goes over 450 MB (then it acts straight away). **It must not fire during the 14-day run.**
5. **Leak tools** (dev only): `CALPI_LEAKCHECK=1` enables `tracemalloc` (25 frames) at startup. `SIGUSR2` writes the top 30 allocation diffs since the previous snapshot, and the top 30 Python object types by count, to the journal.
6. **The WAL is bounded**: the UI process never holds a read transaction open (every query fetches everything right away). The sync worker runs `PRAGMA wal_checkpoint(TRUNCATE)` at the end of a run if the WAL is over 4 MB.
7. `docs/stability.md` has: the method, the timeline (soak and normal phases, outages), the charts or tables of the metrics (a CSV summary: min/max/slope per metric), the leaks found and fixed (with before and after), and the final pass/fail table.
8. Every soak or leak hook is off by default, and gated by environment variables. `scripts/pi soak stop` removes the drop-ins, and it's checked with `systemctl cat`.

---

## Design decisions (already made)

- **D1. Health sampling** (`calpi/health.py`, the collection functions are pure and read `/proc`):
  - RSS: `/proc/self/statm` field 2 × page size.
  - fds: `len(os.listdir('/proc/self/fd'))`.
  - threads: `threading.active_count()` **and** `/proc/self/status` `Threads:` (native threads count too).
  - GLib sources: the app keeps a **registry of its own periodic sources** (`calpi.tasks.register_periodic(name, source_id)` / `unregister`). GLib doesn't list sources publicly. Log the registry size **and** the names in DEBUG. This also catches duplicate timers (for example a second minute clock).
  - sync procs: children of the UI process (`/proc/<pid>/task/*/children`, or scan `/proc/*/stat` for ppid == our pid).
  - db/wal size: `os.stat` on `calpi.sqlite3` and `-wal`.
  - journal: `journalctl --disk-usage` in a worker thread, at most hourly (it's a subprocess).
  - uptime: `time.monotonic()` since start.
- **D2. The hourly timer** comes from `GLib.timeout_add_seconds(3600, ...)` plus one sample 60 s after startup. It's registered in the periodic registry.
- **D3. The soak driver** reuses US-36's bench-driver machinery (GLib-timeout-driven steps) but runs **forever** until stopped. Its random choices use a seeded `random.Random` (seed logged) for reproducibility.
- **D4. `scripts/pi soak`**:
  - `start`: a drop-in with `CALPI_SOAK=1`, `CALPI_LEAKCHECK=1`, and the sync interval override `CALPI_SYNC_INTERVAL_OVERRIDE=5` (a dev-only env that the engine honours if set, **without** writing settings) → restart.
  - `sample`: fetch the latest `health:` lines since the last sample → append them to `scratch-soak.csv`.
  - `collect`: `journalctl -u calpi-kiosk -o short-iso --no-pager | grep "health:"` over the whole period → CSV.
  - `stop`: remove the drop-ins → restart → check with `systemctl cat`.
- **D5. The analysis** (`scripts/soak-analyze.py`, runs locally with the stdlib only): parse the CSV, drop the warm-up, least-squares slope per metric (per day), min, max, and pass/fail against the thresholds in acceptance criterion 3. It prints a table and writes the summary for `docs/stability.md`.

---

## Implementation plan

### Step 1 — The periodic-source registry (`calpi/tasks.py`)
```python
_periodic: dict[str, int] = {}
def register_periodic(name: str, source_id: int) -> None:
    if name in _periodic: log.warning("periodic source %s registered twice", name)   # catches duplicates
    _periodic[name] = source_id
def unregister_periodic(name: str) -> None: _periodic.pop(name, None)
def periodic_sources() -> dict[str, int]: return dict(_periodic)
```
Go through every `timeout_add`/`timeout_add_seconds` that **repeats** (clock, watchdog, inactivity check, sync schedule, settings refreshes, status refresh, scan loops, dim) and register or unregister it. One-shot timers don't need registering, but make sure they aren't created in a loop that never ends (for example the minute clock re-arms itself: register it once under `"clock"` and update the id).

### Step 2 — `calpi/health.py`
```python
@dataclass
class HealthSample: rss_mb: float; fds: int; threads_py: int; threads_os: int; sources: int
                    sync_procs: int; db_mb: float; wal_mb: float; journal_mb: float | None; uptime_s: float
def sample(journal_mb=None) -> HealthSample: ...
def format_line(s: HealthSample) -> str: ...
def check_limits(s, now_local) -> str | None: ...     # safety valve decision (acceptance criterion 4), pure
class HealthMonitor:        # GLib part: hourly timer, journal usage in a worker, SIGUSR2 in dev, valve action
```
The valve action: log ERROR, `watchdog.stopping()`, `app.quit()`, then `sys.exit(75)` after the loop ends. Make sure the exit code gets through to systemd (cage exits with its child's code? **Check**: if cage hides the exit code, it doesn't matter, because `Restart=always` restarts it anyway).

### Step 3 — Leak tools (dev)
In `health.py`, when `CALPI_LEAKCHECK=1`: `tracemalloc.start(25)` as early as possible (at the top of `main()`), keep the previous snapshot, and on `SIGUSR2` (through `GLib.unix_signal_add`) take a snapshot, `compare_to(prev, "lineno")[:30]`, log it, and replace `prev`. The object census: `collections.Counter(type(o).__name__ for o in gc.get_objects()).most_common(30)`. Log both.

### Step 4 — The soak driver (`calpi/devtools/soak.py`) + the engine override
- The engine: if `os.environ.get("CALPI_SYNC_INTERVAL_OVERRIDE")` → use that interval (minutes) instead of the setting, and log a WARNING at startup that the override is active.
- The driver: a list of `(every_seconds, action)` entries run by one registered 5 s tick that checks which ones are due (**one** timer, not ten). The actions call real app methods (`month_view.go_relative`, `navigator.show("day", date=...)`, `navigator.show("settings", section=...)`, `window.keyboard` show/hide on a demo entry, `app.dimming` preview, `bench.mini_run`).

### Step 5 — The WAL and read transactions
- Check that every UI-side query uses `.fetchall()` (or iterates fully) and doesn't keep a cursor open. `grep -rn "execute(" calpi/ | grep -v fetch` → review each one.
- The worker: at the end of `run()`, `if wal_size > 4 MB: conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")` (in try/except; `BUSY` is fine).
- A test: open the UI connection, run `events_for_days` 1,000 times while another connection writes 1,000 transactions → the WAL stays small (checkpoints succeed, because there's no reader holding a snapshot).

### Step 6 — Scripts
- `scripts/pi soak start|stop|sample|collect` (D4).
- `scripts/soak-analyze.py scratch-soak.csv` (D5): the least-squares slope `sum((t - t̄)(y - ȳ)) / sum((t - t̄)²)`, converted to per day.

### Step 7 — Short rehearsal (before the 14-day run)
Run soak mode for **6 hours**. Collect. Analyse. Fix anything obvious (a growing source count, a growing fd count, a WAL over 8 MB, a chatty log). Repeat until a 6-hour rehearsal is clean. **Only then** start the 14-day run.

Typical leak causes to check deliberately during the rehearsal:
- Subscriptions (`CallbackList.add`, `settings.subscribe`) created by widgets that are rebuilt (day-detail rows, settings rows) and never removed.
- `Gio.Subprocess` objects or `run_in_thread` closures kept in lists.
- `perf` sample buffers (bounded: US-36), and `Navigator` history (bounded: US-02).
- CSS providers created again on every calendar-colour update instead of reused (US-07 D5 says reuse).
- Textures (weather icons, the QR code) loaded again instead of cached.
- Log handlers or filters added more than once (the redactor installed repeatedly: US-13).

### Step 8 — The 14-day run
1. The owner agrees to the code freeze. `scripts/pi deploy` (the final build). `scripts/pi soak start`.
2. Days 1–5: soak mode. Sample daily (`scripts/pi soak sample`) and look at the trends.
3. Day 5: `scripts/pi soak stop` (normal mode, with `CALPI_LEAKCHECK` off). Days 6–14: normal operation. The owner uses it normally.
4. Day 14: `scripts/pi soak collect` → analyse → write `docs/stability.md`.
5. If there's a failure: fix it, rehearse again (6 h), then **restart the 14-day run** (or agree a shorter confirmation run with the owner, stating the risk clearly).

---

## Files

| File | Change |
|---|---|
| `calpi/tasks.py` | Periodic-source registry |
| `calpi/health.py` | New |
| `calpi/devtools/soak.py` | New (dev) |
| `calpi/sync_engine.py` | `CALPI_SYNC_INTERVAL_OVERRIDE` |
| `calpi/sync/worker.py` | WAL checkpoint |
| every module with repeating timers | Registers them |
| `scripts/pi` | `soak` subcommand |
| `scripts/soak-analyze.py` | New |
| `docs/stability.md` | New |
| `tests/test_health.py` (the valve logic, parsing), `tests/test_wal_growth.py`, `tests/test_soak_analyze.py` | New |

---

## Pitfalls

- **Deploying during the soak** (it resets the clock and the evidence).
- **Treating the safety valve as the fix.** It's a last resort, and it must never fire in the test.
- **Unregistered repeating timers**: duplicates go unnoticed.
- **Long-lived read transactions** (the WAL grows).
- **Chatty INFO logs** (the journal cap is reached, and the evidence is lost).
- **Leaving the soak drop-ins** in place.

---

## Definition of done

- [ ] All acceptance criteria met. The 14-day run passed every threshold.
- [ ] `docs/stability.md` written, with the analysis output.
- [ ] Drop-ins removed. The device is in normal mode.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `tasks.register_periodic/unregister_periodic` (**every** repeating timer registers) | US-38 onwards, US-39, US-40, US-41 |
| The `health:` log line format | US-31 (optional: show RSS and uptime in Device details), future diagnostics |
| `scripts/pi soak …`, `scripts/soak-analyze.py` | regression soak before releases |
| The rule: no open read transactions in the UI | anyone touching SQLite |
