# US-12 — Crash and power-loss recovery

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P0 |
| **Blocked by** | US-01 Kiosk OS provisioning |
| **Blocks** | — |
| **Phase** | 1. Foundation |

## Story

> As the owner, I want the app to restart itself after a crash and come back cleanly after a power cut, without wearing out the SD card.

## Context

This device will be unplugged without warning (someone needs the socket), it'll lose power in storms, and eventually some bug will crash it or freeze it. None of that should ever need a person with a keyboard. Recovery works in layers:

| Layer | What fails | What recovers it |
|---|---|---|
| App process crashes (Python exception at startup, segfault in GTK) | The app exits → cage exits | systemd `Restart=always` restarts cage and the app |
| App **hangs** (the main loop is blocked, deadlocked, or stuck in C code) | The screen freezes but the process stays alive | **systemd watchdog**: the app sends `WATCHDOG=1` from its main loop. If that stops, systemd kills and restarts it |
| **Crash loop** (for example bad data makes the app crash every time it starts) | It restarts forever, and the screen flickers | The **crash guard** notices repeated starts and starts in **safe mode**, which skips the likely cause |
| The kernel or the whole system hangs | Everything freezes | The **hardware watchdog** reboots the Pi |
| Power loss in the middle of a write | Files could be half-written | Atomic writes (US-05), SQLite WAL (US-04), an **integrity check at startup** with automatic reset of the event database, ext4 journal + `fsck.repair=yes` |
| SD card wear | The card dies after months or years | Few writes: the journal size is capped, there's no swap on the SD card, `noatime`, `/tmp` on tmpfs, and the app writes only when something changed |

The OS-level parts only need US-01. The app-level parts touch modules from US-02, US-04, and US-05. **Do the OS parts first, then do the app parts for whichever modules exist**, and record what's left over (see the blockers).

