# US-31 — Status screen

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P1 |
| **Blocked by** | US-18 Sync status tracking, US-22 Settings shell, US-23 Wi-Fi scan and connect |
| **Blocks** | — |
| **Phase** | 3. Setup and Settings (P1) |

## Story

> As a user, I want one screen that shows the network status, the last sync time and any errors, in plain language.

## Context

When the calendar looks wrong ("why isn't my new event there?"), the owner needs **one place** that answers, without SSH or jargon: *Is it online? When did it last update? Is anything broken, and what should I do?*

The data already exists:
- **Network**: `app.network` (US-17), the US-23/24 parsers and `ConnectionStatusGroup`, and `wifi.internet_status`.
- **Sync**: `app.sync_status` (US-18: per-account and per-calendar last attempt/success/error, and recent runs), `app.sync` (US-16/17: running, next run, offline).
- **Device**: `app.startup_notices` and `app.safe_mode` (US-12/13), `app.clock_trust` (US-17), the build (US-03), uptime, storage, and **power/temperature warnings** from `vcgencmd get_throttled` (a weak power supply is a very common Pi problem, and it's invisible without this).

This story presents it as a **Status** section in Settings, reachable directly by **tapping the sync indicator** in the calendar header. It starts with a one-line **overall verdict** ("Everything is working" / "calpi is offline" / "iCloud needs you to sign in again"), followed by details.

Plain-language text comes from `calpi/data/messages.py`. **US-38 owns that catalogue** (messages + suggested fixes). If US-38 isn't done, this story creates the module with the **same interface** and short texts, and US-38 extends it (D2).

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-18** Sync status tracking | `app.sync_status` (`StatusSnapshot`: accounts, calendars, runs), `app.status_callbacks` | `grep -n "def snapshot" calpi/data/sync_status.py`; `python3 -m calpi.sync.cli status` works on the Pi |
| **US-22** Settings shell | `register_section`, `SettingsGroup`, `InfoRow`, `ButtonRow`, `navigator.show("settings", section=...)` | `grep -n "def register_section" calpi/widgets/settings/shell.py` |
| **US-23** Wi-Fi scan and connect | The Network section (link target), `wifi.run_nmcli`/parsers for SSID/signal, `app.network` usage | Settings → Network works on the Pi |

### Soft dependencies

| Soft blocker | Why | If not done |
|---|---|---|
| **US-24** `ConnectionStatusGroup`, `internet_status` | Richer network block | Show SSID + connected/not connected from `nmcli device` only |
| **US-38** message catalogue | Plain-language texts + fixes | Create `messages.py` with the D2 interface and short texts |
| **US-17** `app.clock_trust`, `app.sync.offline` | Clock/offline lines | Omit those lines |
| **US-27** `formatting.relative_datetime`, `next_run_in_seconds` | Time texts | Implement locally in formatting if missing (same names) |
| **US-30** `app.dimming.state` | "Overnight mode active" line | Omit |

### External blockers
- `vcgencmd` access for `kiosk` (needs group `video`, which it has — verify: `ssh calpi 'sudo -u kiosk vcgencmd get_throttled'`).

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Too much information for non-technical users | Keep the top verdict + 3 short blocks visible; put technical detail (error codes, IPs, build) in dimmed small text or a "Details" sub-page. |
| `vcgencmd` missing on some OS releases | It's in `raspi-utils`/`libraspberrypi-bin`; if absent, skip the power block (log once). |

---

## Scope

### In scope
- **Status** settings section (`"status"`, order 70) + header indicator tap → opens it.
- Overall verdict (pure function, prioritized).
- Blocks: **Network**, **Calendar updates** (last/next, per account, per calendar with problems), **Device** (clock, power/temperature warnings, storage, safe mode/startup notices, version), **Recent updates** (last 5 runs, compact).
- "Fix" buttons linking to the relevant settings section (Network, Accounts) where obvious.
- Live refresh while visible (5 s + callbacks).
- Minimal `messages.py` if US-38 not done.

### Out of scope
- Full error-handling UX elsewhere (banners, toasts) — US-38.
- Log viewer (journal on screen) — not needed; too technical.
- Remote diagnostics.

---

## Acceptance criteria

1. Tapping the **sync status text** in the calendar header opens Settings → **Status**. Also reachable from the Settings sidebar ("Status").
2. At the top: a **verdict** line with an icon-less colour cue (green/amber/red left bar) and one sentence, chosen by priority (D1), e.g. "Everything is working · Updated 14:05", "calpi is offline · Showing events from 14:05", "iCloud needs you to sign in again", "The power supply is too weak — use the official Raspberry Pi power supply".
3. **Network block**: connection type + SSID + signal (or Ethernet), IP address, internet status ("Working"/"No internet"), and a "Network settings" button.
4. **Calendar updates block**: "Last updated" (relative), "Next update" (from US-27 helper or engine), and per account: name + state in plain language ("Up to date", "Sign-in problem", "Couldn't reach iCloud since 09:12 (3 tries)"). Calendars are listed **only if they have a problem** (inherited account errors collapse into the account line). A "Update now" button (US-19 `RefreshButton` if present) and "Accounts" button when an account has an auth problem.
5. **Device block**: "Clock: set automatically" / "Clock not set yet — needs internet"; power: from `get_throttled` bits (D3) — "Power: OK" or the plain warning ("Under-voltage detected since boot" etc.); temperature (`vcgencmd measure_temp`) with a warning above 80 °C; storage free on `/` (warn < 500 MB); **safe mode** and **startup notices** (db reset, credentials unreadable) with plain explanations; overnight mode state (if US-30); app version + build (small, dimmed).
6. **Recent updates**: last 5 runs: time (relative), reason (plain: "scheduled", "manual", "network came back", "account added"), result ("OK", "offline", "sign-in problem"), duration.
7. All values refresh **while the section is visible**: on `status_callbacks`, engine state changes, network changes, and a 5 s timer for time-relative texts and device probes (device probes — `vcgencmd`, `df` — run in a worker, at most every 30 s). Nothing refreshes while hidden.
8. The verdict function and the throttled-bit decoding are pure and unit-tested; message texts come from `messages.py` (no user-facing strings hard-coded in the widget except labels/headings).
9. Screen is readable at a glance: verdict ≥ 40 px, block headings ≥ 28 px, technical details ≤ 20 px dimmed.
10. Meets target-size rules; no blocking calls on the main thread.

---

## Design decisions (already made)

- **D1. Verdict priority** (`calpi/data/status_summary.py`, pure): highest wins —
  1. `power_problem` (under-voltage now) → red
  2. `safe_mode` → red
  3. `credentials_unreadable` or any account `AUTH_FAILED` → red ("needs you to sign in again")
  4. `no_accounts` → amber ("No calendar account yet — add one in Settings → Accounts")
  5. `offline` (network down / no internet) → amber, with "Showing events from HH:MM"
  6. `clock_unsynced` → amber
  7. any account failing (non-auth) ≥ 3 consecutive → amber ("Couldn't reach iCloud since HH:MM")
  8. `stale` (> 6 h since success) → amber
  9. `db_reset` notice this boot → amber ("Calendar data was reset and is downloading again")
  10. otherwise green "Everything is working · Updated HH:MM"
  Input is a plain dataclass `StatusInputs` assembled on the main thread from app objects; output `Verdict(level, text, fix_section | None)`.
- **D2. `messages.py` interface** (shared with US-38): `describe(code: str, *, provider: str = "iCloud", context: str = "status") -> Message(title: str, detail: str | None, fix_label: str | None, fix_section: str | None)`. Codes include `ErrorCode` values plus device/notice codes: `POWER_UNDERVOLTAGE`, `POWER_THROTTLED_PAST`, `TEMP_HIGH`, `DISK_LOW`, `SAFE_MODE`, `DB_RESET`, `CREDENTIALS_UNREADABLE`, `CLOCK_UNSYNCED`, `NO_ACCOUNTS`.
- **D3. `get_throttled` decoding** (pure): bit 0 under-voltage now, 1 freq capped now, 2 throttled now, 3 soft temp limit now, 16 under-voltage occurred, 17 capped occurred, 18 throttled occurred, 19 soft temp limit occurred. Map "now" bits to red/amber warnings; "occurred" bits to amber "since boot" notes.
- **D4. Section, not a separate screen**: lives in Settings (consistent back behaviour, shares the shell). The header tap uses `navigator.show("settings", section="status")`.

---

## Implementation plan

### Step 1 — Pure pieces
- `calpi/data/status_summary.py`: `StatusInputs`, `Verdict`, `summarize(inputs, now) -> Verdict`, `account_line(account_status, calendars, now) -> str`, `run_line(run) -> str`.
- `calpi/system/device_info.py` (no gi): `decode_throttled(hex_str) -> dict`, `parse_measure_temp("temp=48.3'C") -> float`, `disk_free_bytes(path="/") -> int` (`shutil.disk_usage`), `collect() -> DeviceInfo` (runs `vcgencmd` with timeouts; tolerant of absence).
- `calpi/data/messages.py`: if absent, create per D2 with short texts for all codes listed; if present (US-38), add any missing device codes.

Tests: `tests/test_status_summary.py` (each priority level; combinations pick the highest), `tests/test_device_info.py` (throttled `0x0`, `0x50005`, `0x80000`; temp parsing; missing vcgencmd → graceful).

### Step 2 — Section widget (`calpi/widgets/settings/status.py`)
```
StatusSection
├─ VerdictBanner (colour bar + text + optional [Fix] button → navigator.show("settings", section=verdict.fix_section))
├─ SettingsGroup "Network"      (ConnectionStatusGroup from US-24 if available, else simple rows) + [Network settings]
├─ SettingsGroup "Calendar updates"  Last updated / Next update / per-account rows / problem calendars + [Update now] [Accounts]
├─ SettingsGroup "Device"       Clock / Power / Temperature / Storage / Notices / Overnight / Version (small)
└─ SettingsGroup "Recent updates"  5 compact rows
```
`on_show`: subscribe (status_callbacks, sync state/result, network callbacks, clock_trust), start 5 s timer, trigger device probe; `on_hide`: unsubscribe/stop. `_render()` builds `StatusInputs` and updates rows with `set_text_if_changed`; account/calendar/run rows rebuilt only when their text tuple changes.

### Step 3 — Header tap
Make `SyncIndicator` (US-16) clickable: wrap it in a flat `Gtk.Button` (≥ 72 px tall, css `sync-status-button`) → `navigator.show("settings", section="status")`. Keep its text styling.

### Step 4 — Register
`SectionSpec("status", "Status", 70, StatusSection)`.

### Step 5 — Tests (GTK, Broadway)
With fake app state: offline → amber verdict text; auth failure → red with Fix → Accounts; no accounts → amber; all good → green. Check rows don't rebuild when nothing changed (count child widgets before/after two refreshes).

### Step 6 — Pi check
Screenshot the Status section in normal state. Then: take network away (US-17 method) → verdict "offline"; check throttling line (`vcgencmd get_throttled` should be `0x0` with a good PSU — if the owner has a weak USB supply, you'll see the warning, which is a real finding). Tap the header indicator → opens Status.

---

## Files

| File | Change |
|---|---|
| `calpi/data/status_summary.py` | New |
| `calpi/system/device_info.py` | New |
| `calpi/data/messages.py` | New minimal (or extended) |
| `calpi/widgets/settings/status.py` | New |
| `calpi/widgets/settings/__init__.py` | Import `status` |
| `calpi/widgets/sync_indicator.py` | Clickable |
| `tests/test_status_summary.py`, `tests/test_device_info.py` | New |

---

## Pitfalls

- **Jargon** ("PROPFIND 401", "NM state 60") in the main text — codes only in small technical detail.
- **Running `vcgencmd`/`df` on the main thread or every second.**
- **Duplicating message texts** in the widget — use `messages.py`.
- **Refreshing while hidden.**
- **Listing every calendar** even when fine — only problems.

---

## Definition of done

- [ ] All acceptance criteria met; tests pass.
- [ ] Normal and offline states verified on the Pi with screenshots; header tap works.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `status_summary.summarize(inputs, now) -> Verdict` | US-38 (header error state uses the same verdict) |
| `messages.describe(code, provider, context)` interface (D2) | US-38 (owner of the catalogue), US-25 |
| `device_info.collect()`, `decode_throttled` | US-36, US-37 (soak monitoring) |
| Status section id `"status"`; header indicator opens it | US-38 |
