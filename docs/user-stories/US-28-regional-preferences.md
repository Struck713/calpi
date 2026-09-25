# US-28 — Regional preferences

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P0 |
| **Blocked by** | US-06 Month grid, US-22 Settings shell |
| **Blocks** | US-32 First-time setup wizard |
| **Phase** | 3. Setup and Settings |

## Story

> As a user, I want to set the time zone, the first day of the week, and 12- or 24-hour time.

## Context

Three preferences affect every screen:
- **The time zone** decides what "today" is, when midnight happens (US-10), which day a timed event falls on (US-07), where the sync window's edges are (US-15), and how floating times are read (US-15).
- **The first day of the week** decides the grid layout (US-06).
- **12 or 24-hour time** decides every time label (US-07, US-09, and later views).

The plumbing for all three already exists, written so that this story only has to **connect it to settings and add a UI**:
- `timeutil.set_display_tz(name)` + `app.clock.notify_tz_changed()` (US-06, US-10), with the sync engine's zone trigger forcing a sync (US-16).
- `MonthView.set_week_start(n)` (US-06).
- `formatting.set_time_format("12h" | "24h")` (US-07).

This story adds the settings keys, applies them at startup and on change, adds a **Preferences** section with a touch-friendly **time zone picker** (region, then city, with search), and **sets the system time zone** too (through systemd-timedated), so the logs and the OS agree with the display.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-06** Month grid | `timeutil.set_display_tz`, `display_tz`, `system_tz_name`; `MonthView.set_week_start`; `monthmath.WEEKDAY_NAMES` | `grep -n "def set_display_tz\|def set_week_start" calpi/data/timeutil.py calpi/widgets/month_view.py` |
| **US-22** Settings shell | `register_section`, `ChoiceRow`, `ListPickerRow`/`ListPickerPage` (with search), `SectionContext.mode`, `app.toast` | `grep -n "class ListPickerPage" calpi/widgets/settings/rows.py` |

### Soft dependencies

| Soft blocker | Why | If it isn't done |
|---|---|---|
| **US-07** `formatting.set_time_format`, `MonthView.reload` | The 12/24h setting and reloading after a zone change | On the critical path, so it's done. |
| **US-10** `app.clock.notify_tz_changed()` | Re-evaluating "today" and midnight | If it's missing, call `month_view.refresh_today()` + `reload(force=True)` directly, and note it. |
| **US-16** zone trigger (forced sync) | Floating times and window edges | It fires through `clock.subscribe_tz_changed`. If there's no clock, call `app.sync.request_sync("tz-changed", force=True)`. |
| **US-09** `on_data_changed` | The day detail reload | Call `month_view.reload` only. |
| **US-01** provisioning | The polkit rule for timedated (step 1) | Needed to set the **system** zone. Without it, the display zone still works (D2). |

### External blockers
- **tzdata** on the Pi and in the devcontainer (`/usr/share/zoneinfo`). Check: `ls /usr/share/zoneinfo/Europe/Paris`.
- **systemd-timedated** on the Pi (always present), and the polkit rule (step 1).

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| `zoneinfo.available_timezones()` returns about 600 names, including `posix/…`, `right/…`, `Etc/GMT+5`, and legacy aliases | Filter them (D3). |
| It's slow on the Pi (it walks the tzdata tree) | Run it once in `run_in_thread` on first use, and cache the result. |
| `timedatectl set-timezone` over SSH needs a password | That's polkit for the non-active SSH session. Our rule is per user (`kiosk`). Test from the app. |
| Changing the zone changes "today" and the displayed month | Expected. `notify_tz_changed` → US-10's day-change logic moves the grid if the user was on the current month. |

---

## Scope

### In scope
- Settings keys `K_TIMEZONE` (str | None), `K_WEEK_START` (int), `K_TIME_FORMAT` (str), if not registered already (US-16 may have registered `K_TIMEZONE`).
- Applying them at startup (before the first render) and on change.
- The **Preferences** section (`"preferences"`, order 60): time zone (region → city picker with search), first day of week (Monday / Sunday / Saturday), and time format (24-hour / 12-hour, with an example).
- Setting the system zone through D-Bus `org.freedesktop.timedate1.SetTimezone`, plus the polkit rule.
- A reusable `PreferencesPanel` for the wizard.

