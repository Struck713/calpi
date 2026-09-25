# calpi — expanded user stories

This directory expands every user story in [`../stories.md`](../stories.md) into its own implementation guide. Each file is meant to be handed to the agent (or person) who implements that story. It explains **what** to build, **why**, **in what order**, **which files to touch**, **how to test it**, and above all **what blocks it**.

**Read this README before any story file.** It holds the architecture and the shared contracts that every story relies on. The story files point back here instead of repeating it. If a story file and this README disagree, the story file is probably out of date: fix whichever one is wrong, and keep the two in sync.

---

## How to use a story file

Every story file has the same sections, in this order:

| Section | What it tells you |
|---|---|
| Header table | Epic, priority, what blocks it, what it blocks, and the project phase |
| Story | The user story, word for word from `stories.md` |
| Context | Why the story exists and where it sits in the product |
| **Blockers** | Hard blockers (the stories in "Blocked by"), **how to check each one is really done**, soft dependencies, external blockers (hardware, accounts, packages, network), and the problems most likely to stop you partway through, with what to do about each |
| Scope | What is in the story and what is explicitly out, so you don't gold-plate |
| Acceptance criteria | Testable statements. The story is done when all of them are true |
| Design decisions | Choices that are already made. Follow them. If one turns out to be wrong, say so and explain why; don't quietly do something else |
| Implementation plan | Numbered steps in the order to do them, with code sketches |
| Files | Files to create or change |
| Testing | Unit tests, devcontainer (Broadway) checks, and checks on the Pi |
| Pitfalls | Mistakes that are easy to make here |
| Definition of done | The final checklist |
| Contracts for later stories | APIs, file formats, and behaviours that later stories depend on. **Don't break these without updating the stories that use them** |

### Rules for working on any story

1. **Check the blockers first.** Each blocker has a "how to confirm it's done" check. Run the checks. If a hard blocker isn't done, stop and report it. Don't build a private stand-in for another story's module unless the story file says that's allowed.
2. **Stay in scope.** Put ideas for more features in the "Follow-ups" section at the end of your PR or hand-off notes, not in the code.
3. **Follow the project skills.** `gtk-kiosk-app` (UI rules), `pi-kiosk-setup` (OS provisioning), and `pi-deploy` (deploying, logs, screenshots) live in `.claude/skills/`. They record things that were checked on real hardware. Load the relevant skill before starting.
4. **Check on the Pi** for anything visual, anything about performance, or anything that touches the OS. Broadway in the devcontainer is only good for checking layout and logic.
5. **Keep contracts stable.** If you have to change a contract from the "Contracts for later stories" section, update the story files that depend on it in the same change.

---

## Platform facts every story depends on

| Fact | Consequence |
|---|---|
| Raspberry Pi 3B: 1 GB RAM, 4× Cortex-A53, VideoCore IV GPU (**GLES 2.0 only**) | GTK must use the software renderer (`GSK_RENDERER=cairo`). No continuous animation. Keep the UI mostly static and redraw only what changed. |
| Pi 3B has **no real-time clock** | At boot the clock is restored from the last saved time and jumps forward when NTP syncs. Code must never assume time only moves forward in small steps. Work out "now" on every tick. |
| Pi 3B Wi-Fi is **2.4 GHz only** | 5 GHz-only networks never appear in a scan. Tell the user this in the Wi-Fi UI (US-23). |
| Raspberry Pi OS Lite, 64-bit, no desktop | Wayland compositor is `cage`. No X11, no display manager, and by default no icon theme or on-screen keyboard. |
| OS release | By late 2026 new Pi OS images are based on Debian **Trixie** (Python 3.13, GTK 4.18, systemd 257). Older **Bookworm** images have Python 3.11, GTK 4.8 and systemd 252. **US-01 records the real versions on the device** in [`../platform-versions.md`](../platform-versions.md). Code must work on the versions recorded there. If that file doesn't exist yet, write for Python 3.11 and GTK 4.8. |
| Screen: 1920×1080 HDMI | The layout is designed for exactly this size (see the `gtk-kiosk-app` skill). The touchscreen that comes later (US-34) might not be 1080p. That risk is flagged in US-34. |
| Input: non-touch monitor + mouse/keyboard now, touchscreen later | Every control must work with a click, a tap, **and** the keyboard (US-11). |
| SD card storage | Keep writes to a minimum, make them atomic, and make sure they survive power loss (US-12). |