Load the `pi-kiosk-setup` skill (the watchdog, overlay FS, and "Lean and robust" sections) and the `gtk-kiosk-app` skill ("Robustness": let crashes crash, and don't wrap `main()` in a retry loop).

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-01** Kiosk OS provisioning | The provisioned Pi, the `calpi-kiosk.service` template in the skill directory with `StateDirectory` and `RuntimeDirectory` (`RuntimeDirectoryPreserve=yes`), and no network-online wait | `ssh calpi 'systemctl cat calpi-kiosk \| grep -E "StateDirectory\|RuntimeDirectory\|network-online"'` shows the two directories and **no** network-online. `docs/platform-versions.md` exists (you need the systemd version). |

### Soft dependencies (they block parts of this story)

| Soft blocker | Blocks which part | If it isn't done |
|---|---|---|
| **US-02** App skeleton | `watchdog.py`, `crashguard.py`, signal handling, faulthandler, all the app-level parts | Do only the OS parts (steps 1–4), and mark the story **partially done** |
| **US-03** Deploy workflow | Every check on the Pi | Deploy by hand with `scp` + restart, the way US-02 step 12 does |
| **US-04** Local event store | The startup integrity check and reset (step 7) | Write `recover_database()` against US-04's interface when it lands, or leave the step for the US-04 implementer with a clear TODO **in this file's hand-off notes** |
| **US-05** Settings store | Nothing extra: the settings recovery is already in US-05 | — |
| **US-16** Scheduled sync | The power-cut test **during a sync** (step 10, case C) | Test that case later, and note it in US-16's hand-off |

### External blockers

| Blocker | What to do |
|---|---|
| **Pulling the power on the real device** | Real power-cut tests need the owner's help (or a smart plug they control). **Never** trigger reboots or power cycles without the owner's go-ahead (the `pi-deploy` skill's "Don'ts"). `echo b > /proc/sysrq-trigger` is a close software substitute; still ask first. |
| **The systemd version** decides the restart-backoff options | `RestartSteps=`/`RestartMaxDelaySec=` need systemd ≥ 254 (Trixie has 257; Bookworm has 252). Check `platform-versions.md`. |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| `Type=notify` and the service never becomes "active" | The app must send `READY=1`, and `NotifyAccess=all` is needed, because the main PID is **cage**, not Python. Check `$NOTIFY_SOCKET` is in the app's environment (cage passes its environment on: check `/proc/<pid>/environ`). |
| The watchdog kills a healthy app during a slow startup | Send `READY=1` only after the first frame, and set `TimeoutStartSec=90`. The watchdog timer only starts counting after READY. |
| The hardware watchdog reboots in a loop | `RuntimeWatchdogSec` set too low, or something blocking PID 1. Remove the setting over SSH, report it, and use 15 s or more. |
| The overlay FS seems like "the" answer to SD wear | **No**: it would throw away `/var/lib/calpi` at every reboot (US-01 D9). Stick to reducing writes. |

---

## Scope

### In scope
- Service unit: restart policy, `Type=notify`, `NotifyAccess=all`, `WatchdogSec`, `TimeoutStartSec`, backoff.
- `calpi/watchdog.py`: sd_notify (`READY=1`, `WATCHDOG=1`, `STATUS=...`, `STOPPING=1`) with the stdlib `socket`.
- `calpi/crashguard.py`: counting starts in `/run/calpi`, and safe-mode detection.
- Safe mode: what it skips, and how it shows itself.
- `faulthandler` (tracebacks for segfaults and hangs), `sys.excepthook`, `threading.excepthook`, clean `SIGTERM`.
- Startup integrity check and reset of the event database (with US-04).
- The hardware watchdog.
- SD card wear: journald limits, swap, `noatime`, `/tmp`, and checking `fsck.repair`.
- Measuring SD writes, and the crash, hang, and power-cut test campaign.

### Out of scope
- User-facing error messages (US-38 shows the "data was reset" and "safe mode" notices properly. Here, a simple banner label is enough).
- Long-running memory and CPU behaviour (US-37).
- The overlay FS (not used).

---

## Acceptance criteria

1. **Crash**: after `sudo pkill -9 -f /opt/calpi/run.py`, the calendar is back on screen within **10 s**.
2. **Segfault**: after `sudo pkill -SEGV -f /opt/calpi/run.py`, the journal shows a Python traceback from `faulthandler` ("Fatal Python error: Segmentation fault" plus a stack), and the app is back within 10 s.
3. **Hang**: after `sudo pkill -STOP -f /opt/calpi/run.py` (the process is frozen), systemd's watchdog kills and restarts the service within **WatchdogSec + 15 s** (≤ 45 s with `WatchdogSec=30`). The journal shows `Watchdog timeout`.
4. **Hang diagnosis**: `sudo pkill -USR1 -f /opt/calpi/run.py` prints the stack of every Python thread to the journal, without stopping the app.
5. **Crash loop**: with a test hook that crashes whenever events are rendered (`CALPI_TEST_CRASH=render`), after **4 crashes within 10 minutes** the 5th start comes up in **safe mode**: the grid shows without events, background sync doesn't start, a banner says "calpi restarted several times and is running in safe mode. Your data is safe.", and Settings (once it exists) is still reachable. The counter resets after **10 minutes** of stable running, or at reboot.
6. **systemd never gives up**: 30 crashes in a row don't leave the service in `failed` state (`StartLimitIntervalSec=0`). The restart delay grows to at most 60 s if the systemd version supports it (≥ 254). Otherwise it's a fixed 5 s.
7. **Corrupt event database**: if `PRAGMA quick_check` fails at startup, the database files are moved to `calpi.sqlite3.corrupt-<ts>` (+ `-wal`/`-shm`, keeping at most 2 sets), a new empty database is created, an ERROR is logged, and a flag is set that US-38 will show ("Calendar data was reset and will download again"). The app starts normally. The next sync fills it again.
8. **Power cuts**: across **20 real power cuts** at random moments (at least 5 during boot, 5 while idle, 5 during settings writes, and 5 during sync once US-16 exists), the device always comes back to the calendar by itself, with no manual intervention, settings intact (old or new values), and the event database either fine or automatically reset.
9. **Hardware watchdog**: `dtparam=watchdog=on` in `config.txt` and `RuntimeWatchdogSec=15` for systemd are active (`systemctl show -p RuntimeWatchdogUSec` → `15s`). *Tested only if the owner agrees:* `echo c | sudo tee /proc/sysrq-trigger` (a kernel crash) → the Pi reboots and the app comes back.
10. **SD writes**: while idle (no user input, no sync), the app and system write **< 5 MB/hour** to the SD card. With sync every 15 minutes and unchanged calendars, **< 20 MB/hour**. Measure with `/sys/block/mmcblk0/stat` over one hour and record the numbers.
11. Journald: persistent, at most **32 MB**. The swap isn't on the SD card (zram or none). Root is mounted `noatime`. `/tmp` is tmpfs. `fsck.repair=yes` is in `cmdline.txt`.
12. `SIGTERM` (for example `systemctl stop`) shuts the app down cleanly: logs `calpi stopping`, sends `STOPPING=1`, and exits within 5 s.

---

## Design decisions (already made)

- **D1. Unit changes** (in `.claude/skills/pi-kiosk-setup/calpi-kiosk.service`):
  ```ini
  [Unit]
  StartLimitIntervalSec=0            # never enter "failed" because of restart limits

  [Service]
  Type=notify
  NotifyAccess=all                   # the notifier is python, a child of cage (the main PID)
  WatchdogSec=30
  TimeoutStartSec=90                 # READY=1 must arrive within 90 s of start
  TimeoutStopSec=10
  Restart=always
  RestartSec=5
  # systemd >= 254 only (Trixie): exponential backoff up to 60 s
  RestartSteps=5
  RestartMaxDelaySec=60
  ```
  On systemd < 254, `RestartSteps`/`RestartMaxDelaySec` give an "unknown key" warning and are ignored. **Remove them for Bookworm** to keep the journal clean. Do it in `setup-pi.sh`: detect the systemd version and use `sed` on the installed unit.
- **D2. sd_notify is implemented with the stdlib** (an `AF_UNIX` datagram socket to `$NOTIFY_SOCKET`, including the abstract-namespace case where the name starts with `@`). **Don't** depend on `python3-systemd`. If `NOTIFY_SOCKET` isn't set (dev), every call does nothing.
- **D3. READY=1 is sent after the first frame is painted** (the window's frame clock `after-paint`, once). WATCHDOG=1 is sent every **10 s** from a `GLib.timeout_add_seconds` on the **main loop**. That proves the loop is alive. **Never send watchdog pings from a thread**: a thread would keep pinging while the UI is frozen.
- **D4. Crash guard file**: `/run/calpi/starts` (tmpfs, `RuntimeDirectoryPreserve=yes`: it survives service restarts and is wiped at reboot). One line per start, holding a Unix timestamp. Safe mode = **≥ 4 earlier starts in the last 600 s**. After the app has run stably for 600 s, the file is truncated. The file is written atomically (the lines are tiny: rewrite the whole file with `atomic_write_bytes`; it's on tmpfs, so there's no wear).
- **D5. Safe mode skips**: loading events into the grid (the empty grid is still shown), starting sync automatically, and any other "extras" later stories register (weather, and so on: they check `app.safe_mode`). Safe mode **keeps**: the grid frame, navigation, Settings, and manual sync (so the owner can try to fix things). A banner in the header's `end_slot`: "Safe mode". Tapping it (later, US-31) opens the Status screen.
- **D6. Journald** config through a drop-in `/etc/systemd/journald.conf.d/calpi.conf`:
  ```ini
  [Journal]
  Storage=persistent
  SystemMaxUse=32M
  RuntimeMaxUse=16M
  SyncIntervalSec=10m
  RateLimitIntervalSec=30s
  RateLimitBurst=2000
  ```
  **Persistent** so the logs from before a power cut or crash survive (that's worth a small amount of wear). `SyncIntervalSec=10m` batches writes. CRIT/ALERT/EMERG messages are synced at once anyway.
- **D7. Swap**: if `dphys-swapfile` is active (Bookworm), disable it (`systemctl disable --now dphys-swapfile`), and install `zram-tools` (or `systemd-zram-generator`) with about 256 MB of zram. On Trixie, Pi OS already uses `rpi-swap` with zram. **Check** that no swap file is on the SD card (`swapon --show`), and record it.
- **D8. The integrity check** runs **before** any widget is built, on the UI thread (it takes milliseconds for our database size). A corrupt database is moved aside, never deleted straight away (keep the 2 newest, for diagnosis).
- **D9. Signals**: `faulthandler.enable()` (to stderr, which goes to the journal) at the top of `run.py`. `faulthandler.register(signal.SIGUSR1, all_threads=True)` for hang diagnosis. `GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, on_term)`, which calls `app.quit()` after `STOPPING=1`.
- **D10. `sys.excepthook` / `threading.excepthook`** log at CRITICAL with the traceback. The main-thread hook then lets the process die (exit code 1). Worker-thread exceptions are logged and the thread ends (the app carries on).

---

## Implementation plan

### Step 1 — Unit file and provisioning (OS part)

Edit the template (D1). In `setup-pi.sh`, add an idempotent section:
```bash
echo "==> robustness"
SYSTEMD_VER=$(systemctl --version | awk 'NR==1{print $2}')
if (( SYSTEMD_VER < 254 )); then
  sed -i '/^RestartSteps=/d;/^RestartMaxDelaySec=/d' /etc/systemd/system/calpi-kiosk.service
fi
install -d /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/calpi.conf <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=32M
RuntimeMaxUse=16M
SyncIntervalSec=10m
RateLimitIntervalSec=30s
RateLimitBurst=2000
EOF
mkdir -p /var/log/journal
# hardware watchdog
grep -q '^dtparam=watchdog=on' /boot/firmware/config.txt || echo 'dtparam=watchdog=on' >> /boot/firmware/config.txt
install -d /etc/systemd/system.conf.d
printf '[Manager]\nRuntimeWatchdogSec=15\nRebootWatchdogSec=2min\n' > /etc/systemd/system.conf.d/calpi-watchdog.conf
# swap: never on the SD card
if systemctl list-unit-files dphys-swapfile.service >/dev/null 2>&1; then
  systemctl disable --now dphys-swapfile || true
  dphys-swapfile uninstall 2>/dev/null || true
fi
# (install zram-tools here if no zram swap exists — check `swapon --show` on the recorded release first)
# fsck on boot
grep -q 'fsck.repair=yes' /boot/firmware/cmdline.txt || sed -i 's/$/ fsck.repair=yes/' /boot/firmware/cmdline.txt
systemctl daemon-reload
systemctl restart systemd-journald
```
Check `fstab` for `noatime` on `/` (Pi OS default: `defaults,noatime`). Don't change it automatically if it's already there. Check whether `/tmp` is tmpfs (`findmnt /tmp`). If it isn't, `systemctl enable tmp.mount` (if available), or add a tmpfs fstab line. **Test the `cmdline.txt` sed carefully**: the file must stay one line.

The hardware watchdog and `RuntimeWatchdogSec` only take effect after a **reboot**. Ask the owner before rebooting.

Copy the files over, run `setup-pi.sh` again, and check each item from acceptance criterion 11.

### Step 2 — `calpi/watchdog.py` (no gi)

```python
"""Minimal sd_notify (no python3-systemd dependency)."""
import os, socket, logging
log = logging.getLogger("calpi.watchdog")

def _addr():
    a = os.environ.get("NOTIFY_SOCKET")
    if not a: return None
    return "\0" + a[1:] if a.startswith("@") else a

def notify(msg: str) -> bool:
    addr = _addr()
    if addr is None: return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as s:
            s.connect(addr)
            s.sendall(msg.encode())
        return True
    except OSError as e:
        log.warning("sd_notify failed: %s", e)
        return False

def ready(status="running"): notify(f"READY=1\nSTATUS={status}")
def ping(): notify("WATCHDOG=1")
def stopping(): notify("STOPPING=1")
def status(text: str): notify(f"STATUS={text}")
def watchdog_interval_s() -> float | None:
    usec = os.environ.get("WATCHDOG_USEC")
    return int(usec) / 1e6 if usec else None
```
`WATCHDOG_USEC` is set by systemd for the main process. The child (Python under cage) might not see it, because systemd sets it only for the main PID, and cage passes on what it got. **Check this on the Pi.** If it's missing, use a fixed ping interval of 10 s. Don't rely on `WATCHDOG_PID`.

### Step 3 — Wire the watchdog into the app

In `CalpiApp._on_activate` (after the window is presented):
```python
def _after_first_paint(clock):
    clock.disconnect(handler_id[0])
    watchdog.ready()
    log.info("watchdog: READY sent")
fc = self.window.get_frame_clock()
handler_id = [fc.connect("after-paint", _after_first_paint)] if fc else None
if fc is None:   # frame clock not yet available before mapping; connect on "map"
    ...
GLib.timeout_add_seconds(10, safe_callback(watchdog.ping, repeat=True))
```
The frame clock only exists once the window is realised. Connect in a `map` or `realize` handler on the window, or use `GLib.idle_add` after `present()` and fetch the frame clock there. Test it in Broadway (READY does nothing there, but log it so you can see the order).

Also log the watchdog configuration once at startup: `watchdog: NOTIFY_SOCKET=%s interval=%s`.

### Step 4 — Crash-time diagnostics in `run.py`

At the very top (before any other import):
```python
import faulthandler, signal, sys
faulthandler.enable(file=sys.stderr, all_threads=True)
faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True, chain=False)
```
In `calpi/app.py` `main()`:
```python
def _excepthook(exc_type, exc, tb):
    logging.getLogger("calpi").critical("uncaught exception", exc_info=(exc_type, exc, tb))
sys.excepthook = _excepthook
threading.excepthook = lambda args: logging.getLogger("calpi").critical(
    "uncaught exception in thread %s", args.thread.name if args.thread else "?",
    exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

def _on_term():
    log.info("calpi stopping (SIGTERM)")
    watchdog.stopping()
    app.quit()
    return GLib.SOURCE_REMOVE
GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, _on_term)
```
Note: PyGObject may print exceptions from GLib callbacks itself instead of going through `sys.excepthook`. That's why every callback uses `safe_callback` (US-02).

### Step 5 — `calpi/crashguard.py` (no gi)

```python
WINDOW_S = 600
THRESHOLD = 4          # >= 4 previous starts in the window -> safe mode
STABLE_S = 600

def record_start_and_check(now: float | None = None) -> bool:
    """Record this start; return True if we should run in safe mode."""
    now = now or time.time()
    f = paths.runtime_dir() / "starts"
    try:
        prev = [float(x) for x in f.read_text().split() if x.strip()]
    except (OSError, ValueError):
        prev = []
    recent = [t for t in prev if now - t < WINDOW_S]
    atomic_write_bytes(f, ("\n".join(str(t) for t in recent + [now]) + "\n").encode(), mode=0o600)
    return len(recent) >= THRESHOLD

def mark_stable() -> None:
    try: (paths.runtime_dir() / "starts").write_text("")
    except OSError: pass
```
In the app: `self.safe_mode = crashguard.record_start_and_check()` at the very start of `_on_activate`. If it's true, log a WARNING `SAFE MODE: N starts in 10 min`. Then `GLib.timeout_add_seconds(STABLE_S, ...)` calls `mark_stable()` once.

**Use `time.time()` here** (not monotonic, because it has to be compared across processes). Clock jumps at boot don't matter: the file is on tmpfs and empty at boot.

### Step 6 — Safe mode behaviour

- `CalpiApp.safe_mode: bool`, which every component can read.
- `MonthView.attach_store` (US-07): if `safe_mode`, don't load events. Keep the grid.
- The sync engine (US-16): don't schedule automatic syncs in safe mode. (Put a line in US-16's hand-off notes, or add the check yourself if US-16 exists.)
- The banner: a `Gtk.Label` "Safe mode" with class `.safe-mode-badge` (red-ish, `@danger`) in `header.end_slot`, plus a larger one-time explanation label under the header: "calpi restarted several times and is running in safe mode. Your data is safe." US-38 will turn this into its standard error presentation.

**Test hook** (dev and test only, **guarded by an environment variable**): `CALPI_TEST_CRASH=render` makes `MonthView.reload` raise `SystemExit(1)` (to simulate a data-triggered crash) *unless* `safe_mode`. Also `CALPI_TEST_CRASH=start` makes `main()` exit before the window (to test the restart backoff; that one crashes in safe mode too, on purpose).

### Step 7 — Event database integrity at startup (needs US-04)

In `calpi/data/db.py` (no gi):
```python
def recover_if_corrupt(path: Path | None = None) -> bool:
    """Returns True if the DB was reset. Call before opening the store for real."""
    path = path or default_path()
    if not path.exists(): return False
    try:
        conn = sqlite3.connect(str(path), timeout=5.0)
        ok = conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        conn.close()
    except sqlite3.DatabaseError:
        ok = False
    if ok: return False
    ts = int(time.time())
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists(): os.replace(p, Path(f"{path}.corrupt-{ts}{suffix}"))
    _prune_corrupt_sets(path, keep=2)
    log.error("event database failed integrity check; moved aside as %s.corrupt-%d", path.name, ts)
    return True
```
Call it at the start of `_on_activate` (after the crash guard, before creating `EventStore`). Store the result as `app.startup_notices.append("db_reset")`: a plain list that US-38 will display. For now, log it and show a small label.

**Also handle the case where the sync process finds corruption** (it gets `sqlite3.DatabaseError` while writing): it logs and exits with an error code. The next UI start runs the check. Put a note in US-16's hand-off notes.

**Test**: create a database, corrupt it by overwriting bytes in the middle of the file with `os.urandom`, check `recover_if_corrupt` returns True, the corrupt files are moved aside, and a new `EventStore` opens cleanly. Truncate the file to half its size → the same result. Put 0 bytes in it → sqlite treats an empty file as a valid empty database. Check that doesn't raise.

### Step 8 — Settings recovery check

US-05 already handles a corrupt `settings.json`. Add a test in this story's test suite (or check the US-05 tests exist) that the **app** starts with garbage in `settings.json`: run `scripts/smoke.sh` with a pre-seeded state directory.

### Step 9 — Measure SD writes

```bash
scripts/pi ssh 'awk "{print \$7}" /sys/block/mmcblk0/stat'   # sectors written (512 B each)
# ... wait exactly 1 hour, idle (no input, sync off or unchanged) ...
scripts/pi ssh 'awk "{print \$7}" /sys/block/mmcblk0/stat'
```
(difference × 512 / 1,048,576) = MB/hour. If it's over the target, find the writer: `sudo apt-get install -y iotop` then `sudo iotop -oPa -d 60`, or check `/proc/<pid>/io` (`write_bytes`) for journald, python3, and NetworkManager. Common culprits: journald at DEBUG level, NetworkManager writing lease files, `systemd-timesyncd` (writes the clock file on every sync: acceptable), and **our own app writing settings or the database without changes** (compare the US-04 revision before and after an idle hour: it must be unchanged).

### Step 10 — The test campaign (on the Pi, with the owner's help for power cuts)

Record every run in a table in the hand-off notes (`case | time | recovered? | seconds to calendar | notes`).

- **A. Crash** (acceptance criteria 1–2): `pkill -9`, `pkill -SEGV` → recovery times, and the traceback seen in `scripts/pi logs`.
- **B. Hang** (acceptance criteria 3–4): `pkill -USR1` (stacks printed, the app still running), then `pkill -STOP` → the watchdog restart, and `Watchdog timeout` in `journalctl -u calpi-kiosk`.
- **C. Crash loop** (acceptance criteria 5–6): add a drop-in with `Environment=CALPI_TEST_CRASH=render`, restart, and watch: 4 quick crashes, then safe mode. Screenshot. Then `CALPI_TEST_CRASH=start` → 30 restarts over time, and `systemctl is-failed calpi-kiosk` stays `active`/`activating`, never `failed`. Record the growing restart delay. **Remove the drop-in** and check with `systemctl cat`.
- **D. Power cuts** (acceptance criterion 8): 20 cuts, as listed. For the "during settings writes" case, use the loop script from US-05 step 7. After each boot: `scripts/pi ssh 'sudo -u kiosk sqlite3 /var/lib/calpi/calpi.sqlite3 "pragma quick_check"; sudo cat /var/lib/calpi/settings.json | head -5'` (install the `sqlite3` CLI on the Pi if needed, as a dev tool: note it, but don't add it to `deps/apt-runtime.txt`).
- **E. Kernel crash** (acceptance criterion 9): only with the owner's OK.
- **F. SD writes** (acceptance criterion 10): step 9.

---

## Files

| File | Change |
|---|---|
| `.claude/skills/pi-kiosk-setup/calpi-kiosk.service` | D1 |
| `.claude/skills/pi-kiosk-setup/setup-pi.sh` | The robustness section (step 1) |
| `.claude/skills/pi-kiosk-setup/SKILL.md` | Watchdog, journald, and swap notes |
| `run.py` | faulthandler |
| `calpi/watchdog.py`, `calpi/crashguard.py` | New |
| `calpi/app.py` | READY/WATCHDOG, excepthooks, SIGTERM, safe mode, integrity check, test hooks |
| `calpi/data/db.py` | `recover_if_corrupt()` (with US-04) |
| `calpi/widgets/month_view.py` | Safe-mode skip, the banner |
| `calpi/style.css` | `.safe-mode-badge` |
| `tests/test_watchdog.py`, `tests/test_crashguard.py`, `tests/test_db_recovery.py` | New |

---

## Testing (unit)

- `test_watchdog.py`: bind a temporary `AF_UNIX` datagram socket, set `NOTIFY_SOCKET` to its path, call `ready()`, and check the received bytes. With `@abstract`, the same thing using an abstract name. Without `NOTIFY_SOCKET` → returns False, with no exception.
- `test_crashguard.py`: use `tmp_path` as the runtime directory (monkeypatch `paths.runtime_dir`). 4 starts inside 10 min → the 5th returns True. Starts spread over 11 min → False. `mark_stable` clears it. A corrupt file → treated as empty.
- `test_db_recovery.py`: step 7's cases.

---

## Pitfalls

- **Watchdog pings from a thread**: they hide the exact hang the watchdog exists to catch (D3).
- **READY=1 too early**: the watchdog then starts during a slow first render and kills a healthy startup.
- **Missing `NotifyAccess=all`**: notifications from the child are ignored, and `Type=notify` times out after 90 s, causing a restart loop. It looks like "the app keeps restarting every 90 s".
- **`StartLimitIntervalSec=0` in `[Service]`**: it belongs in **`[Unit]`**.
- **Deleting a corrupt database immediately**: keep it for diagnosis (D8).
- **Leaving test drop-ins** (`CALPI_TEST_CRASH`) on the device. Always remove them and check with `systemctl cat calpi-kiosk`.
- **Rebooting or power-cycling without the owner's OK.**

---

## Definition of done

- [ ] All acceptance criteria met, with the campaign table (A–F) in the hand-off notes.
- [ ] The provisioning script is still idempotent, and the skill doc is updated.
- [ ] All test drop-ins removed from the Pi.
- [ ] Anything deferred (for example power cuts during sync, waiting for US-16) is listed explicitly.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `app.safe_mode` (bool): extras and automatic sync check it | US-16, US-41, and any optional feature |
| `app.startup_notices` (list of codes such as `"db_reset"`, `"safe_mode"`) | US-38 shows them, US-31 lists them |
| `watchdog.status(text)` for a short status string in `systemctl status` | US-16 ("last sync 14:05"), optional |
| The main loop must never block for more than about 20 s, or the watchdog restarts the app (WatchdogSec=30, ping every 10 s) | **all stories**: yet another reason to keep blocking work off the main thread |
| `db.recover_if_corrupt()` runs before the store opens | US-04 (implemented together), US-16 |
| Journal capped at 32 MB: **keep INFO logging modest** (no per-frame or per-event INFO lines) | all stories, US-37 |
| `CALPI_TEST_CRASH` hooks (dev only) | US-37 |