### Out of scope
- Language and translation, date formats (like DD/MM), and locales. English only (US-06 D3).
- Automatic time zone detection by IP (a privacy concern and a network dependency; not requested).
- Setting the clock by hand (NTP handles it).

---

## Acceptance criteria

1. **Keys**: `timezone` (default `None` = follow the system zone; otherwise a valid IANA name. The validator checks that `ZoneInfo(name)` loads), `week_start` (default `0` = Monday; allowed `0`, `5` Saturday, `6` Sunday), `time_format` (default `"24h"`; allowed `"24h"`, `"12h"`).
2. **At startup**, before `MonthView` is first rendered: `timeutil.set_display_tz(settings.get(K_TIMEZONE))`, `formatting.set_time_format(...)`, and `MonthView(week_start=...)`. The first frame already uses the saved preferences (no visible flip).
3. **Time zone picker**: "Time zone: Europe/Paris (UTC+02:00)" → a full-page **region** list (Africa, America, Antarctica, Arctic, Asia, Atlantic, Australia, Europe, Indian, Pacific, plus "UTC") → a **city** list for that region (for example "Paris", "Argentina / Buenos Aires"), each with its current UTC offset, sorted by name, plus a search field (OSK) that filters **all** cities across every region. Rows ≥ 80 px. The current zone is ticked.
4. **Choosing a zone**: saves `K_TIMEZONE`, applies the display zone immediately (`set_display_tz` → `clock.notify_tz_changed()` → today, midnight, and the grid re-evaluated → a forced sync requested), and **asynchronously** sets the system zone through timedated. The grid shows the right "today" for the new zone within 1 s. The toast "Time zone set to Paris".
5. If setting the **system** zone fails (for example because of permissions), the display zone still changes, a WARNING is logged, and the About section (US-22) shows the system zone and the display zone separately when they differ.
6. **First day of week**: a segmented `ChoiceRow` Monday | Sunday | Saturday. Changing it calls `month_view.set_week_start(n)` at once (no widget rebuild: US-06 acceptance criterion 7), and the week view (US-39) later follows the same key.
7. **Time format**: a segmented `ChoiceRow` "24-hour (14:30)" | "12-hour (2:30 PM)". Changing it calls `formatting.set_time_format` + `app.on_data_changed()`, so every visible time label updates within 200 ms.
8. `PreferencesPanel(ctx)` renders the same three controls for the wizard (`ctx.mode == "wizard"`, no toasts).
9. Zone list: canonical `Region/City` names only (D3), built once in a worker thread, cached, with offsets computed for "now".
10. **Polkit**: `setup-pi.sh` installs a rule that allows `kiosk` to run `org.freedesktop.timedate1.set-timezone` (only that action).
11. Unit tests: zone filtering and grouping, offset formatting (`UTC+05:30`, `UTC−03:00`, `UTC`), and settings validators.

---

## Design decisions (already made)

- **D1. The setting is the source of truth for the display.** `K_TIMEZONE = None` means "use the system zone" (a fresh device: the zone set with Imager). Once the user picks a zone, it's stored explicitly.
- **D2. Also set the system zone** (so journal timestamps and the OS match) through D-Bus: `org.freedesktop.timedate1` `/org/freedesktop/timedate1` `SetTimezone(s timezone, b interactive=false)`, async. The failure is non-fatal (acceptance criterion 5).
- **D3. Zone list filtering** (`calpi/system/timezone.py`, pure part): keep names with at least one `/`, whose first part is in `{"Africa", "America", "Antarctica", "Arctic", "Asia", "Atlantic", "Australia", "Europe", "Indian", "Pacific"}`. Drop `posix/`, `right/`, `Etc/`, `SystemV/`, `US/`, `Canada/`, `Brazil/`, `Chile/`, `Mexico/` (legacy aliases), and add `"UTC"` as its own entry. City display: the part after the region, with `_` → space and `/` → " / " (`America/Argentina/Buenos_Aires` → "Argentina / Buenos Aires").
- **D4. Offsets** are computed with `datetime.now(ZoneInfo(z)).utcoffset()` when the list is built (the current offset, so DST is reflected), formatted `UTC+HH:MM` with a real minus sign `−` for negative offsets. It's display only.
- **D5. Polkit rule** `/etc/polkit-1/rules.d/51-calpi-timedate.rules`:
  ```js
  polkit.addRule(function(action, subject) {
      if (subject.user === "kiosk" && action.id === "org.freedesktop.timedate1.set-timezone") {
          return polkit.Result.YES;
      }
  });
  ```