---

## Architecture

### Runtime picture

```
systemd: calpi-kiosk.service (user: kiosk, tty1, StateDirectory=calpi)
└─ cage (Wayland kiosk compositor)
   └─ /usr/bin/python3 /opt/calpi/run.py             ← the UI process (GTK 4)
      ├─ GLib main loop: all widgets, timers, D-Bus signals
      ├─ short-lived worker threads: quick blocking I/O (validating an account, nmcli calls)
      └─ spawns: /usr/bin/python3 -m calpi.sync.worker  ← the SYNC PROCESS (one per sync run)
                  network + iCalendar parsing + SQLite writes, then exits
```

**Why sync runs in a separate process** (decided in US-16):
- Parsing iCalendar data and expanding recurring events is CPU-bound Python. In a thread it would hold the GIL and make the UI stutter on the Pi 3B. A separate process runs on another core with no GIL contention.
- Memory the sync uses (XML trees, icalendar objects) is returned to the OS when the process exits. That makes US-37 (weeks of uptime without memory growth) much easier.
- A crash or hang while parsing can't take the display down. The UI kills the process after a timeout.
- The UI process never imports `icalendar` or `recurring_ical_events`. That keeps startup fast (US-36).

### Repository layout (target)

```
run.py                        US-02  entry point; sets GSK_RENDERER before importing Gtk
pyproject.toml                US-02  tool config only (pytest, ruff); not used to build a package
deps/
  apt-runtime.txt             US-02  apt packages needed on the Pi (later stories append to it)
  apt-dev.txt                 US-02  extra apt packages for the devcontainer and tests
scripts/
  dev-run.sh                  US-02  starts broadwayd and runs the app in the devcontainer
  smoke.sh                    US-02  headless smoke test (starts, checks, quits)
  pi                          US-03  helper: deploy | logs | status | screenshot | ssh | deps
calpi/
  __init__.py                 US-02  __version__
  app.py                      US-02  CalpiApp (Gtk.Application), MainWindow, Navigator
  paths.py                    US-02  state dir resolution (no gi)
  logging_setup.py            US-02  logging to stdout → journal
  tasks.py                    US-02  run_in_thread(), safe_callback(), main-thread helpers
  style.css                   US-02  the single app stylesheet
  input.py                    US-11  cursor auto-hide, key-binding helper, touch sizing rules
  inactivity.py               US-08  InactivityMonitor
  clock.py                    US-10  ClockService: minute ticks, day-changed and tz-changed signals
  watchdog.py                 US-12  sd_notify READY/WATCHDOG heartbeat
  crashguard.py               US-12  crash-loop detection → safe mode
  perf.py                     US-36  timing marks and after-paint measurement
  dimming.py                  US-30  overnight schedule controller
  assets/                     various  PNG icons, QR codes (pre-rendered at display size)
  health.py                   US-37  hourly self-monitoring line + safety valve
  devtools/                   US-36/37  bench.py (benchmark driver), soak.py (soak driver) — dev only
  data/                       NO gi IMPORTS IN THIS PACKAGE — unit-tested with plain pytest
    models.py                 US-04  Event, Calendar dataclasses (US-14 adds Account, RemoteCalendar)
    db.py                     US-04  SQLite connection factory, pragmas, migrations (US-12 adds recover_if_corrupt)
    event_store.py            US-04  EventStore (US-15 adds apply_calendar_sync etc.)
    sample_data.py            US-04  sample calendars/events + CLI loader (US-36 adds --scale)
    atomic.py                 US-05  atomic_write_bytes()/atomic_write_json()
    settings_store.py         US-05  SettingsStore (JSON, typed keys, defaults, migrations)
    credentials.py            US-13  CredentialStore (AES-GCM encrypted), Secret, log redaction
    accounts.py               US-14  account records in settings (US-25 adds remove/reconcile)
    timeutil.py               US-06  now()/today()/display_tz(); CALPI_FAKE_NOW support
    daychange.py              US-10  DayChangeDetector (pure)
    monthmath.py              US-06  month_grid_dates(), add_months(), names
    formatting.py             US-07  time labels, contrast; US-09/US-27 add detail/relative texts
    layout.py                 US-07  lane assignment for all-day/multi-day bars, capacity/overflow
    keyboard_layouts.py       US-21  OSK layout data (ASCII coverage tested)
    sync_text.py              US-17  header sync-indicator state/text (US-19/38 extend)
    sync_status.py            US-18  sync status tables: write (worker) + snapshot (UI)
    palette.py                US-26  calendar colour palette + contrast checks
    status_summary.py         US-31  overall verdict for the Status screen
    messages.py               US-31 (minimal) → US-38 (full catalogue): code → plain text + fix
    problem_rules.py          US-38  when/where problems are shown (grace, priority, dismissal)
    setup_state.py            US-32  wizard start decision, step order
    guides.py                 US-33  guide texts (iCloud app-specific password)
    gestures.py               US-35  swipe classifier
    week_layout.py            US-39  week timeline layout (overlap columns)
    agenda.py                 US-40  agenda item builder
  sync/                       NO gi IMPORTS — runs inside the sync process
    errors.py                 US-14  SyncError and ErrorCode enum
    http.py                   US-14  small urllib wrapper: timeouts, auth, manual redirects
    caldav.py                 US-14  PROPFIND/REPORT + multistatus parsing
    icloud.py                 US-14  iCloud discovery (principal → home → calendars)
    ical_parse.py             US-15  iCalendar → Event occurrences (recurrence, tz, all-day)
    fetch.py                  US-15  sync_account(): list calendars → ctag → REPORT → parse → store
    retry.py                  US-17  backoff policy, result classification
    worker.py                 US-16  `python3 -m calpi.sync.worker` entry point
    providers.py (+ provider_*.py, caldav_sync.py)  US-20  provider registry (iCloud, CalDAV, ICS)
    cli.py                    US-14  dev CLI: discover/add-account/fetch/status
  sync_engine.py              US-16  (gi) schedules and launches the sync process, applies results
  system/                     OS integration. Parsing logic stays free of gi; D-Bus parts are marked
    networkmanager.py         US-17 (monitor) / US-23 (WifiConnector over D-Bus)
    timesync.py               US-17  NTP-synchronised state (timedate1)
    wifi.py                   US-23/24  nmcli command builders + parsers (no gi)
    timezone.py               US-28  zone index, labels, SetTimezone via timedate1
    brightness.py             US-29  backlight sysfs / DDC-CI / software-dim backends
    display_power.py          US-30  output on/off (wlopm / bl_power / DDC / wlr-randr / black overlay)
    device_info.py            US-31  throttling, temperature, disk
  dimming.py                  US-30  overnight schedule (pure state machine + controller)
  weather/                    US-41  client.py, cache.py (no gi), service.py (GLib)
  widgets/
    util.py                   US-02  set_text_if_changed(), set_visible_if_changed(), css class helpers
    month_view.py             US-06  MonthView = header + weekday row + 6 week rows
    header.py                 US-06  Header with start/center/end slot boxes that later stories fill
    week_row.py               US-06/07  one week: DayCells + non-targetable event content layer
    day_cell.py               US-06  one day's number and today marker (US-09 tap, US-41 forecast)
    calendar_colors.py        US-07  generated CSS for per-calendar colours
    day_detail.py             US-09  full list of one day's events
    sync_indicator.py         US-16  header sync status (US-17/19/31/38 extend)
    refresh_button.py         US-19  manual refresh button
    keyboard.py               US-21  on-screen keyboard dock + password field helper
    overlays.py               US-22  confirm dialog, toast, blocking overlay (in-app, no Gtk.AlertDialog)
    problem_banner.py         US-38  one-slot problem banner
    swipe.py                  US-35  horizontal swipe helper
    view_switcher.py          US-39/40  Month | Week | Agenda switcher
    settings/
      shell.py                US-22  SettingsScreen, section registry, sidebar
      rows.py                 US-22  SwitchRow, ChoiceRow, ButtonRow, StepperRow, ListPicker
      about.py                US-22  (version/build/IP; "Run setup again" added by US-32)
      network.py              US-23/24  (order 10)
      accounts.py             US-25     (order 20)
      calendars.py            US-26     (order 30)
      sync.py                 US-27     (order 40)
      display.py              US-29/30  (order 50)
      weather.py              US-41     (order 55)
      preferences.py          US-28     (order 60)
      status.py               US-31     (order 70)
    wizard/                   US-32
    icloud_guide.py           US-33
    week_view.py              US-39
    agenda_view.py            US-40
    weather_panel.py          US-41
    dev_*.py                  US-21/22/34  dev-only demo/test screens (flag-gated)
tests/
  fixtures/                   .ics and CalDAV XML fixtures (US-14, US-15)
  test_*.py
```

