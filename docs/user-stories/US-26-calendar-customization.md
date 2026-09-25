# US-26 — Calendar customization

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P1 |
| **Blocked by** | US-07 Events in the grid, US-25 Account management |
| **Blocks** | — |
| **Phase** | 3. Setup and Settings (P1) |

## Story

> As a user, I want to show, hide, rename and recolor individual calendars.

## Context

A household calendar often combines calendars with unhelpful names ("Calendar", "Home", "john@…") and colours that clash or are hard to read on a dark screen. This story adds a **Calendars** section to Settings where each calendar can be:
- **shown or hidden** (hidden calendars still sync, so un-hiding is instant),
- **renamed** (a display name only; iCloud isn't changed),
- **recoloured** (from a curated palette that reads well on the dark background),
- **reset** to the name and colour that come from iCloud.

The storage already exists: US-04 put `user_name`, `user_color`, and `hidden` in the `calendars` table, sync never overwrites them (`upsert_calendar` only updates `remote_*`), `Calendar.name`/`.color` prefer the user values, and `EventStore.set_calendar_overrides()` changes them. US-07's `CalendarColors` regenerates CSS when colours change. This story is mostly **UI plus correct refreshing**.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-07** Events in the grid | `CalendarColors.update()` / `css_class()` (one shared instance), `MonthView.reload()`, `formatting.contrast_text`, `.bar.cal-N` styles; plus US-04's `set_calendar_overrides`, `list_calendars` | `grep -n "def set_calendar_overrides" calpi/data/event_store.py`; `grep -n "class CalendarColors" calpi/widgets/calendar_colors.py` |
| **US-25** Account management | Real calendars in the store (added via the UI), the Accounts section to link from, `apply_calendar_selection` (which already sets `hidden` at sign-in) | Settings → Accounts lists the owner's account on the Pi; `sqlite3 … "select id, remote_name, hidden from calendars"` shows rows |

(US-25 brings US-21's keyboard for renaming and US-22's section framework.)

### Soft dependencies
- **US-09** `on_data_changed()` reloads the day detail, too.
- **US-20** ICS calendars have no remote colour — they show the default until recoloured; nothing special needed.

### External blockers
None.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Colour changes don't show until restart | `CalendarColors.update()` must be called with the new list and `MonthView.reload(force=True)` — `reload()`'s key includes `revision()`, and `set_calendar_overrides` bumps it (US-04). Check both. |
| Sample calendars (dev) show up too | That's fine and useful for testing; they're customizable like any other. |
| Name conflicts (two calendars both called "Family") | Allowed — names are display-only. Don't block. |

---

## Scope

### In scope
- **Calendars** settings section (`"calendars"`, order 30): all calendars grouped by account (and "Sample" in dev), each row: colour dot, display name, original name (if renamed), visibility switch.
- Per-calendar edit page: rename (OSK `text`), colour palette (12 swatches), "Reset to iCloud name and colour", visibility.
- Immediate apply + refresh of grid/day detail and generated CSS.
- Palette definition with contrast-checked colours.

### Out of scope
- Reordering calendars (sort order) — possible later; not requested.
- Changing anything on the server.
- Custom colour entry (hex) — the palette is enough and avoids unreadable choices.

---

## Acceptance criteria

1. **Calendars section** lists every calendar, grouped under its account's display name (ICS/CalDAV accounts too if US-20). Each row: colour dot (≥ 28 px) in its current colour, display name, dimmed original name when renamed ("iCloud: Home"), and a visibility switch (the `SwitchRow` style from US-22; tapping the switch toggles visibility; tapping elsewhere on the row opens the edit page).
2. Toggling visibility applies **immediately**: the grid (and day detail, if open later) shows/hides that calendar's events within 200 ms on the Pi; no sync is triggered (hidden calendars keep syncing).
3. **Edit page**: title = display name; a name field (OSK purpose `text`, done label "Save") with Save button; a palette of **12 colour swatches** (each ≥ 88 × 88, currently selected one marked ✓); a "Reset to original" button (enabled only when a user name or colour is set); the visibility switch.
4. Renaming: empty or whitespace-only name → resets to the original name (`user_name=None`); names are trimmed and limited to 40 characters. Saved on Save / keyboard Done; toast "Renamed".
5. Recolouring: tapping a swatch applies immediately (grid colours update; `CalendarColors` regenerated); no Save needed.
6. Reset: sets `user_name=None`, `user_color=None` → the calendar shows its iCloud name and colour again.
7. Overrides **survive syncs**: after changing name/colour/visibility, a forced sync (`request_sync("manual", force=True)` via a test hook or CLI) leaves them unchanged (verified on the Pi).
8. Overrides survive app restarts and power cuts (they're in SQLite; US-04/US-12).
9. **Palette**: 12 colours, each with WCAG contrast ≥ 3:1 against the app background `#101418` (for the dot/stripe) and a text colour (black or white via `contrast_text`) reaching ≥ 4.5:1 on the colour itself (for all-day bars). A unit test checks both.
10. At least one "all calendars hidden" safeguard: hiding the last visible calendar shows a toast "All calendars are hidden — the calendar will be empty" (allowed, just informed).

---

## Design decisions (already made)

- **D1. Palette** (in `calpi/data/palette.py`, no gi) — starting values, adjust only if the contrast test fails:
  `#4f9dff` blue, `#3ecf8e` green, `#ffb020` amber, `#ff6b6b` red, `#c77dff` purple, `#2ec5d3` teal, `#ff8fb1` pink, `#a3d65c` lime, `#ff9248` orange, `#8fa3ff` periwinkle, `#e0c068` sand, `#b0bec5` grey.
- **D2. Writes from the UI process** via `store.set_calendar_overrides(...)` (US-04 D7 allows exactly this). Each write bumps `revision()`, so `MonthView.reload()` picks it up.
- **D3. Refresh sequence after any change:** `app.colors.update(store.list_calendars(include_hidden=True))` → `app.on_data_changed()` (reloads month view + day detail). Put this in one helper `app.on_calendars_changed()`.
- **D4. Section reuse in the wizard** (US-32 "calendar selection" step) — the wizard uses US-25's selection page at sign-in, not this section. No wizard mode needed here; `available` returns True only when at least one calendar exists.
- **D5. Sample calendars** are listed under "Sample calendars (development)" only when present.

---

## Implementation plan

### Step 1 — Palette + tests (`calpi/data/palette.py`)
```python
PALETTE = [("#4f9dff", "Blue"), ("#3ecf8e", "Green"), ...]
APP_BG = "#101418"
def contrast_ratio(a: str, b: str) -> float: ...   # WCAG 2.x using relative_luminance from formatting.py
```
`tests/test_palette.py`: every colour ≥ 3.0 vs `APP_BG`; `contrast_ratio(colour, contrast_text(colour)) ≥ 4.5`; all distinct; all lowercase `#rrggbb`.

### Step 2 — `app.on_calendars_changed()`
In `CalpiApp`: regenerate colours and call `on_data_changed()`. Make sure `CalendarColors` includes hidden calendars in its CSS (the settings list shows their dots too) — adjust US-07's call site if it passed `include_hidden=False` (colour classes for hidden calendars are harmless).

### Step 3 — Calendars section (`calpi/widgets/settings/calendars.py`)
```python
class CalendarsSection:
    def __init__(self, ctx): ...
    def on_show(self): self._render()
    def _render(self):
        cals = ctx.app.store.list_calendars(include_hidden=True)
        key = tuple((c.id, c.name, c.color, c.hidden) for c in cals)
        if key == self._key: return
        ... group by account_id → account display name (accounts.get_account), "Sample calendars (development)" for sample:
        ... row per calendar: dot (Gtk.Box css "cal-dot cal-N"), labels, Gtk.Switch
    def _toggle(self, cal, visible):
        store.set_calendar_overrides(cal.id, hidden=not visible)
        if not any(not c.hidden for c in store.list_calendars(include_hidden=True)):
            app.toast("All calendars are hidden — the calendar will be empty")
        app.on_calendars_changed()
```
Dot CSS: `.cal-dot { min-width: 28px; min-height: 28px; border-radius: 14px; }` + the generated `.bar.cal-N` background — add `.cal-dot.cal-N` rules to `CalendarColors` generation (extend US-07's generator with one more selector).

### Step 4 — Edit page
Pushed via `ctx.push_page(page, cal.name)`:
- `SettingsGroup("Name")`: `Gtk.Entry` prefilled with `cal.name`, `window.keyboard.attach(entry, "text", done_label="Save", on_done=save)`, Save button; small "Original: <remote_name>".
- `SettingsGroup("Colour")`: `Gtk.FlowBox` or a fixed `Gtk.Grid` (6 × 2) of swatch buttons (`Gtk.Button` with css `swatch` + a per-swatch class `swatch-N` defined statically in `style.css` from the palette — generate those 12 rules once at startup in a CSS provider, or hard-code them in `style.css` matching `palette.py`; **generate** to keep one source of truth). Selected swatch gets `✓` label and `.selected`.
- `SettingsGroup("Visibility")`: `SwitchRow`.
- `ButtonRow("Reset to original", ...)`.

Every action → `set_calendar_overrides(...)` → `app.on_calendars_changed()` → update the page's own title/labels.

Name rules: `name = entry.get_text().strip()[:40]`; `user_name=None` if empty **or** equal to `remote_name`.
Colour rule: `user_color=None` if equal to `remote_color`.

### Step 5 — Register
`register_section(SectionSpec("calendars", "Calendars", 30, CalendarsSection, available=lambda app: bool(app.store.list_calendars(include_hidden=True))))`. The shell re-evaluates `available` on show (US-22 `_rebuild_sidebar_if_needed`).

Also add a "Calendars" link row in each account's detail page (US-25) → `navigator.show("settings", section="calendars")`.

### Step 6 — Tests
- Palette tests (step 1).
- Store-level: override → forced sync (fake transport, US-15 fetch) → overrides intact (this may already be covered by US-04/US-15 tests — add an explicit end-to-end test here: `sync_account` twice with an override set in between).
- GTK (Broadway): toggle → `month_view.reload` observed (log line), rename flow, reset.

### Step 7 — Pi check
Rename "Home" → "Family", recolour to green, hide one calendar → screenshot of grid + settings. Force a sync (`scripts/pi ssh '... cli fetch --account <id> --force'` then restart, or wait for a scheduled run after a phone change) → overrides unchanged. Restart app → unchanged.

---

## Files

| File | Change |
|---|---|
| `calpi/data/palette.py` | New |
| `calpi/widgets/settings/calendars.py` | New |
| `calpi/widgets/settings/__init__.py` | Import `calendars` |
| `calpi/widgets/calendar_colors.py` | `.cal-dot.cal-N` rules; swatch CSS generation |
| `calpi/widgets/settings/accounts.py` | "Calendars" link on account detail |
| `calpi/app.py` | `on_calendars_changed()` |
| `tests/test_palette.py`, `tests/test_overrides_survive_sync.py` | New |

---

## Pitfalls

- **Forgetting to regenerate CSS** after a colour change — the grid keeps the old colour.
- **Custom free-form colours** — unreadable combinations; the palette is deliberate.
- **Writing overrides from a worker thread** — main thread only (tiny writes).
- **Treating hidden as "don't sync"** — hidden calendars still sync (instant un-hide).
- **Storing `user_name` equal to the remote name** — then later remote renames wouldn't show; store `None` instead.

---

## Definition of done

- [ ] All acceptance criteria met; tests pass (palette contrast, overrides survive sync).
- [ ] Verified on the Pi including a forced sync and a restart.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `app.on_calendars_changed()` | US-20, US-39, US-40 (anything showing calendar colours) |
| `palette.PALETTE`, `contrast_ratio` | US-20 (default ICS colour), US-39/40 |
| `.cal-dot.cal-N` CSS | US-31, US-39, US-40 |