---

## Implementation plan

### Step 1 — Provisioning
Add the D5 rule to `setup-pi.sh` (the same pattern as US-23's section). Run it. Check: `ssh calpi 'sudo -u kiosk busctl call org.freedesktop.timedate1 /org/freedesktop/timedate1 org.freedesktop.timedate1 SetTimezone sb "$(timedatectl show -p Timezone --value)" false && echo OK'`. That sets the zone to its **current** value, which is harmless. Note: this SSH test runs in a non-active session, which is exactly why the rule is per user.

### Step 2 — Keys and startup application
In `settings_store.py` (only register the ones that aren't there yet):
```python
K_TIMEZONE = "timezone";       register(Key(K_TIMEZONE, (str, type(None)), None, _valid_tz))
K_WEEK_START = "week_start";   register(Key(K_WEEK_START, int, 0, lambda v: v in (0, 5, 6)))
K_TIME_FORMAT = "time_format"; register(Key(K_TIME_FORMAT, str, "24h", lambda v: v in ("24h", "12h")))
```
`_valid_tz(v)`: `v is None`, or `ZoneInfo(v)` doesn't raise.

In `CalpiApp._on_activate`, **before** creating the window:
```python
timeutil.set_display_tz(self.settings.get(K_TIMEZONE))
formatting.set_time_format(self.settings.get(K_TIME_FORMAT))
week_start = self.settings.get(K_WEEK_START)
```
and pass `week_start` into `MonthView(...)`.

Subscriptions (after the window exists):
```python
self.settings.subscribe(K_TIMEZONE, lambda k, v: self._apply_tz(v))
self.settings.subscribe(K_WEEK_START, lambda k, v: self.window.month_view.set_week_start(v))
self.settings.subscribe(K_TIME_FORMAT, lambda k, v: (formatting.set_time_format(v), self.on_data_changed()))

def _apply_tz(self, name):
    timeutil.set_display_tz(name)
    if hasattr(self, "clock"): self.clock.notify_tz_changed()     # US-10 → day change / grid / US-16 forced sync
    else: self.window.month_view.refresh_today(); self.on_data_changed()
    if name: system_timezone.set_async(name, on_done=..., on_error=lambda e: log.warning("system tz not set: %s", e))
```

### Step 3 — `calpi/system/timezone.py`
Pure part (no gi): `filter_zones(names) -> list[str]`, `group_by_region(zones) -> dict[str, list[str]]`, `city_label(zone) -> str`, `offset_label(zone, now_utc) -> str`, `load_zone_index() -> ZoneIndex` (calls `zoneinfo.available_timezones()`, filters, groups, computes offsets). Heavy-ish, so always call it through `run_in_thread`, and cache it in a module global after the first load.

The Gio part (`set_async(name, on_done, on_error)`): `Gio.bus_get(SYSTEM)` → `call("org.freedesktop.timedate1", "/org/freedesktop/timedate1", "org.freedesktop.timedate1", "SetTimezone", GLib.Variant("(sb)", (name, False)), None, NONE, 10000, None, cb)`.

### Step 4 — The Preferences section (`calpi/widgets/settings/preferences.py`)
```python
class PreferencesPanel(Gtk.Box):
    def __init__(self, ctx):
        # Time zone: ListPickerRow("Time zone", current_label, self._open_regions)
        # First day of week: ChoiceRow("First day of the week", [(0,"Monday"),(6,"Sunday"),(5,"Saturday")], key=K_WEEK_START)
        # Time format: ChoiceRow("Time format", [("24h","24-hour (14:30)"),("12h","12-hour (2:30 PM)")], key=K_TIME_FORMAT)
    def _open_regions(self):
        # ensure the index is loaded (run_in_thread + "Loading…" row), then push region list page with a search entry
    def _open_city(self, region): ...
    def _pick(self, zone):
        self.ctx.app.settings.set(K_TIMEZONE, zone); self.ctx.pop_page(); self.ctx.pop_page()
        if self.ctx.mode == "settings": self.ctx.app.toast(f"Time zone set to {city_label(zone)}")

class PreferencesSection:
    def __init__(self, ctx): self.widget = PreferencesPanel(ctx)
```
The search in the region page filters **every** zone (the cities from all regions, labelled "City — Region"), so typing "Paris" finds it straight away. Use `ListPickerPage(search=True)` with a filter function over the prebuilt rows (US-22).

The current-zone label: `f"{city_label(z)} ({offset_label(z, now)})"`, where `z = settings.get(K_TIMEZONE) or timeutil.system_tz_name()`, with "(system)" appended when the setting is `None`.

Register it: `SectionSpec("preferences", "Preferences", 60, PreferencesSection)`.

### Step 5 — About: show a mismatch (small change to US-22's About)
If `settings.get(K_TIMEZONE)` is set and differs from `timeutil.system_tz_name()`: an `InfoRow("System time zone", ...)` plus a dimmed note. Otherwise one `InfoRow("Time zone", ...)`.

### Step 6 — Tests
- `tests/test_timezone.py`: filtering (samples including `posix/Europe/Paris`, `Etc/GMT+5`, `US/Eastern`, `America/Argentina/Buenos_Aires`, `UTC`), grouping, `city_label`, `offset_label` (India `+05:30`, `America/St_Johns` `−02:30`/`−03:30` depending on the date: pass a fixed `now`, and UTC).
- Settings validators (a bad zone name rejected, `week_start=3` rejected).
- Startup application: with a settings file holding `America/New_York` + `12h` + Sunday, the smoke run logs `month_view: showing ...` with a Sunday start (log the week start), and a DEBUG line with the zone.
- The zone change end to end (GTK/Broadway): `CALPI_FAKE_NOW=2026-09-30T23:30:00+00:00` with display zone `UTC` → pick `Europe/Paris` (a test hook) → today becomes 1 October (01:30 in Paris) → the grid shows October.

### Step 7 — Pi check
Change the zone to one where today is a different date than the current zone (for example from Europe to Pacific/Auckland in the evening) → the grid moves "today", and `ssh calpi timedatectl` shows the new system zone. Set it back to the owner's real zone. Switch Sunday/Monday and 12/24h → screenshots. `CALPI_CHECK_TARGETS=1` on the picker pages.

---

## Files

| File | Change |
|---|---|
| `.claude/skills/pi-kiosk-setup/setup-pi.sh` | The timedate polkit rule |
| `calpi/data/settings_store.py` | Keys |
| `calpi/system/timezone.py` | New |
| `calpi/widgets/settings/preferences.py` | New: `PreferencesPanel`, `PreferencesSection` |
| `calpi/widgets/settings/about.py` | Zone mismatch display |
| `calpi/app.py` | Startup application and subscriptions |
| `tests/test_timezone.py`, settings tests | New cases |

---

## Pitfalls

- **Applying preferences after the first render** (a visible flip). Apply them before building the window.
- **A blocking `available_timezones()` on the main thread.**
- **Fixed offsets instead of zone names.** Always store the IANA name.
- **Forgetting the forced sync** after a zone change: floating events would sit on the wrong times until the next change.
- **Leaving the Pi in a test zone.** Set it back.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] Zone, week-start, and time-format changes checked on the Pi. The system zone updated. Put back to the owner's settings.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `PreferencesPanel(ctx)` | US-32 (wizard preferences step) |
| `K_TIMEZONE`, `K_WEEK_START`, `K_TIME_FORMAT` | US-16 (worker zone), US-39 (week view), US-40, US-41 |
| `calpi.system.timezone.load_zone_index`, `city_label`, `offset_label` | US-41 (weather location display, optional) |
| The Preferences section id `"preferences"` (order 60) | US-31, US-38 |