Build the layout story by story. Don't create empty modules ahead of time.

### State on the device

| What | Where on the Pi | Where in the devcontainer | Format | Created by |
|---|---|---|---|---|
| State directory | `/var/lib/calpi` (systemd `StateDirectory=calpi`, owned by `kiosk`, mode 0700) | `$CALPI_STATE_DIR`, else `~/.local/state/calpi` | directory | US-01 (unit), US-02 (`paths.py`) |
| Events, calendars, sync status | `<state>/calpi.sqlite3` (+ `-wal`, `-shm`) | same | SQLite, WAL mode | US-04 |
| Settings, account list | `<state>/settings.json` (+ `settings.json.bak`) | same | JSON, atomic writes | US-05 |
| Credentials | `<state>/credentials.bin` (encrypted), key in `<state>/keys/credentials.key` (0600) | same | AES-GCM | US-13 |
| Weather cache | `<state>/weather.json` | same | JSON | US-41 |
| Runtime scratch (crash counter, sync lock) | `/run/calpi` (systemd `RuntimeDirectory=calpi`, tmpfs, so no SD card wear) | `$XDG_RUNTIME_DIR/calpi` or `<state>/run` | small files | US-12 |
| Logs | journald (`journalctl -u calpi-kiosk`) | stdout | text | US-02 |
| App code | `/opt/calpi` (root-owned, read-only to `kiosk`) | the repo | Python | US-03 |

