# calpi

A self-contained wall calendar for the Raspberry Pi. A Pi 3B drives a 1920x1080 HDMI touchscreen that shows
this month's events, keeps itself up to date from online calendars, and is set up and managed entirely from
its own screen: no keyboard, second monitor or computer needed once it is installed.

It is a Python + GTK 4 app running fullscreen under the [cage](https://github.com/cage-kiosk/cage) Wayland
compositor, started by systemd on boot.

## Features

- **Calendar views:** month grid (default), week timeline and agenda list, with a day detail view for busy
  days. Swipe or use the arrows to change month/week; it returns to today after a period of inactivity and
  rolls over at midnight.
- **Calendar sync:** iCloud (Apple ID + app-specific password, with an on-screen guide and QR code), any
  CalDAV server (Fastmail, Nextcloud, ...) and read-only ICS subscriptions (Google "secret address", holiday
  feeds). Sync runs in a background worker on a configurable interval, with manual refresh, retry/backoff and
  offline support. Sync is read-only.
- **Weather:** forecast in the header and day cells from Open-Meteo (no API key).
- **On-device setup:** a first-run wizard (Wi-Fi, time zone and preferences, accounts, sync and dimming) and
  a Settings area covering network, accounts and calendars (show/hide, rename, recolour), sync, display
  brightness, overnight dim/sleep, regional preferences, and a Status page that explains problems in plain
  language. Text entry uses a built-in on-screen keyboard.
- **Reliability:** events are cached in a local SQLite database, credentials are encrypted with AES-GCM,
  and a systemd watchdog, crash guard with safe mode, hardware watchdog and hourly self-monitoring keep it
  running for months. The Pi's setup is tuned to limit SD-card wear.

## Repository layout

| Path | What's there |
|---|---|
| `run.py` | Entry point |
| `calpi/` | The app: `app.py`, `widgets/` (views, settings, keyboard), `sync/` (providers, worker, CLI), `data/` (event store, settings, messages, sample data), `system/` (Wi-Fi, brightness, time zone, touch), `weather/`, `devtools/` (benchmarks, soak tests) |
| `scripts/pi` | Deploy to the Pi and manage it over SSH |
| `scripts/dev-run.sh`, `scripts/smoke.sh` | Run the app or a smoke test in the devcontainer |
| `deps/` | apt packages for the Pi (`apt-runtime.txt`) and the devcontainer (`apt-dev.txt`) |
| `.claude/skills/pi-kiosk-setup/` | Pi provisioning script, systemd unit and PAM config |
| `docs/` | Plan, user stories, providers, security, performance and the Pi verification checklist |
| `tests/` | pytest suite |

## Development

Development happens in the devcontainer (`.devcontainer/`), which installs the packages from `deps/`. The
app uses the system Python (`/usr/bin/python3`, 3.11+) and apt-packaged libraries; there are no pip
dependencies.

Run the app in a browser via GTK's Broadway backend:

```bash
scripts/dev-run.sh                 # then open http://localhost:8085
scripts/dev-run.sh --sample-data   # load sample events first
```

State (settings, database, credentials) goes to `.devstate/` unless `CALPI_STATE_DIR` is set.

Useful `run.py` options: `--windowed` (don't go fullscreen), `--state-dir DIR`, `--sample-data`,
`--exit-after SECONDS`.

### Tests

```bash
/usr/bin/python3 -m pytest                      # unit tests
CALPI_GTK_TESTS=1 /usr/bin/python3 -m pytest    # also the GTK tests (need Broadway)
scripts/smoke.sh                                # start the app headless and check it comes up
```

## Setting up a Raspberry Pi

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. In its customisation settings, set
   the hostname (e.g. `calpi`), a user, Wi-Fi and time zone, and enable SSH with your public key.
2. Provision it as a kiosk (installs cage, the `kiosk` user, the systemd unit, polkit rules, watchdogs and
   SD-wear settings; safe to re-run):

   ```bash
   scp .claude/skills/pi-kiosk-setup/{setup-pi.sh,calpi-kiosk.service,pam-calpi-kiosk} calpi:/tmp/
   ssh calpi 'sudo WIFI_COUNTRY=US bash /tmp/setup-pi.sh'
   ```

   Options are passed as environment variables, e.g. `LEAN=1` (disable Bluetooth and other unused services),
   `ROTATE=180`, `MODE=1920x1080@60D`, `TOUCH_NAME=...`/`TOUCH_MATRIX=...` for touch calibration. See the top
   of `setup-pi.sh`.
3. Install runtime packages and deploy the app:

   ```bash
   scripts/pi deps
   scripts/pi deploy
   ```

The Pi then boots straight into calpi. On first start it runs the setup wizard on screen.

`scripts/pi` expects the Pi to be reachable as `calpi` over SSH (set `CALPI_HOST` / `CALPI_USER` to
change that). See `docs/pi-checklist.md` for the full verification list.

## Managing the Pi

```bash
scripts/pi deploy [--no-restart]   # sync the code to /opt/calpi, restart, wait until ready
scripts/pi rollback                # restore the previous deploy
scripts/pi restart
scripts/pi status                  # service status and running build
scripts/pi logs [-f] [-n N]        # this boot's journal
scripts/pi screenshot [file.png]   # capture what's on the HDMI screen
scripts/pi health                  # throttling, temperature, memory, disk
scripts/pi perf                    # run the benchmark suite on the device
scripts/pi soak start|sample|stop|collect   # long-running stability test
scripts/pi ssh [cmd...]
```

## Adding calendars

Normally from the screen: **Settings > Accounts > Add account**. Accounts can also be added from the command
line on the Pi or in the devcontainer (stop the kiosk first, or restart it afterwards):

```bash
python3 -m calpi.sync.cli add-account --provider icloud --username you@icloud.com
python3 -m calpi.sync.cli add-account --provider caldav --server https://cloud.example.com --username me
python3 -m calpi.sync.cli add-account --provider ics --name Holidays
python3 -m calpi.sync.cli list-accounts
python3 -m calpi.sync.cli status
```

Passwords and feed links are prompted for and never shown. For iCloud, create an app-specific password at
[account.apple.com](https://account.apple.com) (Sign-In and Security > App-Specific Passwords). See
[docs/providers.md](docs/providers.md) for how to get credentials for other providers.

## Documentation

- [docs/plan.md](docs/plan.md): goals, features and phases
- [docs/user-stories/](docs/user-stories/): detailed requirements (US-01 ... US-41)
- [docs/providers.md](docs/providers.md): calendar providers and credentials
- [docs/security.md](docs/security.md): credential storage and log redaction
- [docs/performance.md](docs/performance.md) and [docs/stability.md](docs/stability.md): targets and how
  they're measured
- [docs/pi-checklist.md](docs/pi-checklist.md): what to verify on real hardware
- [docs/platform-versions.md](docs/platform-versions.md): OS and library versions on the device
