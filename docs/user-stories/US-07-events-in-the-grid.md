# US-07 — Events in the grid

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P0 |
| **Blocked by** | US-04 Local event store, US-06 Month grid |
| **Blocks** | US-09 Day detail view, US-26 Calendar customization, US-36 Performance targets, US-39 Week view, US-40 Agenda view |
| **Phase** | 1. Foundation |

## Story

> As a user, I want each day's events shown in its cell, colored by calendar, including all-day and multi-day events.

## Context

This is the story that makes calpi a calendar and not just a grid. It reads events from the event store (US-04) for the visible 6 weeks and draws them into each `WeekRow.content` layer (US-06).

It's the hardest layout work in the project, for three reasons:
1. **Multi-day and all-day events are drawn as bars that span several columns**, like Google or Apple Calendar, and they have to stay in the same vertical "lane" across the days they cover. That needs a small lane-assignment algorithm (pure Python, fully unit-tested).
2. **Cells have a fixed capacity** (about 152 px tall). When a day has more events than fit, the last line becomes "+N more", and the number must be exactly right.
3. **The Pi 3B renders in software.** Loading a month must be fast. That means a few dozen labels at most per month, reused where possible, and redrawn only when the data or the month changes.

Load the `gtk-kiosk-app` skill. Read US-04's contracts (`events_for_days`, the sort order D6, the representation of all-day events) and US-06's contracts (`WeekRow.content`, `DAY_NUMBER_HEIGHT`, `month_changed_callbacks`).

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-04** Local event store | `EventStore.events_for_days(first, end, tz)` (sorted), `list_calendars()`, `Calendar.color`/`.name`, `revision()`, **sample data** covering every display case | `/usr/bin/python3 -m pytest tests/test_event_store.py tests/test_sample_data.py` passes. `/usr/bin/python3 -m calpi.data.sample_data --load --state-dir /tmp/x` works. `grep -n "def events_for_days" calpi/data/event_store.py` |
| **US-06** Month grid | `MonthView`, `WeekRow.content` (non-targetable, 7 columns), `DAY_NUMBER_HEIGHT`, `month_changed_callbacks`, `visible_range()`, `timeutil` | `scripts/smoke.sh` logs `month_view: showing`. `grep -n "self.content" calpi/widgets/week_row.py` |

