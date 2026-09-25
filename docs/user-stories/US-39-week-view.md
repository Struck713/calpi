# US-39 — Week view

| | |
|---|---|
| **Epic** | 5. Extras |
| **Priority** | P2 |
| **Blocked by** | US-07 Events in the grid |
| **Blocks** | — |
| **Phase** | 5. Extras (optional) |

## Story

> As a user, I want a week view that shows more detail than the month grid.

## Context

The month grid shows about 4 short lines per day. A **week view** gives each day a whole column of the 1920 px screen and shows **when** things happen: a time axis (for example 07:00–22:00) with events drawn as blocks at their start time and height proportional to their length, all-day and multi-day events in a strip at the top, and overlapping events side by side.

On the Pi 3B's software renderer, a naive version made of one GTK widget per event block, with absolute positioning and many labels, would be slow. **Draw the timeline with one `Gtk.DrawingArea` and cairo + Pango**, redrawn only when the data or the week changes. Taps are handled by hit-testing the block rectangles. That's the pattern the `gtk-kiosk-app` skill recommends for custom drawing.

This story also adds a small **view switcher** (Month | Week, plus Agenda once US-40 exists) and a `default_view` setting.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-07** Events in the grid | `EventStore.events_for_days` (with US-04's sort order), `layout.covered_days`, `formatting.short_time`/`long_time`, `CalendarColors` (and calendar colours via `Calendar.color`), `contrast_text`, `MonthView.reload` pattern, `app.on_data_changed` | `/usr/bin/python3 -m pytest tests/test_layout.py` passes; `grep -n "def covered_days" calpi/data/layout.py` |

### Soft dependencies
- **US-08** `go_relative` pattern + inactivity return — the week view gets its own prev/next/Today and must return to the **default view's current period** on inactivity.
- **US-09** day detail — tapping an event block or a day header opens `day` for that date.
- **US-10** `app.clock` — current-time line position updates each minute; day change moves "today".
- **US-11** `KeyRouter`/`on_key` — Left/Right = previous/next week; `m`/`w` switch views.
- **US-28** `K_WEEK_START`, `K_TIME_FORMAT` — follow them.
- **US-35** `attach_horizontal_swipe` — add swipe for weeks if available.
- **US-36** `perf.until_paint` — measure `week_render`.
- **US-22** settings — the `default_view` choice goes into the Preferences section (US-28) as an extra `ChoiceRow`.

### External blockers
None (Pi measurement needs US-03).

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Pango text in a DrawingArea looks different from labels | Use `PangoCairo` with the same font family and pixel sizes; create the `Pango.Layout` via `widget.create_pango_layout(text)` so it inherits the widget's font settings. |
| Redraws are slow on the Pi | Draw only the visible hours; cache per-week layout (block rectangles, text layouts) and redraw from cache; only rebuild on data/week change. Avoid alpha blending except for tentative events. |
| Colours for cairo come from hex | Parse `#rrggbb` into floats once per calendar (cache). |

---

## Scope

### In scope
- `calpi/data/week_layout.py` (pure): time-axis mapping, overlap columns algorithm, all-day strip lanes (reuse `layout.py` lane assignment), hit rectangles.
- `calpi/widgets/week_view.py`: `WeekView` screen (`"week"`): header (title "14 – 20 September 2026", ‹ Today ›, view switcher), day header row (weekday + date, today highlighted), all-day strip, timeline `DrawingArea`.
- Visible hour range: default 07:00–22:00; events outside it are indicated with small "↑ earlier" / "↓ later" markers per day (tap → day detail).
- Current-time line (today column), updated each minute.
- View switcher in both month and week headers; `K_DEFAULT_VIEW` setting ("month" | "week"); inactivity returns to the default view's current period.
- Tap handling → day detail.

### Out of scope
- Scrolling the timeline vertically (a fixed range is simpler and faster; events outside are indicated) — could be a follow-up.
- Drag to create/edit (project out of scope).
- Animations.

---

## Acceptance criteria

1. A **view switcher** (segmented buttons "Month" | "Week", ≥ 110 × 72) sits in the header `start_slot` of both views; switching is instant (< 200 ms p90 on the Pi).
2. **Layout** (1920 × 1080): header ~120 px; day header row ~70 px (e.g. "Mon 14", today in accent); all-day strip showing up to 3 lanes (~28 px each) with "+N" overflow per day; timeline filling the rest with 07:00–22:00 (≈ 55 px per hour), hour labels at the left (~80 px gutter), faint hour lines.
3. **Timed events** are drawn as rounded blocks in their calendar colour, positioned by local start/end (display zone), minimum height 26 px, with text "09:30 Dentist" (time format per settings) wrapped/clipped inside the block; tentative events dimmed/outlined.
4. **Overlaps**: events overlapping in time within a day are placed side by side in columns (the standard "cluster → columns" algorithm, D2); each block's width = column width; no text overlaps another block.
5. Events crossing the visible range edges are clipped to the range with a small arrow marker; events entirely before 07:00 or after 22:00 are summarized as "↑ 2 earlier" / "↓ 1 later" at the top/bottom of that day column.
6. **Multi-day timed events** (e.g. 22:30 → 01:00) are split per day: the part on each day drawn in that day's column.
7. All-day and multi-day all-day events appear in the all-day strip as bars spanning their days (using `layout.py` lane assignment, capacity 3).
8. **Today**: day header highlighted; a thin accent **current-time line** across today's column at the current time, updated every minute via `app.clock`.
9. **Navigation**: ‹ / › = previous/next week; Today = current week; keys Left/Right/Home; swipe (if US-35). Week starts on `K_WEEK_START`.
10. **Tap** on a block, an overflow marker, or a day header → day detail for that date (US-09).
11. **Data refresh**: `WeekView.reload()` hooked into `app.on_data_changed`; redraw only when `(revision, week start, tz, time format, calendar colour hash)` changed.
12. **Performance** on the Pi (with real data): `week_render` p90 ≤ 200 ms; switching weeks p90 ≤ 200 ms; idle CPU unchanged.
13. `K_DEFAULT_VIEW` ("month" default) chosen in Settings → Preferences ("Start with: Month | Week"); inactivity (US-08) returns to the default view showing the current period; the app starts in the default view.
14. Pure layout logic is unit-tested (overlap columns, clipping, splitting, hit-testing).

---

## Design decisions (already made)

- **D1. Rendering:** one `Gtk.DrawingArea` for the timeline (all 7 day columns) with `set_draw_func`. Precompute a `WeekLayout` (pure) with block rectangles in widget coordinates for the current allocation; cache Pango layouts per block text; `queue_draw()` only on data/week/size change and once per minute (only the time-line region: `queue_draw` of the whole area is acceptable if it's fast; measure).
- **D2. Overlap columns:** per day, sort timed segments by (start, -duration); sweep to build **clusters** (maximal sets of transitively overlapping segments); within a cluster, assign each segment the lowest free column; cluster column count = max column + 1; block x = day_x + col * (day_w / ncols), width = day_w / ncols − gap.
- **D3. Time mapping:** `y(t) = top + (minutes_since_start_of_range / 60) * HOUR_PX`, using **local** times (`astimezone(display_tz)`); on DST change days, the local day may have 23/25 hours — map by local wall-clock time (minutes since local midnight), which keeps the axis labels correct; events in the repeated/skipped hour are placed by their local wall time (acceptable).
- **D4. All-day strip** is a small `Gtk.Grid` of labels (like US-07 bars, reusing `.bar` CSS and `CalendarColors`) — few widgets, so no need to draw it by hand.
- **D5. View switcher** is a tiny shared widget `ViewSwitcher(app)` placed in each view's header; it calls `navigator.show("calendar")` / `navigator.show("week")` and keeps the selected period aligned (switching month → week shows the week containing today if the month is the current one, else the first week of the displayed month).

---

## Implementation plan

### Step 1 — Pure layout (`calpi/data/week_layout.py`) + tests
```python
@dataclass(frozen=True)
class Segment: event: Event; day_index: int; start_min: int; end_min: int   # local minutes since midnight (clipped per day)
@dataclass(frozen=True)
class Block: segment: Segment; x: float; y: float; w: float; h: float; col: int; ncols: int; clipped_top: bool; clipped_bottom: bool
@dataclass
class WeekLayout: blocks: list[Block]; earlier: list[int]; later: list[int]; allday: WeekLayout_from_layout_py
def split_timed(events, week_dates, tz) -> list[Segment]: ...        # per-day pieces (multi-day timed split at local midnight)
def assign_columns(segments_of_day) -> list[tuple[Segment, int, int]]: ...   # D2
def build(week_dates, events, tz, geom: Geometry) -> WeekLayout: ...  # geometry: gutter, day_w, top, hour_px, range_start_h, range_end_h
def hit_test(layout, x, y) -> tuple[str, date] | None: ...            # ("event", date) / ("earlier", date) / ("later", date)
```
Tests: no overlap → 1 column each; 3 events A(9–10), B(9:30–11), C(10–10:30) → A col0, B col1, C col0, ncols 2; chain overlaps; zero-length event → min height; 22:30→01:00 split into two segments; events before/after range counted; DST day (Europe/Berlin 2026-03-29) positions by wall time; hit_test on block and markers.

### Step 2 — `WeekView` widget
Structure: header (title, `ViewSwitcher`, ‹ Today ›, plus the same end_slot items as the month header — sync indicator/refresh/settings — **reuse**: move those into a shared `HeaderEnd` widget or re-parent on screen switch; simplest: the `SyncIndicator`, `RefreshButton`, and settings button are created per header (they subscribe/unsubscribe properly per US-19 D1)). Day header row: `Gtk.Grid` of 7 labels (+ gutter spacer) with `GestureClick` → day detail. All-day strip: `Gtk.Grid` like US-07 `WeekRow.content`. Timeline: `Gtk.DrawingArea` (hexpand/vexpand) with `set_draw_func(self._draw)` and a `GestureClick` (on `released`) → `hit_test`.

`_draw(area, cr, w, h)`: background → hour lines + labels (gutter) → today column subtle background → blocks (rounded rect fill with calendar RGB; tentative: alpha 0.5 + outline) → text via `PangoCairo.show_layout` clipped to block rect → "earlier/later" markers → current-time line (if today in week). Use cached per-calendar RGB tuples and cached `Pango.Layout`s (keyed by (text, width)).

`reload(force=False)` builds `WeekLayout` when key changed or allocation changed (`notify::width`/`height` or `resize` signal of DrawingArea) and calls `queue_draw()`. Measure with `perf.until_paint("week_render", self)`.

### Step 3 — Navigation, clock, keys, swipe
`go_relative(±1)` (weeks), `go_today()`, `on_key` (Left/Right/Home, `m` → month view). `app.clock.subscribe_minute` → if the current week contains today: `queue_draw()` (time line). `subscribe_day_changed` → reload. Swipe via `attach_horizontal_swipe(self.timeline, ...)` if US-35 exists.

### Step 4 — Default view + switcher + inactivity
Register `K_DEFAULT_VIEW` ("month" | "week"; later "agenda" by US-40 — validator reads from a registry list `VIEWS`). `ViewSwitcher` in both headers. App start: `navigator.reset("week" if default == "week" else "calendar")`. Inactivity (US-08 `_on_idle_return`): generalize to "if current in (calendar, day, week, agenda) → reset to default view at current period". Preferences: add `ChoiceRow("Start with", [("month","Month"),("week","Week")], key=K_DEFAULT_VIEW)` (US-28's panel; a small addition).

### Step 5 — Pi check
Real data: screenshot of the current week; overlap-heavy week with sample data (add a sample case with 3 overlapping events if not present — extend US-04 sample generator); measure `week_render`/switch timings; tap blocks → day detail; current-time line moves each minute.

---

## Files

| File | Change |
|---|---|
| `calpi/data/week_layout.py` | New |
| `calpi/widgets/week_view.py`, `calpi/widgets/view_switcher.py` | New |
| `calpi/app.py` | Register `week` screen, default view start, generalized inactivity |
| `calpi/widgets/month_view.py` | ViewSwitcher in header |
| `calpi/widgets/settings/preferences.py` | "Start with" row |
| `calpi/data/settings_store.py` | `K_DEFAULT_VIEW`, `VIEWS` |
| `calpi/data/sample_data.py` | Overlap sample case |
| `calpi/style.css` | Week view styles (header row, all-day strip) |
| `tests/test_week_layout.py` | New |

---

## Pitfalls

- **One widget per event block** — slow; use the DrawingArea (D1).
- **Redrawing every minute the whole area when it's slow** — measure; if needed, `queue_draw` only when today is in the week.
- **UTC positions** — always local wall time.
- **Text overflowing blocks** — clip each block's text (`cr.rectangle(...); cr.clip()` per block, with `cr.save()/restore()`).
- **Subscriptions from duplicated header widgets leaking** — follow US-19 D1.

---

## Definition of done

- [ ] All acceptance criteria met; layout tests pass.
- [ ] Pi screenshots + timings recorded (US-36 targets).

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `ViewSwitcher`, `VIEWS` registry, `K_DEFAULT_VIEW` | US-40 (adds "agenda") |
| Generalized inactivity return to the default view | US-40 |
| `week_layout` overlap algorithm | future day-timeline in day detail (optional) |
