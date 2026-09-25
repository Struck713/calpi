# US-36 — Performance targets

| | |
|---|---|
| **Epic** | 4. Touch and Polish |
| **Priority** | P1 |
| **Blocked by** | US-07 Events in the grid, US-16 Scheduled background sync |
| **Blocks** | US-37 Long-running stability |
| **Phase** | 4. Touch and Polish |

## Story

> As a user, I want the app to start quickly and change months and screens instantly, with measured targets checked on the Pi.

## Context

"Smooth" is a project goal: the display must never feel frozen or sluggish, even on a Pi 3B with software rendering. Earlier stories measured things along the way (`perf: month_render`, `day_open`, `osk_show`), but each in its own ad-hoc way. This story:
1. **Sets the targets** (a table, D1), measured **on the Pi**, on the final screen if US-34 is done.
2. Builds **one instrumentation module** (`calpi/perf.py`) that everything uses, with percentiles and a report.
3. Builds a **repeatable benchmark driver** that exercises the app in a scripted way on the device, plus a `scripts/pi perf` command that runs it and collects the results.
4. **Measures boot time**, from power-on to the calendar being visible.
5. **Optimises** whatever misses its target, using the playbook in step 6, and records the before and after numbers in `docs/performance.md`.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-07** Events in the grid | The real render path to measure (month render with events), the existing `perf: month_render` log (or its local helper), `MonthView.reload` | `grep -rn "month_render" calpi/` finds the measurement |
| **US-16** Scheduled background sync | The sync process and engine, so the "no stutter during sync" target can be measured, plus a realistic event load from the real account | `scripts/pi logs \| grep "sync:"` shows runs |

### Soft dependencies
- **US-09, US-21, US-22**: day detail, the OSK, and Settings exist → measure them too. What doesn't exist yet isn't measured. List it in the report.
- **US-34**: measure on the **final** screen if possible (the resolution is the same, but the display pipeline may differ). If it's not done yet, measure on the test monitor, and note that.
- **US-03**: `scripts/pi` is extended with `perf`. Precompiled `.pyc` files (US-03) must be in place, and they matter for startup.
- **US-12**: the watchdog (US-12) mustn't fire during the benchmarks.