Nothing writes into `/opt/calpi` at runtime. The deploy step pre-compiles `.pyc` files as root (US-03), because `kiosk` can't write `__pycache__` there. Without them, every start would recompile everything, which is slow on the Pi.

### Threading and process rules (from the `gtk-kiosk-app` skill, made concrete)

1. **Widgets are only ever touched on the main thread.** Worker threads hand results back through `calpi.tasks.run_in_thread(fn, on_done=..., on_error=...)`, which uses `GLib.idle_add` internally.
2. **Every GLib callback is wrapped** with `@calpi.tasks.safe_callback` (it logs the exception and returns the right `SOURCE_*` value), so a single error can't silently stop a timer.
3. **Blocking work never runs on the main thread**: network, `subprocess.run`, `nmcli`, `ddcutil`, big SQLite writes. Small indexed SQLite *reads* (one month of events) are fine on the main thread and take well under 10 ms.
4. **Sync runs in the sync process** (see above). The UI starts it with `Gio.Subprocess` and reads the JSON summary it prints asynchronously.
5. **SQLite**: every thread and every process opens its own connection through `calpi.data.db.connect()`, which sets `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`. The UI process reads, and only writes the calendar override columns (US-26). The sync process writes everything else.

### Screens and navigation (contract from US-02)

`MainWindow` has one root `Gtk.Overlay`. Its main child is a `Gtk.Stack` (transition type `NONE`, because there are no animations) that holds the screens:

| Screen name | Widget | Added by |
|---|---|---|
| `calendar` | `MonthView` | US-06 |
| `day` | `DayDetail` | US-09 |
| `settings` | `SettingsScreen` | US-22 |
| `wizard` | `SetupWizard` | US-32 |
| `week`, `agenda` | `WeekView`, `AgendaView` | US-39, US-40 |

`window.navigator.show(name, **params)` switches screens and calls `screen.on_show(**params)` / `screen.on_hide()` when those exist. `window.navigator.back()` returns to the previous screen. Overlay layers sit above the stack: the keyboard dock (US-21), the dim layer (US-29/30), toasts and confirm dialogs (US-22), and the wake-catcher (US-30).

### Settings keys (contract from US-05; each later story adds its keys to `DEFAULTS`)