### Soft dependencies
- **US-03** for checking on the Pi (the look and the timing). Strongly recommended: the performance numbers in acceptance criterion 8 can only be measured on the Pi.
- **US-28** (later) changes `time_format` and the zone. This story reads the time format through `formatting.set_time_format()`, defaulting to 24h, **not** through settings (US-07 isn't blocked by US-05).

### External blockers
None.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| The rows grow taller when there are many events | The content layer is an overlay clipped by `WeekRow` (US-06 D2). If a row still grows, a label somewhere has no `ellipsize`, or something set a `min-height`. Check every label: `ellipsize=END`, `max_width_chars=1` (so the natural width doesn't push the column), `hexpand=True`, `xalign=0`. |
| Bars don't line up with the cell columns | The content grid must have the same 7 homogeneous columns and the same horizontal padding as the cell grid. Use identical CSS padding on both, or none on either. |
| Colours can't be set per widget in GTK 4 | That's right: there's no `override_background_color`. Use **generated CSS classes** (D5). |
| Label creation is slow on the Pi | Use the widget pool (D7). Measure first (acceptance criterion 8). |

---

## Scope

### In scope
- `calpi/data/formatting.py`: time labels (12h/24h), event line text.
- `calpi/data/layout.py`: pure lane assignment and per-day visible and overflow computation (fully tested).
- `calpi/widgets/calendar_colors.py`: generated CSS for per-calendar colours, including text contrast.
- Filling `WeekRow.content`: bars for all-day and multi-day events, lines for timed events, and "+N more".
- Loading data when the month changes, and reloading when `store.revision()` changes (with a public `reload()` for US-10/US-16 to call).
- Tentative events drawn differently (dimmed or outlined).

### Out of scope
- Opening a day (US-09). Tapping "+N more" also opens the day, and that's US-09. Here it's just a label.
- Hiding, renaming, and recolouring calendars (US-26). Here the colours come from `Calendar.color`, and hidden calendars are already filtered out by the store.
- Syncing (US-15/16). Sample data is enough here.

---

## Acceptance criteria

1. **Timed single-day events** show as one line in their day's cell: a small calendar-colour dot or left stripe, the start time ("9:30" or "09:30" depending on the format), and the summary, ellipsized at the cell width.
2. **All-day events** show as a filled bar in the calendar's colour, with the summary in a readable contrasting colour (black or white, chosen by luminance).
3. **Multi-day events** (all-day events of 2+ days, **and** timed events that cross midnight or last several days) show as **one continuous bar per week row**, spanning the columns they cover. If the event continues from the previous week or into the next one, the bar's start or end edge is square (not rounded), and the text is repeated on each week's segment.
4. A multi-day event keeps the **same lane** across all the days it covers within a week row.
5. **Order within a day**: bars (lanes) at the top, then timed events by start time, as the store returns them (US-04 D6).
6. **Capacity and overflow**: each cell shows at most `CAPACITY` lines (computed from the cell height: 4 at the default sizes). If a day has more items than fit, the last visible line is "+N more", where **N is exactly the number of that day's items not shown**, counting bars that were pushed out of the visible lanes.
7. Days outside the displayed month show their events too, dimmed like their day number (35% opacity).
8. **Performance on the Pi 3B**, with sample data: switching months (calling `show_month` and loading events) finishes in **under 150 ms** at the 90th percentile, measured from the call to the next frame being painted (log `perf: month_render NN ms` at DEBUG, or INFO when `CALPI_PERF=1`). Also: no CPU use while idle (no timers are added).
9. When `store.revision()` changes and `month_view.reload()` is called, the visible events update. When the revision is unchanged, `reload()` does nothing (no widget changes).
10. Events from hidden calendars never appear. Calendar colours come from `Calendar.color` (so user overrides in US-26 take effect automatically).
11. Tentative events (`status == "TENTATIVE"`) are visibly different: a striped or outlined bar, or italic dimmed text for timed lines.
12. **Midnight-crossing edge cases**: a timed event from 22:30 to 01:00 shows as a 2-day bar (D2). An event from 00:00 to 00:00 the next day (exactly 24 h, timed) shows only on its first day. An event ending at exactly 00:00 doesn't show on the day it ends.

---

## Design decisions (already made)

- **D1. Item types** in a week row:
  - **Bar**: an all-day event (any length), or a timed event that covers more than one local day. Bars are placed in lanes, and span columns.
  - **Line**: a timed event that starts and ends on the same local day (end ≤ the next midnight). Lines go into their day's column under the lanes.
  - Both use the same 26–28 px line height, so capacity is counted in lines.
- **D2. Which days a timed event covers**: from `start.astimezone(tz).date()` up to and including `(end - 1 microsecond).astimezone(tz).date()`, but at least the start day. This makes events ending at exactly midnight **not** show on the next day. An event covering one day is a line, otherwise a bar.
- **D3. Lane assignment is greedy, per week row**: sort the bars by (start column, longer first, then the store order), and put each bar in the lowest lane that's free across all its columns. Done in `layout.py`, which is pure and tested. The lanes are **local to each week row** (like Google Calendar), so a bar can be in a different lane in the next week. That's acceptable and expected.
- **D4. Capacity**: `CAPACITY = floor((cell_height - DAY_NUMBER_HEIGHT) / LINE_HEIGHT)`, computed from constants (the cell height is fixed because there are always 6 rows at 1080p: US-06 D1). Don't measure it at runtime: measurement needs a layout pass and adds complexity. The constants live in `week_row.py`, next to `DAY_NUMBER_HEIGHT`.
  - Per day: `visible_slots = CAPACITY`. If the day's total items (bars covering it + its lines) > CAPACITY, then only `CAPACITY - 1` slots show items and the last slot shows "+N more".
  - Bars take slots by **lane index**. A bar in lane L is visible on a day only if `L < the visible slots of that day`. For a bar spanning several days where some of the days are overflowing, draw the bar only for the **contiguous run of columns** where it's visible, and count it as hidden on the others. (It's a rare case. Keep the rule simple and tested.)
  - Lines fill the slots left under the highest *used* lane of that day.
- **D5. Colours through generated CSS**: `calendar_colors.py` builds one CSS provider with a class per calendar: `.cal-<n>` where `<n>` is a small integer index mapped from the calendar id (never put ids straight into CSS: they contain `:` and other characters). Rules: `.bar.cal-3 { background-color: #4f9dff; color: #0b0e11; }` `.line.cal-3 .dot { background-color: #4f9dff; }`. Regenerate the provider when the calendar list changes (compare a hash of `(id, color)` pairs). One provider, replaced in place (`provider.load_from_data`), at `STYLE_PROVIDER_PRIORITY_APPLICATION + 1`.
- **D6. Text contrast**: relative luminance (WCAG formula). If the luminance of the background is > 0.45, the text is `#0b0e11`, otherwise `#ffffff`.
- **D7. Widget pool**: each `WeekRow` keeps a pool of bar labels and line boxes. Rendering takes widgets from the pool (creating more only if it runs out), attaches them to the grid, and at the start of the next render, detaches the used ones (`grid.remove`) and returns them to the pool. **Never destroy and recreate on every render.** Keep the pool size bounded: if it's larger than 60, drop the extras.
- **D8. The time format** comes from a module-level setting in `formatting.py` (`set_time_format("24h" | "12h")`), default `"24h"`. US-28 connects it to settings.
  - 24h: `09:30` → shown as `9:30`? **Decision: `09:30` style in 24h mode, and `9:30a` / `2:15p` in 12h mode** (short, to save width). The day detail (US-09) uses the longer `9:30 AM`.
- **D9. A reload is triggered by** (a) a month change (`month_changed_callbacks`), (b) `month_view.reload()` called by others (US-10 at midnight, US-16 after a sync, US-26 after a calendar change, US-28 after a zone/format change). `reload(force=False)` skips the work if the `(store.revision(), year, month, tz, week_start, time_format, calendar CSS hash)` key hasn't changed.

---

## Implementation plan

### Step 1 — `calpi/data/formatting.py` (no gi)

```python
_time_format = "24h"
def set_time_format(fmt: str) -> None:
    global _time_format
    if fmt not in ("24h", "12h"): raise ValueError(fmt)
    _time_format = fmt
def time_format() -> str: return _time_format

def short_time(t: datetime) -> str:
    """Compact label for grid lines: '09:30' (24h) or '9:30a' (12h). '9a' when minutes are 0 in 12h."""
    if _time_format == "24h":
        return f"{t.hour:02d}:{t.minute:02d}"
    h = t.hour % 12 or 12
    suffix = "a" if t.hour < 12 else "p"
    return f"{h}{suffix}" if t.minute == 0 else f"{h}:{t.minute:02d}{suffix}"

def long_time(t: datetime) -> str:
    """'09:30' (24h) or '9:30 AM' (12h). Used by the day detail (US-09)."""
    ...
```
Always pass times that are already converted to the display zone. Tests for both formats, including midnight (`00:00` / `12a`) and noon (`12:00` / `12p`).

### Step 2 — `calpi/data/layout.py` (no gi): the core algorithm

```python
@dataclass(frozen=True)
class Bar:
    event: Event
    start_col: int          # 0..6 within the week
    end_col: int            # inclusive
    continues_before: bool  # event started before this week
    continues_after: bool
    lane: int = -1

@dataclass(frozen=True)
class Line:
    event: Event
    col: int
    local_start: datetime   # already in display tz, for the time label

@dataclass
class DayLayout:
    lines: list[Line]            # lines that are visible
    hidden_count: int            # number for "+N more" (0 = no overflow line)
    more_slot: int | None        # slot index where "+N more" goes

@dataclass
class WeekLayout:
    bars: list[tuple[Bar, int, int]]   # (bar, visible_start_col, visible_end_col) segments to draw
    days: list[DayLayout]              # 7 entries

def covered_days(e: Event, tz) -> tuple[date, date]:
    """Inclusive (first_day, last_day) the event occupies in display tz (D2)."""
    if e.all_day:
        return e.start, max(e.start, e.end - timedelta(days=1))
    s = e.start.astimezone(tz)
    last = (e.end - timedelta(microseconds=1)).astimezone(tz).date() if e.end > e.start else s.date()
    return s.date(), max(s.date(), last)

def layout_week(week_dates: list[date], events: list[Event], tz, capacity: int) -> WeekLayout:
    # 1. classify each event overlapping this week into Bar (spans >1 day OR all_day) or Line
    # 2. clip bars to columns 0..6; set continues_before/after
    # 3. assign lanes greedily (D3)
    # 4. per day: items = bars covering day (by lane) + lines (store order)
    #    if len(items) > capacity: visible = capacity - 1, more_slot = capacity - 1
    #    bars visible on day d iff lane < visible; lines fill slots from (max visible lane used on d)+1
    #    hidden_count = total items on day - visible items on day
    # 5. build visible bar segments: for each bar, the runs of consecutive columns where it's visible
    ...
```
Decisions inside the algorithm:
- An **all-day event of exactly one day is still a Bar** (D1): it's filled, spans 1 column, and takes a lane. That keeps all-day items at the top, looking the same whatever their length.
- Line slots on a day start **after the highest lane used on that day** (not after the highest lane used in the week). That avoids empty gaps under days that have no bars.
  - But careful: if lane 0 is empty on a day and lane 1 is used (a bar from a neighbouring day in lane 1 passes over it), lines start at slot 2 on that day, and slot 0 stays empty. Accept it: it's what keeps bars straight.

**Write the tests before the widget code** (`tests/test_layout.py`):
1. A single timed event → one Line, no bars.
2. A 3-day all-day event from Tue to Thu → one Bar, columns 1–3, lane 0.
3. Two overlapping multi-day bars → lanes 0 and 1. A third that doesn't overlap the first → lane 0.
4. A bar starting before the week → `continues_before`, column 0. Ending after → `continues_after`, column 6.
5. A timed event from 22:30 to 01:00 → a Bar across 2 columns (D2). An event ending at exactly 00:00 → a Line on the start day only.
6. Overflow: capacity 4, a day with 9 lines → 3 visible lines + "+6 more" in slot 3.
7. Overflow with bars: capacity 4, 4 bars stacked on Wednesday (lanes 0–3) plus 2 lines on Wednesday → visible: lanes 0–2 (3 slots), "+3 more" (1 bar + 2 lines). On Tuesday, only lanes 0–1 exist → no overflow.
8. A bar in lane 3 that crosses an overflowing day → drawn as two segments around that day, hidden on that day, and counted there.
9. The hidden count is exact in every case (property-style test: generate random events with a seeded `random.Random`, and check that visible + hidden == total per day for 1,000 random weeks).
10. DST: an event from 01:30 to 03:30 on the spring-forward day in `Europe/Berlin` → one day.

### Step 3 — `calpi/widgets/calendar_colors.py`

```python
class CalendarColors:
    """Generates and installs a CSS provider with one class per calendar."""
    def __init__(self):
        self._provider = Gtk.CssProvider()
        add_style_provider(self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._classes: dict[str, str] = {}
        self._hash = None

    def update(self, calendars: list[Calendar]) -> bool:
        key = tuple(sorted((c.id, c.color) for c in calendars))
        if key == self._hash: return False
        self._hash = key
        css = []
        for i, c in enumerate(sorted(calendars, key=lambda c: c.id)):
            cls = f"cal-{i}"
            self._classes[c.id] = cls
            fg = contrast_text(c.color)
            css.append(f".bar.{cls} {{ background-color: {c.color}; color: {fg}; }}")
            css.append(f".line.{cls} .dot {{ background-color: {c.color}; }}")
        self._provider.load_from_data("\n".join(css).encode())   # see note on the signature
        return True

    def css_class(self, calendar_id: str) -> str:
        return self._classes.get(calendar_id, "cal-unknown")
```
- Put `contrast_text(hex)` and `relative_luminance(hex)` in `formatting.py` (pure, tested), not in the widget module.
- **`Gtk.CssProvider.load_from_data` changed signature** between GTK versions (in 4.12+ PyGObject accepts `(str, -1)`; older versions take `bytes`). Write a small helper that tries `load_from_string` (4.12+), then `load_from_data(bytes)`, then `load_from_data(str, -1)`. Test it on the Pi's GTK version.
- **Validate colours** before putting them into CSS: only allow `^#[0-9a-f]{6}$`, otherwise use `DEFAULT_CALENDAR_COLOR`. That avoids CSS injection from server data (US-15 normalises colours too, but defend here as well).

### Step 4 — Rendering in `WeekRow` (`week_row.py`)

Add constants and a render method:
```python
LINE_HEIGHT = 27              # px, must match .bar / .line min-height + margins in CSS
CELL_HEIGHT = 152             # (1080 - header - weekday row) / 6, see US-06 D1; verify on the Pi
CAPACITY = (CELL_HEIGHT - DAY_NUMBER_HEIGHT) // LINE_HEIGHT     # 3 or 4 — check

def render(self, layout: WeekLayout, colors: CalendarColors, month: int) -> None:
    self._release_all()                       # detach last render's widgets back into pools
    for bar, c0, c1 in layout.bars:
        w = self._take_bar()
        w.set_text(bar.event.summary or "(no title)")
        w.set_css_classes(["bar", colors.css_class(bar.event.calendar_id),
                           *(["cont-before"] if bar.continues_before and c0 == bar.start_col else []),
                           *(["cont-after"] if bar.continues_after and c1 == bar.end_col else []),
                           *(["tentative"] if bar.event.status == "TENTATIVE" else []),
                           *(["other-month"] if all(self.dates[i].month != month for i in range(c0, c1+1)) else [])])
        self.content.attach(w, c0, bar.lane, c1 - c0 + 1, 1)
    for col, day in enumerate(layout.days):
        for slot, line in day.placed_lines:   # (slot index, Line) pairs computed by layout
            w = self._take_line(); w.set(line, colors, other_month=self.dates[col].month != month)
            self.content.attach(w, col, slot, 1, 1)
        if day.hidden_count:
            m = self._take_more(); m.set_text(f"+{day.hidden_count} more")
            self.content.attach(m, col, day.more_slot, 1, 1)
```
Adjust `DayLayout` to carry `placed_lines: list[tuple[int, Line]]`, so the widget code doesn't redo any layout logic. **All the decisions are in `layout.py`. `render` only places widgets.**

`set_css_classes` replaces all classes at once. That's fine for pooled widgets and cheaper than several add/remove calls.

The **Line widget** is a `Gtk.Box` with a dot (`Gtk.Box`, 10×10 px, css `dot`, rounded), a time label (css `time`), and a summary label (css `summary`, `ellipsize=END`, `hexpand=True`, `max_width_chars=1`). Build it once per pooled instance, and only change text and classes.

Also make sure every content-grid row has the same height: set `row_homogeneous=False`, but give each child `min-height: LINE_HEIGHT` through CSS, and set `valign=START` on the content grid, so rows don't stretch to fill the cell.

**The CSS**:
```css
.week-content { padding: 0 4px; }            /* match .day-cell horizontal padding */
.bar  { min-height: 25px; margin: 1px 3px; padding: 0 8px; border-radius: 6px; font-size: 19px; }
.bar.cont-before { border-top-left-radius: 0; border-bottom-left-radius: 0; margin-left: 0; }
.bar.cont-after  { border-top-right-radius: 0; border-bottom-right-radius: 0; margin-right: 0; }
.bar.tentative   { opacity: 0.6; }            /* or a dashed border, if it's legible on the device */
.line { min-height: 25px; margin: 1px 6px; font-size: 19px; }
.line .dot  { min-width: 10px; min-height: 10px; border-radius: 5px; margin-right: 6px; }
.line .time { color: @text_dim; margin-right: 6px; }
.line.tentative .summary { font-style: italic; color: @text_dim; }
.more { font-size: 18px; color: @text_dim; margin: 1px 8px; }
.other-month { opacity: 0.35; }
```
Font sizes: 19 px is the smallest that's still readable at a glance from about 2 m on a 1080p panel. Tune on the device, and **recompute `CAPACITY`** if you change the sizes.

### Step 5 — Loading in `MonthView`

```python
class MonthView:
    def attach_store(self, store: EventStore) -> None:
        self.store = store
        self.colors = CalendarColors()
        self.month_changed_callbacks.append(lambda y, m: self.reload(force=True))
        self.reload(force=True)

    def reload(self, force: bool = False) -> None:
        tz = timeutil.display_tz()
        key = (self.store.revision(), self.year, self.month, tz.key, self.week_start, formatting.time_format())
        if not force and key == self._last_key: return
        t0 = time.perf_counter()
        self.colors.update(self.store.list_calendars(include_hidden=False))
        first, end = self.visible_range()
        events = self.store.events_for_days(first, end, tz)
        for row in self.week_rows:
            row.render(layout.layout_week(row.dates, _overlapping(events, row.dates, tz), tz, CAPACITY),
                       self.colors, self.month)
        self._last_key = key
        perf.mark_until_paint("month_render", t0, self)   # or a local helper; see below
```
- `_overlapping(events, dates, tz)` pre-filters the events for each week (bars can be in several weeks). Doing it in Python per week is fine: at most a few hundred events.
- **Timing up to the next paint**: after rendering, connect once to the frame clock's `after-paint` signal (`self.get_frame_clock()`) and log `perf: month_render %.1f ms` from `t0`. If US-36's `calpi/perf.py` doesn't exist yet, write a small local helper `_log_until_paint(name, t0, widget)` here and add a comment that US-36 will move it into `perf.py`.
- Where the store comes from: `CalpiApp` creates **one** `EventStore` for the UI process and passes it in (`month_view.attach_store(store)`), next to the settings store if US-05 is done.

### Step 6 — Check it

**Devcontainer**:
```bash
CALPI_STATE_DIR=.devstate /usr/bin/python3 -m calpi.data.sample_data --load --clear
CALPI_STATE_DIR=.devstate scripts/dev-run.sh
```
Look at every D8 case from US-04: the busy day with "+N more", the 3-day bar across the week boundary (two segments with square edges), the midnight-crossing event, the long title (ellipsized), the other-month days (dimmed), and no events from the hidden `Archive` calendar. Try `CALPI_FAKE_NOW` so the sample data lands in different parts of the grid.

**Pi** (US-03):
```bash
scripts/pi deploy && scripts/pi sample-data --clear && scripts/pi restart && scripts/pi screenshot
```
Read the screenshot. Measure: with `CALPI_PERF=1` set in a systemd drop-in, or a temporary environment variable, switch months (after US-08 exists; before that, use a temporary test hook that cycles through 12 months at startup, `CALPI_TEST_MONTH_CYCLE=1` from US-06). Collect the `perf: month_render` lines and report the median and p90.

---

## Files

| File | Change |
|---|---|
| `calpi/data/formatting.py`, `calpi/data/layout.py` | New |
| `calpi/widgets/calendar_colors.py` | New |
| `calpi/widgets/week_row.py` | Constants, pools, `render()` |
| `calpi/widgets/month_view.py` | `attach_store()`, `reload()` |
| `calpi/app.py` | Creates the `EventStore` and attaches it |
| `calpi/style.css` | Event styles |
| `tests/test_formatting.py`, `tests/test_layout.py` | New |

---

## Pitfalls

- **Recomputing layout in widget code.** All the decisions belong in `layout.py`, where they can be tested.
- **Labels without ellipsize** make the grid wider.
- **`+N more` off by one.** The property test in step 2 exists for exactly this.
- **Unvalidated colours in CSS.** Validate with a regex.
- **Rendering on every revision check when nothing changed.** Use the reload key.
- **Treating one-day all-day events as lines.** They're bars (D1).
- **Using `event.start.date()` for timed events.** You get the UTC date, not the local one. Always `astimezone(tz)` first.

---

## Definition of done

- [ ] All acceptance criteria met. `test_layout.py`, including the property test, passes.
- [ ] Every sample-data case checked visually in Broadway.
- [ ] Pi screenshot reviewed. Month render timing recorded (median/p90) in the hand-off notes.
- [ ] `CAPACITY`, `LINE_HEIGHT`, and `CELL_HEIGHT` match the real layout on the device (check with a screenshot: no clipped lines and no large empty gaps).

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `MonthView.attach_store(store)`, `MonthView.reload(force=False)` | US-10, US-16, US-26, US-28 |
| `formatting.short_time`, `long_time`, `set_time_format`, `time_format`, `contrast_text` | US-09, US-28, US-39, US-40 |
| `layout.covered_days(event, tz)` (which days an event covers) | US-09, US-39, US-40 |
| `CalendarColors` (one instance; `css_class(calendar_id)`, `update(calendars)`) | US-09, US-26, US-39, US-40 (reuse the same instance: put it on the app) |
| The `perf: month_render` log line | US-36 |
| CSS classes: `.bar`, `.line`, `.dot`, `.more`, `.tentative`, `.other-month`, `.cal-N` | US-09, US-39, US-40 |