### External blockers
- **A realistic data set on the Pi**: the owner's real account synced (hundreds of events), **plus** a stress case (the sample data scaled up: a dev option `sample_data --scale 5` generating about 5× the events). Ask before loading stress data into the real state directory. **Use a separate state directory for stress runs** (`--state-dir /tmp/calpi-perf`, through a drop-in environment variable `CALPI_STATE_DIR`... Watch out: `STATE_DIRECTORY` from systemd takes precedence over `CALPI_STATE_DIR`, and only `--state-dir` beats it (US-02 precedence). So the drop-in must change `ExecStart` to add `--state-dir`, or the driver must use a different mechanism: see step 4).
- **A good power supply** (`get_throttled = 0x0`). Throttling ruins every measurement. Check before each run.
- **Owner help** for the power-on timing (a stopwatch from plug-in to calendar visible), in addition to the logged numbers.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Measurements vary a lot between runs | Warm up first (5 iterations discarded), run ≥ 50 iterations, report p50/p90/max, and make sure no sync is running (unless it's the sync test). Check `get_throttled` and the temperature. |
| After-paint timing never fires (nothing redrawn) | If the operation changed nothing on screen, no frame is drawn. Handle it with a timeout (500 ms), and log `no-paint` instead of a number. |
| A target is impossible on this hardware | Measure, profile, try the playbook. If it's still missing, **document it with evidence** and propose a revised target to the owner. Don't silently relax targets. |

---

## Scope

### In scope
- `calpi/perf.py`: `Timer`, `measure_until_paint`, percentile statistics, the report.
- Moving the ad-hoc measurements from earlier stories onto `perf.py` (month render, day open, settings open, OSK show).
- New measurements: app start (process start → first paint, and → first paint *with events*), boot (`CLOCK_BOOTTIME` at first paint), idle CPU, RSS.
- `calpi/devtools/bench.py`: a scripted driver (`CALPI_BENCH=1`) that runs the scenarios (D2), prints a JSON report, and quits.
- `scripts/pi perf [--stress] [--during-sync]`: runs the driver on the Pi and collects the report.
- A boot-time investigation and optimisation (systemd services and timers, with the owner's OK).
- The optimisation playbook applied where targets are missed.
- `docs/performance.md`: the targets, the method, the results table (before and after), and the remaining issues.

### Out of scope
- Long-run memory and stability (US-37: it uses this story's tools).
- A GTK 3 port (only if GTK 4 fundamentally can't meet the targets: raise it with the owner first).

---

## Acceptance criteria

1. **Targets** (D1) are written in `docs/performance.md`, and every one of them is measured on the Pi and reported with p50/p90/max, the data-set size, the OS/GTK versions, and the screen.
2. `calpi/perf.py` provides `perf.span(name)` (a context manager), `perf.until_paint(name, widget, t0=None)`, and `perf.report() -> dict`. The measurements log at DEBUG (INFO with `CALPI_PERF=1`). Every earlier ad-hoc measurement is moved onto it.
3. The benchmark driver runs the D2 scenarios automatically and writes a JSON report to stdout (a single `CALPI_BENCH_RESULT {...}` line) and to `<runtime_dir>/bench.json`. `scripts/pi perf` deploys the needed drop-in, runs the driver, fetches the report, prints a table, and **removes the drop-in** at the end (even on failure, using `trap`).
4. **Every target is met** with the owner's real data set. With the stress data set (5×), the interaction targets are met at p90, or the misses are documented with a profile and a mitigation plan.
5. **During a sync**: month changes p90 ≤ 150 ms (the same target), measured with `--during-sync` (the driver forces a sync and runs month changes at the same time).
6. **Boot**: `systemd-analyze` (kernel + userspace) and the app's `perf: boot_to_first_paint` (from `CLOCK_BOOTTIME`) are recorded. Power-on → calendar visible ≤ **35 s** (and the owner's stopwatch agrees within ±3 s).
7. **Idle**: the app plus cage use ≤ **2 %** CPU on average over 5 minutes, idle, with the screen on (`pidstat`, or `/proc/<pid>/stat` deltas). No periodic wakeups more often than once every 5 s, apart from the minute clock, the watchdog ping, and cursor/inactivity checks (list them).
8. **Memory**: the UI process RSS after startup and after the benchmark run ≤ **150 MB**. The sync process peak ≤ 150 MB (US-15).
9. `docs/performance.md` includes a "before/after" table for every optimisation applied, and the list of optimisations with their effects.

---

## Design decisions (already made)

- **D1. Targets** (Pi 3B, 1920×1080, the cairo renderer, the owner's real data):

  | Metric | Target |
  |---|---|
  | Power-on → calendar visible (stopwatch; `boot_to_first_paint`) | ≤ 35 s |
  | App process start → first paint (calendar frame) | ≤ 3 s |
  | App process start → first paint **with events** | ≤ 4 s |
  | Month change (input → painted) | p90 ≤ 150 ms, max ≤ 300 ms |
  | Open day detail | p90 ≤ 150 ms |
  | Back to calendar | p90 ≤ 100 ms |
  | Open Settings (sections already built) | p90 ≤ 250 ms |
  | First open of a settings section | ≤ 400 ms |
  | OSK first show / later shows / key press | ≤ 300 / 50 / 50 ms |
  | Month change **during a sync** | p90 ≤ 150 ms |
  | Idle CPU (app + cage) | ≤ 2 % average |
  | UI RSS | ≤ 150 MB |

- **D2. Benchmark scenarios** (the driver, run through GLib timeouts so the main loop runs normally between steps. Each step waits for its paint, then 200 ms):
  1. `startup`: read the `boot_to_first_paint`, `start_to_first_paint`, and `start_to_events_paint` marks.
  2. `month_nav`: 60× `go_relative(+1)`, then 60× `go_relative(-1)` (5 warm-up iterations discarded).
  3. `day_open`: 30× open a day with events → back.
  4. `settings_open`: 30× open Settings → back. Also the first-open time of each section once.
  5. `osk`: 10× show and hide the keyboard on a demo entry, and 50 key presses.
  6. `idle`: 300 s with no input, sampling CPU from `/proc/self/stat` and cage's `/proc/<pid>/stat` (find cage's PID with `os.getppid()`: the app's parent is cage).
  7. `during_sync` (optional flag): `request_sync(force=True)`, then `month_nav` while it's running.
- **D3. Time sources**: `time.perf_counter()` for durations; `time.clock_gettime(time.CLOCK_BOOTTIME)` for "since power-on" (the kernel counts from boot, which is close to power-on; the firmware stage before the kernel isn't included. The stopwatch covers it). Process start: read `starttime` from `/proc/self/stat` (in clock ticks since boot, `os.sysconf('SC_CLK_TCK')`), compared with `CLOCK_BOOTTIME`.
- **D4. `until_paint`**: connect **once** to the widget's frame clock `after-paint`. On the first paint after `t0`, record `now - t0` and disconnect. A safety timeout of 500 ms records `no-paint`. The widget must be realised (use the window if the widget isn't).
- **D5. The driver is dev-only** and enabled only by `CALPI_BENCH=1` (plus scenario flags). It must never be triggered in normal operation.

---

## Implementation plan

### Step 1 — `calpi/perf.py`
```python
_samples: dict[str, collections.deque] = defaultdict(lambda: deque(maxlen=500))   # bounded (US-37)
def record(name: str, ms: float) -> None: ...
@contextmanager
def span(name): t = time.perf_counter(); yield; record(name, (time.perf_counter() - t) * 1000)
def until_paint(name, widget, t0=None) -> None: ...   # D4
def stats(name) -> dict: ...   # n, p50, p90, max (compute with sorted(); small n)
def report() -> dict: return {n: stats(n) for n in _samples}
def since_boot_ms() -> float: return time.clock_gettime(time.CLOCK_BOOTTIME) * 1000
def process_start_since_boot_ms() -> float: ...          # /proc/self/stat field 22
```
Refactor the earlier measurement sites to call `perf.until_paint(...)`. Search for them: `grep -rn "perf:" calpi/`.

Startup marks in `CalpiApp`: on the first `after-paint` of the window → `record("start_to_first_paint", now - process_start)` and `record("boot_to_first_paint", since_boot)`. After the first `MonthView.reload` with events has painted → `start_to_events_paint`.

### Step 2 — The driver (`calpi/devtools/bench.py`)
A small state machine of scenario steps, driven by `GLib.timeout_add`, which **waits for each paint** before the next step (use `until_paint` callbacks, or poll `perf._samples` lengths). At the end: `print("CALPI_BENCH_RESULT " + json.dumps({"report": perf.report(), "meta": {...}}))`, write the JSON to `<runtime_dir>/bench.json`, then `app.quit()`. `meta` holds: the build stamp, the GTK version (`Gtk.get_major_version()` and so on), the Python version, the event count in the store, `get_throttled` before and after, and the temperature before and after.

Enabled in `CalpiApp._on_activate` only if `os.environ.get("CALPI_BENCH") == "1"`: `bench.start(app, scenarios=os.environ.get("CALPI_BENCH_SCENARIOS", "startup,month_nav,day_open,settings_open,osk,idle"))`.

### Step 3 — `scripts/pi perf`
```bash
perf) shift; scen="${CALPI_BENCH_SCENARIOS:-startup,month_nav,day_open,settings_open,osk,idle}"
  [[ " $* " == *" --during-sync "* ]] && scen="$scen,during_sync"
  remote "sudo mkdir -p /etc/systemd/system/calpi-kiosk.service.d && printf '[Service]\nEnvironment=CALPI_BENCH=1\nEnvironment=CALPI_BENCH_SCENARIOS=$scen\nEnvironment=CALPI_PERF=1\n' | sudo tee /etc/systemd/system/calpi-kiosk.service.d/bench.conf >/dev/null && sudo systemctl daemon-reload"
  trap 'remote "sudo rm -f /etc/systemd/system/calpi-kiosk.service.d/bench.conf && sudo systemctl daemon-reload && sudo systemctl restart calpi-kiosk"' EXIT
  cursor=...; remote "sudo systemctl restart calpi-kiosk"
  remote "timeout 900 journalctl -u calpi-kiosk --after-cursor='$cursor' -f --no-pager | grep -m1 CALPI_BENCH_RESULT" | sed 's/^.*CALPI_BENCH_RESULT //' > scratch-bench.json
  /usr/bin/python3 - <<'EOF'   # pretty table from scratch-bench.json
  ...
EOF
  ;;
```
When the driver quits, the app exits. systemd restarts it (still with the bench drop-in). **The trap removes the drop-in and restarts cleanly**, but the second benchmark run started by that systemd restart could begin before the trap runs. To avoid it, have the driver write a marker file `<runtime_dir>/bench.done` and **not** start a benchmark if that marker exists. The trap removes the marker too.

**Stress data** (`--stress`): the drop-in also sets `CALPI_BENCH_STATE=/tmp/calpi-perf`. At the very start of `main()`, the driver-enabled app calls `paths.set_state_dir_override(...)` when both `CALPI_BENCH=1` and `CALPI_BENCH_STATE` are set, so the stress state directory is used without touching `/var/lib/calpi`. Seed it before the run: `scripts/pi ssh 'cd /opt/calpi && sudo -u kiosk /usr/bin/python3 -m calpi.data.sample_data --load --clear --scale 5 --state-dir /tmp/calpi-perf'`. Add `--scale N` to US-04's sample generator: it repeats the event patterns with shifted titles and times.

### Step 4 — Measure the baseline
1. `scripts/pi health` → `throttled=0x0`, the temperature below 70 °C.
2. `scripts/pi perf` (real data) → save the table as the **baseline** in `docs/performance.md`.
3. `scripts/pi perf --stress`, and `scripts/pi perf --during-sync`.
4. Boot: `scripts/pi ssh 'systemd-analyze; systemd-analyze blame | head -20; systemd-analyze critical-chain calpi-kiosk.service'`. Then, with the owner, power-cycle with a stopwatch (3 times), and read `perf: boot_to_first_paint` from the logs.

### Step 5 — Idle checks
```bash
scripts/pi ssh 'sudo apt-get install -y sysstat >/dev/null; pidstat -u -p $(pgrep -d, -f "cage|/opt/calpi/run.py") 10 30'
```
(`sysstat` is a dev tool: note it, but don't add it to runtime deps.) Also list the periodic GLib sources: add a dev-only DEBUG dump of the registered timers (the app keeps a registry of its own periodic timers: clock, watchdog, inactivity check, sync schedule; list them in `docs/performance.md`).

### Step 6 — The optimisation playbook (only for missed targets)
Profile first, then pick from this list:
- **Import time** (startup): `python3 -X importtime run.py --exit-after 1 2> imports.txt` (run on the Pi with Broadway? No: run it under the service with a drop-in setting `PYTHONPROFILEIMPORTTIME=1`; it prints to stderr, which goes to the journal). Look for heavy imports in the UI process (`icalendar` must **not** be there: US-15 D1). Make heavy modules lazy (import inside functions), for example `cryptography` (only needed when credentials are used), and the settings sections (already lazy).
- **`.pyc` present?** `find /opt/calpi -name '*.pyc' | wc -l` (US-03).
- **Render work**: `cProfile` around `MonthView.reload` in dev (`CALPI_PROFILE=reload` writes `pstats` to `/tmp`). Common fixes: the widget pool (US-07 D7) if it's not in place, avoiding `set_css_classes` when unchanged, fewer nested boxes per event line, avoiding `Gtk.Label` markup, cutting down the number of CSS rules that match (specific classes rather than descendant selectors like `.week-row .line .summary`).
- **CSS**: complex selectors and `*` rules are re-evaluated on state changes. Keep `* { transition: none; }` (it's needed), but avoid other universal rules.
- **Fonts**: `fc-cache -f` done. A single font family (DejaVu Sans). Check the font lookup time with `FC_DEBUG=1` (a dev drop-in).
- **The renderer**: confirm `GSK_RENDERER=cairo` (the log in `calpi ready`). Don't try GL on the Pi 3B.
- **Boot**: disable unneeded units (with the owner's OK): `apt-daily.timer`, `apt-daily-upgrade.timer` (they refresh package lists on the SD card; the owner decides about updates), `man-db.timer`, `e2scrub_all.timer`, `ModemManager` (if present), `bluetooth` (US-01), `triggerhappy`, `rpi-eeprom-update` (not on a 3B). Check `NetworkManager-wait-online` isn't in the chain (US-01 D3). Put the approved changes in `setup-pi.sh` (`LEAN=1` from US-01).
- **Precompute** anything computed at startup that doesn't need to be (for example the zone index is already lazy, US-28).
- **The GTK version**: if GTK 4.8 (Bookworm) is much slower than 4.18 (Trixie) and the owner is willing, upgrading the OS release is an option. **Raise it; don't do it yourself.**

After each change, run `scripts/pi perf` again and add a row to the before/after table.

### Step 7 — `docs/performance.md`
Sections: the targets (D1), the method (tools, scenarios, data sets, device state), the baseline results, the optimisations (each with before and after), the final results, the known limitations, and how to run it again (`scripts/pi perf`).

---

## Files

| File | Change |
|---|---|
| `calpi/perf.py` | New |
| `calpi/devtools/__init__.py`, `bench.py` | New (dev only) |
| `calpi/app.py` | Startup marks, driver hook, bench state override |
| Earlier measurement sites (`month_view.py`, `day_detail.py`, `keyboard.py`, `settings/shell.py`) | Moved onto `perf.py` |
| `calpi/data/sample_data.py` | `--scale N` |
| `scripts/pi` | `perf` subcommand |
| `.claude/skills/pi-kiosk-setup/setup-pi.sh` | Approved boot trims (`LEAN=1`) |
| `docs/performance.md` | New |
| `tests/test_perf.py` | New (percentiles, bounded deques, span) |

---

## Pitfalls

- **Measuring in Broadway or the devcontainer.** It means nothing. The Pi only.
- **Measuring while throttled or hot.**
- **Unbounded sample lists.** They leak over weeks (US-37). Use a `deque(maxlen=...)`.
- **Leaving the bench drop-in** in place (the `trap` + marker handle it; check with `systemctl cat` afterwards).
- **Stress data in the real state directory.** Use the separate directory.
- **"Optimising" without a profile.**
- **Relaxing targets silently.**

---

## Definition of done

- [ ] Every D1 metric measured on the Pi, with the results in `docs/performance.md`.
- [ ] Every target met, or the misses documented with evidence and agreed with the owner.
- [ ] `scripts/pi perf` works and cleans up after itself.
- [ ] Boot trims applied only with the owner's approval, and reproducible through `setup-pi.sh`.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `perf.span`, `perf.until_paint`, `perf.report` | every later feature (measure new screens the same way), US-37 |
| `scripts/pi perf` and the bench driver scenarios | US-37 (soak mode), US-39/40 (add scenarios) |
| `docs/performance.md` targets | regression checks for later stories |
| `sample_data --scale N` | US-37 |