| Key | Type | Default | Added by |
|---|---|---|---|
| `schema_version` | int | 1 | US-05 |
| `setup_completed` | bool | false | US-05 (used by US-32) |
| `wizard_step` | str \| null | null | US-32 |
| `inactivity_return_seconds` | int | 120 | US-08 |
| `accounts` | list[dict] | [] | US-14 |
| `sync_interval_minutes` | int | 15 | US-16 (UI in US-27) |
| `sync_window_months_back` / `_forward` | int | 2 / 12 | US-15 |
| `timezone` | str \| null (null = system zone) | null | US-28 (read by `timeutil` from US-06) |
| `week_start` | int 0–6 (0 = Monday) | 0 | US-28 (read by `monthmath` from US-06) |
| `time_format` | `"24h"` \| `"12h"` | `"24h"` | US-28 (read by `formatting` from US-07) |
| `brightness` | int 10–100 | 100 | US-29 |
| `dim_schedule` | dict | disabled | US-30 |
| `default_view` | `"month"` \| `"week"` \| `"agenda"` | `"month"` | US-39 (or US-40 if first) |
| `weather` | dict | disabled | US-41 |
| `dismissed_problems` | dict | {} | US-38 |
| `touch_device_names` | list[str] | [] | US-34 (only if needed) |

Add every new key through `register(Key(...))` in `settings_store.py`, with a `K_*` constant. **Never** read or write a key by a bare string anywhere else.

### Error codes (contract from US-14, extended by US-18 and US-38)

`calpi.sync.errors.ErrorCode` is a `str` enum: `AUTH_FAILED`, `NETWORK_DOWN`, `DNS_FAILED`, `TIMEOUT`, `TLS_ERROR`, `CLOCK_WRONG`, `SERVER_ERROR`, `RATE_LIMITED`, `NOT_FOUND`, `PARSE_ERROR`, `CREDENTIALS_UNREADABLE`, `DISK_FULL`, `UNKNOWN`. It is recorded by the sync process (US-18) and turned into plain language by `calpi.data.messages` (US-38).

---

## Dependency graph (from `stories.md`)

`A → B` means A blocks B.

```
US-01 ─┬→ US-03 ←─ US-02
       ├→ US-12
       ├→ US-23
       └→ US-34
US-02 ─┬→ US-04 ─┬→ US-07 ─┬→ US-09
       │         │         ├→ US-26
       │         │         ├→ US-36 ─→ US-37
       │         │         ├→ US-39
       │         │         └→ US-40
       │         └→ US-15 ─┬→ US-16 ─┬→ US-17
       │                   │         ├→ US-18 ─┬→ US-31
       │                   │         │         └→ US-38
       │                   │         ├→ US-19
       │                   │         ├→ US-27 ─→ US-32
       │                   │         ├→ US-36
       │                   │         └→ US-37
       │                   └→ US-20
       ├→ US-05 ─┬→ US-13 ─→ US-14 ─┬→ US-15
       │         │                  └→ US-25 ─┬→ US-26
       │         │                            ├→ US-32
       │         │                            └→ US-33
       │         ├→ US-16
       │         └→ US-22 ─┬→ US-23 ─┬→ US-24
       │                   │         ├→ US-31
       │                   │         ├→ US-32
       │                   │         └→ US-41
       │                   ├→ US-25, US-27, US-28, US-31
       │                   └→ US-29 ─→ US-30
       ├→ US-06 ─┬→ US-07, US-08 (→ US-35), US-10, US-28, US-41
       └→ US-11 ─┬→ US-21 ─┬→ US-23
                 │         └→ US-25
                 ├→ US-22
                 └→ US-34 ─→ US-35
```

## Story index

### Epic 1: Foundation
| ID | File | Priority |
|---|---|---|
| US-01 | [Kiosk OS provisioning](US-01-kiosk-os-provisioning.md) | P0 |
| US-02 | [App skeleton](US-02-app-skeleton.md) | P0 |
| US-03 | [Deploy workflow](US-03-deploy-workflow.md) | P0 |
| US-04 | [Local event store](US-04-local-event-store.md) | P0 |
| US-05 | [Settings store](US-05-settings-store.md) | P0 |
| US-06 | [Month grid](US-06-month-grid.md) | P0 |
| US-07 | [Events in the grid](US-07-events-in-the-grid.md) | P0 |
| US-08 | [Month navigation](US-08-month-navigation.md) | P0 |
| US-09 | [Day detail view](US-09-day-detail-view.md) | P1 |
| US-10 | [Midnight rollover](US-10-midnight-rollover.md) | P0 |
| US-11 | [Pointer and touch input](US-11-pointer-and-touch-input.md) | P0 |
| US-12 | [Crash and power-loss recovery](US-12-crash-and-power-loss-recovery.md) | P0 |

