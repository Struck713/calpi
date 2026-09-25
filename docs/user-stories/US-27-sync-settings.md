# US-27 — Sync settings

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P0 |
| **Blocked by** | US-16 Scheduled background sync, US-22 Settings shell |
| **Blocks** | US-32 First-time setup wizard |
| **Phase** | 3. Setup and Settings |

## Story

> As a user, I want to choose how often events refresh.

## Context

US-16 registered the `sync_interval_minutes` setting (default 15) and reschedules whenever it changes. This story gives it a **UI**: a **Sync** section in Settings with the refresh interval, a clear indication of when the last and next syncs happen, and (if US-19 exists) a **Sync now** button. The same interval chooser is reused as the "refresh timing" step of the setup wizard (US-32).

It's a small story, but it's P0 because the wizard depends on it, and it's the user-visible control over the "Always current" goal.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-16** Scheduled background sync | `K_SYNC_INTERVAL_MINUTES`, `SYNC_INTERVAL_CHOICES`, the engine rescheduling on change, `app.sync.last_success_wall`, `is_running`, state and result callbacks | `grep -n "SYNC_INTERVAL_CHOICES" calpi/data/settings_store.py`. On the Pi, changing the value in `settings.json` with a script + restart changes the cadence. |
| **US-22** Settings shell | `register_section`, `ChoiceRow`/`ListPickerRow`, `InfoRow`, `SectionContext.mode` | `grep -n "class ChoiceRow" calpi/widgets/settings/rows.py` |

### Soft dependencies
- **US-19** `RefreshButton` / `app.trigger_manual_refresh()`: the "Sync now" row. If it isn't there, leave out the row (don't build a second refresh mechanism).
- **US-17**: the engine's current retry state ("Retrying in 4 min (offline)"). Show it if `app.sync.offline` exists.
- **US-18** `app.sync_status`: per-account last-success times. Optional here (US-31 shows the details).

### External blockers
None.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Seven interval choices are too many for a segmented `ChoiceRow` (the max is 5) | Use a `ListPickerRow` → `ListPickerPage` with the 7 choices (D1). |
| "Next sync" needs the engine's timer deadline | Add `SyncEngine.next_run_mono` (a monotonic deadline set in `_arm`) and a helper `next_run_in_seconds()`. It's a small engine addition, owned by this story. |

---

## Scope

### In scope
- The **Sync** section (`"sync"`, order 40): the interval picker, "Last updated", "Next update", "Sync now" (if US-19), and a short explanation.
- A reusable `IntervalChooser` widget for the wizard.
- `SyncEngine.next_run_in_seconds()`.

### Out of scope
- The window sizes (`sync_window_months_*`): hidden settings, no UI.
- Per-calendar or per-account intervals.
- Detailed status (US-31).

---

## Acceptance criteria

