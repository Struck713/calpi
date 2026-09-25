# Long-running stability (US-37)

Status: **tooling built and rehearsed on the dev machine; the 14-day Pi soak has not been run yet** (no Pi was
reachable). The sections marked TODO are filled in from the real run.

## Method

1. **Self-monitoring** (`calpi/health.py`). Sixty seconds after start and then every hour the app logs one line:

   `health: rss=87.3MB fds=23 threads=3 sources=9 sync_procs=0 db=1.2MB wal=0.1MB journal=18MB uptime=3d04h`

   `rss` from `/proc/self/statm`, `fds` from `/proc/self/fd`, `threads` from `/proc/self/status`, `sources` the size of
   the periodic-timer registry (`calpi.tasks.register_periodic`; names at DEBUG), `sync_procs` children of the UI
   process (zombies included), `db`/`wal` file sizes, `journal` from `journalctl --disk-usage` in a worker thread.
2. **Safety valve** (last resort, must never fire in the soak): RSS > 350 MB or fds > 500 restarts the app between
   02:00 and 05:00; RSS > 450 MB restarts it at once. It logs `health: resource limit exceeded (...), restarting`
   and exits with code 75 (`Restart=always` brings it back; if cage hides the exit code that does not matter).
3. **Soak mode** (`CALPI_SOAK=1`, dev only): `calpi/devtools/soak.py` speeds up use: sync every 5 min (forced every
   4th), month navigation every 30 s, a day every 2 min, a Settings tour every 10 min, the OSK every 10 min, a dim
   preview hourly, and a 20-step month-navigation mini-benchmark every 6 h (`health: minirun ...`). One 5 s tick,
   seeded random choices (seed logged).
4. **Leak tools** (`CALPI_LEAKCHECK=1`, dev only): tracemalloc with 25 frames; `kill -USR2 <pid>` logs the top 30
   allocation diffs since the previous signal and the top 30 Python object types.
5. **Collection**: `scripts/pi soak start | sample | collect | stop`, then `scripts/soak-analyze.py` (least-squares
   slopes per day, min/max, pass/fail against the acceptance thresholds after a 12 h warm-up).

Run order: deploy the final build, `scripts/pi soak start` (code freeze from here: a deploy resets the soak), sample
daily, `scripts/pi soak stop` after day 5, `scripts/pi soak collect` on day 14, paste the markdown summary below.

## Leak hunt on the dev machine (done)

`tests/test_leaks_gtk.py` runs the real app under the soak driver on virtual time (`CALPI_SOAK_SELFTEST`), takes a
census after a warm-up and again after several hundred more cycles of the same activity, and requires flat widget
counts per screen, callback lists, settings observers, timer names, fds, threads and GTK object types.

Result of the code audit and the runs:

| Checked | Finding |
|---|---|
| Widgets of day detail / Settings / OSK after 100s of open-close cycles | flat (rows freed on hide, sections built once) |
| Subscriptions (`CallbackList`, `settings.subscribe`, clock subscribers) | balanced: on_show adds, on_hide removes |
| Repeating timers | were unregistered (no way to see a duplicate); all now registered: clock, watchdog, inactivity, problems, sync schedule, and the timers of the Status, Sync and Network/Wi-Fi screens while visible. The weather service (US-41) re-arms one-shots and should register as `weather` when it moves to the registry. |
| Sync processes, pipes | 150 real worker spawns per run: fds and threads flat, no zombies |
| SQLite WAL | UI reads always fetch fully (no open read transaction); `tests/test_wal_growth.py` holds it under 6 MB with 1000 concurrent writes; the sync worker now runs `wal_checkpoint(TRUNCATE)` at the end of a run when the WAL is over 4 MB |
| Bounded structures | `perf` sample deques (500), `Navigator` history (10), no other unbounded module-level containers found |
| CSS providers, log filters | one provider per purpose, the redactor is installed idempotently |
| **RSS under Broadway** | grows about 0.3 MB per redraw **for any GTK app** (a 20-line PyGObject script shows the same): Broadway buffers frames when no browser is attached. Python object counts stay flat. So RSS can only be judged on the Pi (cage/Wayland), which is why the soak run matters. |

No application-level leak was found by the audit or the runs.

## Needs the multi-day Pi soak (TODO)

- RSS slope <= 0.5 MB/day and maximum <= 150 MB on the real renderer (Wayland, cairo), including US-34 touch input.
- fds, threads and periodic sources flat (max - min <= 2), `sync_procs` 0 outside syncs, no zombies.
- Database size flat, WAL <= 8 MB, journal <= 32 MB and the app's log volume <= 1 MB/day in normal mode
  (check `journalctl -u calpi-kiosk -o cat | awk '{print $2}' | sort | uniq -c | sort -rn | head`).
- Month-render p90 in the 6-hourly mini-runs within +20 % of day 1.
- No `Watchdog timeout`, `uncaught exception`, `SAFE MODE`; `NRestarts=0`; one `clock: day changed` per day.
- Safe-valve never fires. Whether cage passes the exit code 75 through (irrelevant for correctness).
- Real outage handling (US-17): unplug the network for a few hours during the soak.
- The 6 h rehearsal first, then the 14 days (5 in soak mode, 9 normal). `docs/stability.md` gets the timeline,
  the per-metric min/max/slope table and the final pass/fail table.

## Timeline and results (TODO after the run)

| Phase | Dates | Notes |
|---|---|---|
| Rehearsal (6 h, soak mode) | | |
| Soak mode | | |
| Normal mode | | |

Analysis output (`scripts/pi soak collect` writes `scratch-soak-summary.md`):

TODO