### Epic 2: Calendar Syncing
| ID | File | Priority |
|---|---|---|
| US-13 | [Secure credential storage](US-13-secure-credential-storage.md) | P0 |
| US-14 | [iCloud account connection](US-14-icloud-account-connection.md) | P0 |
| US-15 | [Event fetching and parsing](US-15-event-fetching-and-parsing.md) | P0 |
| US-16 | [Scheduled background sync](US-16-scheduled-background-sync.md) | P0 |
| US-17 | [Offline resilience](US-17-offline-resilience.md) | P0 |
| US-18 | [Sync status tracking](US-18-sync-status-tracking.md) | P1 |
| US-19 | [Manual refresh](US-19-manual-refresh.md) | P1 |
| US-20 | [Additional providers](US-20-additional-providers.md) | P2 |

### Epic 3: Setup and Settings
| ID | File | Priority |
|---|---|---|
| US-21 | [On-screen keyboard](US-21-on-screen-keyboard.md) | P0 |
| US-22 | [Settings shell](US-22-settings-shell.md) | P0 |
| US-23 | [Wi-Fi scan and connect](US-23-wifi-scan-and-connect.md) | P0 |
| US-24 | [Saved network management](US-24-saved-network-management.md) | P1 |
| US-25 | [Account management](US-25-account-management.md) | P0 |
| US-26 | [Calendar customization](US-26-calendar-customization.md) | P1 |
| US-27 | [Sync settings](US-27-sync-settings.md) | P0 |
| US-28 | [Regional preferences](US-28-regional-preferences.md) | P0 |
| US-29 | [Brightness control](US-29-brightness-control.md) | P1 |
| US-30 | [Overnight dim and sleep schedule](US-30-overnight-dim-and-sleep.md) | P1 |
| US-31 | [Status screen](US-31-status-screen.md) | P1 |
| US-32 | [First-time setup wizard](US-32-first-time-setup-wizard.md) | P0 |
| US-33 | [iCloud setup guide](US-33-icloud-setup-guide.md) | P1 |

### Epic 4: Touch and Polish
| ID | File | Priority |
|---|---|---|
| US-34 | [Touchscreen bring-up](US-34-touchscreen-bring-up.md) | P1 |
| US-35 | [Touch gestures](US-35-touch-gestures.md) | P2 |
| US-36 | [Performance targets](US-36-performance-targets.md) | P1 |
| US-37 | [Long-running stability](US-37-long-running-stability.md) | P1 |
| US-38 | [User-facing error handling](US-38-user-facing-error-handling.md) | P1 |

### Epic 5: Extras
| ID | File | Priority |
|---|---|---|
| US-39 | [Week view](US-39-week-view.md) | P2 |
| US-40 | [Agenda view](US-40-agenda-view.md) | P2 |
| US-41 | [Weather](US-41-weather.md) | P2 |

## Known gaps in the formal dependency graph

The "Blocked by" column in `stories.md` lists only the **direct** blockers that matter for completing a story. A few stories also depend in practice on stories that aren't in their chain. Each story file lists these under "Soft dependencies". The important ones:

- **US-14 / US-25 and US-04:** discovered calendars are written to the event store's `calendars` table. On the critical path US-04 is always done first, so this never actually blocks.
- **US-12 and US-02/US-04/US-05:** US-12's OS-level work only needs US-01, but its app-level work (safe callbacks, database integrity checks, settings backup) touches modules from those stories.
- **Everything that's checked on the Pi and US-03:** without the deploy workflow you can't verify on hardware.
- **US-30 and US-32:** US-30 adds a dimming step to the wizard if the wizard already exists. If it doesn't, US-32 adds the step itself when it's built after US-30.