1. Settings → **Sync** shows:
   - **Refresh every**: the current value ("15 minutes"). Tapping opens a full-page list: 5 minutes, 10 minutes, 15 minutes (recommended), 30 minutes, 1 hour, 2 hours, 4 hours. The current choice is ticked.
   - **Last updated**: "Today 14:05" / "Yesterday 22:15" / "Never".
   - **Next update**: "in about 12 minutes", "Updating now…", "Retrying in 4 minutes (offline)" (if US-17), or "Paused (safe mode)" (if US-12's safe mode).
   - **Sync now** (if US-19): the `RefreshButton` in a `ButtonRow`.
   - An explanation: "calpi checks your calendars in the background. More frequent updates use a little more network data."
2. Picking an interval saves it at once (`settings.set`). The engine reschedules (US-16 acceptance criterion 4). The "Next update" line reflects the new schedule within 1 s. The toast "Calendars will refresh every 30 minutes".
3. The "Last" and "Next" lines refresh while the section is visible (every 30 s and on engine callbacks), and don't refresh at all when it's hidden.
4. `IntervalChooser(ctx, on_changed=None)` renders the same picker for the wizard, and writes the same setting.
5. The choices come from `SYNC_INTERVAL_CHOICES` (the single source), with labels from a pure `interval_label(minutes)` helper (tested).
6. All controls meet the size rules (`CALPI_CHECK_TARGETS=1`).

---

## Design decisions (already made)

- **D1. `ListPickerRow` + `ListPickerPage`** (US-22 D4) for the 7 choices. The 15-minute option is labelled "(recommended)".
- **D2. "Next update"** = `max(0, next_run_mono - time.monotonic())`, formatted as "in about N minutes" (rounded up), "in less than a minute", or "Updating now…" while running. It's computed on the main thread from engine state (no I/O).
- **D3. Relative dates** ("Today", "Yesterday", or the weekday for the last 6 days, otherwise the date) go in `formatting.relative_datetime(dt, now)` (pure and tested). US-31 and US-38 reuse it.

---

## Implementation plan

### Step 1 — Pure helpers
`calpi/data/formatting.py`:
```python
def interval_label(minutes: int) -> str:      # 5 -> "5 minutes", 60 -> "1 hour", 120 -> "2 hours"
def relative_datetime(dt: datetime | None, now: datetime) -> str:   # "Never" | "Today 14:05" | "Yesterday 22:15" | "Monday 09:10" | "12 Sep 09:10"
def next_update_text(seconds: float | None, running: bool, offline: bool, safe_mode: bool) -> str: ...
```
Tests for each, including 12h and 24h formats (through `formatting.set_time_format`), and the day boundaries in the display zone.

### Step 2 — Engine addition
In `SyncEngine._arm(seconds)`: `self.next_run_mono = time.monotonic() + seconds`. When a run starts: `self.next_run_mono = None`. `def next_run_in_seconds(self): return None if self.next_run_mono is None else max(0.0, self.next_run_mono - time.monotonic())`. Test it with the fake spawner and injectable timers (extend US-16's tests).

### Step 3 — `IntervalChooser` and the Sync section (`calpi/widgets/settings/sync.py`)
```python
class IntervalChooser(ListPickerRow):
    def __init__(self, ctx, on_changed=None):
        self.ctx = ctx; self.on_changed = on_changed
        super().__init__("Refresh every", interval_label(ctx.app.settings.get(K_SYNC_INTERVAL_MINUTES)), self._open)
        self._h = ctx.app.settings.subscribe(K_SYNC_INTERVAL_MINUTES, lambda k, v: self.set_value_label(interval_label(v)))
    def _open(self):
        items = [(m, interval_label(m) + (" (recommended)" if m == 15 else "")) for m in SYNC_INTERVAL_CHOICES]
        self.ctx.push_page(ListPickerPage("Refresh every", items, self._pick,
                                          current=self.ctx.app.settings.get(K_SYNC_INTERVAL_MINUTES)), "Refresh every")
    def _pick(self, minutes):
        self.ctx.app.settings.set(K_SYNC_INTERVAL_MINUTES, minutes)
        self.ctx.pop_page()
        if self.ctx.mode == "settings": self.ctx.app.toast(f"Calendars will refresh every {interval_label(minutes)}")
        if self.on_changed: self.on_changed(minutes)
```
The Sync section: `SettingsGroup("Updates")` containing `IntervalChooser`, `InfoRow("Last updated")`, `InfoRow("Next update")`, and the Sync now `ButtonRow` (if US-19). Then the explanation label. `on_show` starts a 30 s timer plus the engine callback subscriptions. `on_hide` stops the timer. `_refresh()` uses `set_text_if_changed`.

Register it: `SectionSpec("sync", "Sync", 40, SyncSection)`.

### Step 4 — Tests
- Pure helpers (step 1). Engine `next_run_in_seconds` (step 2).
- GTK (Broadway): pick 30 minutes → the setting is 30, the engine is rearmed (log), and the toast is shown.

### Step 5 — Pi check
Set 5 minutes → watch `scripts/pi logs -f | grep sync:`: the next run about 5 minutes after the last one. The section's "Next update" counts down. Set it back to 15. Screenshot.

---

## Files

| File | Change |
|---|---|
| `calpi/data/formatting.py` | `interval_label`, `relative_datetime`, `next_update_text` |
| `calpi/sync_engine.py` | `next_run_mono`, `next_run_in_seconds()` |
| `calpi/widgets/settings/sync.py` | New: `IntervalChooser`, `SyncSection` |
| `calpi/widgets/settings/__init__.py` | Imports `sync` |
| `tests/test_formatting.py`, `tests/test_sync_engine.py` | New cases |

---

## Pitfalls

- **A second copy of the interval choices.** Import `SYNC_INTERVAL_CHOICES`.
- **Timers running while the section is hidden.**
- **Wall-clock arithmetic for "next update".** Use the monotonic deadline.
- **Toasts in wizard mode**: the wizard gives its own feedback.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] The cadence change checked on the Pi, and set back to 15 minutes.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `IntervalChooser(ctx, on_changed)` | US-32 (wizard refresh step) |
| `formatting.relative_datetime`, `interval_label`, `next_update_text` | US-25 (account status), US-31, US-38 |
| `SyncEngine.next_run_in_seconds()` | US-31 |
| The Sync section id `"sync"` (order 40) | US-31, US-38 links |
