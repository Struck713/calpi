# Performance (US-36)

STATUS: tooling done and verified in the devcontainer. **Nothing has been measured on the Pi yet** (no Pi was
reachable). Every "Pi" cell below is TBD. Broadway timings are not evidence for the Pi (see "Devcontainer numbers").

## Targets (D1; Pi 3B, 1920x1080, cairo renderer, the owner's real data)

| Metric | Target | Pi result |
|---|---|---|
| Power-on to calendar visible (stopwatch; `boot_to_first_paint`) | <= 35 s | TBD |
| Process start to first paint | <= 3 s | TBD |
| Process start to first paint with events | <= 4 s | TBD |
| Month change (input to painted) | p90 <= 150 ms, max <= 300 ms | TBD |
| Open day detail | p90 <= 150 ms | TBD |
| Back to calendar | p90 <= 100 ms | TBD |
| Open Settings (sections built) | p90 <= 250 ms | TBD |
| First open of a settings section | <= 400 ms | TBD |
| OSK first show / later shows / key press | <= 300 / 50 / 50 ms | TBD |
| Month change during a sync | p90 <= 150 ms | TBD |
| Idle CPU (app + cage) | <= 2 % average over 5 min | TBD |
| UI RSS after startup and after the run | <= 150 MB | TBD |
| Sync process peak RSS | <= 150 MB | TBD |

## Tooling

- `calpi/perf.py`: `span(name)`, `until_paint(name, widget, t0=None)` (500 ms safety timeout counts `no_paint`),
  `record`, `stats`, `report`, `since_boot_ms`, `process_start_since_boot_ms`, `mark_first_paint`, `cpu_ticks`,
  `rss_mb`, `profiled(name)`. Samples are bounded deques (500). Logs at DEBUG, INFO with `CALPI_PERF=1`.
- Built-in marks: `month_render`, `week_render`, `agenda_render`, `day_open`, `osk_show_first`, `osk_show`,
  `osk_key`, `screen_<name>` (every navigator switch: `screen_settings`, `screen_calendar` = back to calendar),
  `start_to_first_paint`, `start_to_events_paint`, `boot_to_first_paint`. All earlier ad-hoc measurements were moved onto perf.py.
- `calpi/devtools/bench.py` (`CALPI_BENCH=1`, dev only): scenarios `startup, month_nav, day_open, settings_open, osk,
  idle` plus optional `week_nav`, `during_sync`. Prints `CALPI_BENCH_RESULT {json}`, writes `<runtime>/bench.json` and
  `bench.done` (which stops a systemd restart from running it twice), then quits. Env: `CALPI_BENCH_SCENARIOS`,
  `CALPI_BENCH_STEP_MS` (400), `CALPI_BENCH_IDLE_S` (300), `CALPI_BENCH_N` (<1 shrinks iteration counts),
  `CALPI_BENCH_STATE` (state dir override for stress data). Each measured step also records `<name>_sync`: the
  main-thread cost of the action without waiting for paint.
- `calpi/devtools/report.py`: prints the table and checks D1 targets (exit 1 on a miss).
- `scripts/pi perf [--stress] [--during-sync] [--week]`: temporary systemd drop-in, run, table, drop-in removed by `trap`.
- `python3 -m calpi.data.sample_data --load --clear --scale N --state-dir DIR`: N times the events (copies shifted 3 days / 20 min).
- `CALPI_PROFILE=reload`: cProfile of `MonthView.reload`, dumped to `/tmp/calpi-reload.pstats`.

## Method on the Pi (to do)

1. `scripts/pi health`: `throttled=0x0`, temperature < 70 C. No sync running (except `--during-sync`).
2. `scripts/pi deploy`, then `scripts/pi perf` (real data), `scripts/pi perf --stress`, `scripts/pi perf --during-sync --week`.
3. Boot: `scripts/pi ssh 'systemd-analyze; systemd-analyze blame | head -20; systemd-analyze critical-chain calpi-kiosk.service'`,
   plus 3 stopwatch power cycles with the owner (plug-in to calendar visible), and `perf: boot_to_first_paint` from the journal.
4. Idle: `pidstat -u -p $(pgrep -d, -f "cage|/opt/calpi/run.py") 10 30` (sysstat is a dev tool only).
5. Profile only what misses (import time: `PYTHONPROFILEIMPORTTIME=1` drop-in; `find /opt/calpi -name '*.pyc' | wc -l`).
6. Stress state lives in `/tmp/calpi-perf`; if the service uses `PrivateTmp`, the seed step must write elsewhere.

## Periodic wakeups (audit from `grep timeout_add`)

Steady-state timers: minute-aligned clock (`clock.py`), watchdog ping (`watchdog.DEFAULT_PING_SECONDS`), inactivity
check (`InactivityMonitor.CHECK_INTERVAL_S`), sync schedule (`sync_engine`, minutes), problem banner tick (60 s),
time-sync poll (`timesync.POLL_S`, only while waiting for NTP), weather refresh (service, hours). Timers that exist only
while a settings section is visible (network scan, status/sync ticks) are stopped on hide. Idle wakeups/s are measured by
the `idle` scenario (`app_wakeups_per_s`); on the Pi check that nothing else appears.

## Devcontainer numbers (x86_64, Python 3.13, GTK 4.18, Broadway, load average 8-13 from parallel work)

Meaningless as absolute values (Broadway paints only when the daemon lets it; many `no_paint` at 500 ms), useful for
main-thread cost and regressions.

| What | Result |
|---|---|
| Main-thread cost of a month change (`month_change_sync`), 280 events (5x sample) | p50 1.3 ms, p90 3.9 ms |
| `MonthView.reload` profile (60 changes, 5x data) | about 2 ms each: `layout_week` 37 %, `WeekRow.render` 19 %, `events_for_days` 19 % |
| Startup to first paint (Broadway) | 0.8 to 1.7 s |
| Idle CPU over 10 s | 1.3 % (app; devcontainer) |
| Input to painted (Broadway, noisy) | month p50 320 ms, p90 550 ms: dominated by Broadway |
| RSS growth in the bench | 55 to 153 MB over 120 month changes. A bare Gtk grid of labels updated the same way grows by a similar amount (60 to 74 MB per 200 updates), so this is Broadway's backend, not a leak in calpi. **Must be re-checked on the Pi**; US-37 owns long-run memory. |

No optimisation was applied: the profile shows no algorithmic hot spot (Python cost of a month change is about 2 ms on
x86, roughly 25 ms scaled to a Pi 3B), so the target risk is cairo painting, which only the Pi can show.

## Optimisations (before / after)

None yet. Add rows here after Pi profiling.

| Change | Before | After |
|---|---|---|

## Needs the Pi / owner

- Every table above (baseline, stress, during-sync, boot, idle, RSS, sync process peak).
- Boot trims (apt-daily timers, man-db, ModemManager, bluetooth, ...) and their `setup-pi.sh` `LEAN=1` switch: only with the owner's OK. Not done.
- Stopwatch power cycles, and a re-run on the final touchscreen (US-34).
- Not measured because it does not exist yet: anything added after this story.
