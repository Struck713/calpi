# US-06 — Month grid

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P0 |
| **Blocked by** | US-02 App skeleton |
| **Blocks** | US-07 Events in the grid, US-08 Month navigation, US-10 Midnight rollover, US-28 Regional preferences, US-41 Weather |
| **Phase** | 1. Foundation |

## Story

> As a user, I want the current month shown as a grid with today clearly marked.

## Context

This is the main screen of the product: what people see from across the room, 24 hours a day. It replaces US-02's placeholder as the `calendar` screen.

This story builds the **frame**: the header, the weekday names, and 6 week rows × 7 day cells with day numbers, where the days from other months are dimmed and today is clearly highlighted. **Events are not part of this story** (that's US-07), but the widget structure has to leave room for them. The design decision on `WeekRow` below exists for US-07.

It also creates two small pure-Python modules that many later stories use:
- `calpi/data/timeutil.py`: the single source of "now", "today", and the display time zone (with a fake-clock hook for testing).
- `calpi/data/monthmath.py`: the grid dates for a given month and week start, plus month and weekday names.

Load the `gtk-kiosk-app` skill: build the tree **once** and mutate it afterwards, update text only when it changed, and use no animations.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-02** App skeleton | `MainWindow`, `Navigator` (`add`/`show`), `style.css`, `widgets/util.py`, `tasks.safe_callback`, `scripts/dev-run.sh` / `smoke.sh` | `scripts/smoke.sh` → `SMOKE OK`. `grep -n "class Navigator" calpi/app.py` |

### Soft dependencies
- **US-03** for the check on the Pi (screenshots, readability). Without it, check in Broadway and hand the Pi check to the first story that has US-03.
- **US-05 isn't a blocker.** This story must **not** depend on `SettingsStore`. The week start and the time zone are **parameters and module-level hooks with defaults**. US-28 later connects them to settings. So: `MonthView(week_start=0)`, and `timeutil.set_display_tz(...)`.
- **US-04** (sample data) makes the screen more realistic, but it isn't needed. There are no events in this story.

### External blockers
None for the devcontainer. The final readability check needs the physical monitor and the owner's eyes (acceptance criterion 8).

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Columns have different widths, or a cell grows when its text is long | Use `Gtk.Grid` with `column_homogeneous=True`, `hexpand=True` on the cells, and later (US-07) `ellipsize` on every label. A label without ellipsize asks for its full natural width and pushes the column wider. |
| The devcontainer shows UTC while the owner is somewhere else | That's expected. Use `CALPI_FAKE_NOW` / `CALPI_TZ` (step 1) to test other zones. On the Pi, the zone set during provisioning is used. |
| Broadway looks different from the Pi (fonts, sizes) | Broadway is for layout and logic. Judge the final look with a screenshot from the Pi (`scripts/pi screenshot`). |

---

## Scope

### In scope
- `timeutil.py`, `monthmath.py` (with tests).
- `widgets/month_view.py` (`MonthView`), `widgets/header.py` (`Header` with slots), `widgets/week_row.py` (`WeekRow`, containing the cells and an **empty** overlay content layer for US-07), `widgets/day_cell.py` (`DayCell`).
- CSS for all of the above.
- Replacing the placeholder: the `calendar` screen becomes `MonthView`, which shows the month of `timeutil.today()`.
- Public methods that later stories call: `show_month(year, month)`, `refresh_today()`, `set_week_start(n)`.

### Out of scope
- Events (US-07), navigation buttons and gestures (US-08, US-35), tapping a day (US-09), midnight updates (US-10: it only *calls* `refresh_today()`), settings connections (US-28), and anything in the header slots.

---

## Acceptance criteria

1. The `calendar` screen shows, at 1920×1080: a header (about 120 px) with the month and year ("September 2026"), a row of weekday names (about 48 px), and **always 6 week rows** filling the rest, with 7 equal-width columns.
2. The grid covers the whole displayed month. Leading and trailing days from the neighbouring months fill the 42 cells, and they're **visibly dimmed**.
3. **Today** is obvious from across a room: the day number sits in a filled accent-coloured circle, and the cell has an accent border or a slightly lighter background. Only one cell is marked. If the displayed month isn't the current month, no cell is marked, **unless** today is one of the visible leading or trailing days, in which case it's marked in its dimmed cell as well.
4. The week start can be Monday (default), Sunday, or Saturday (and in fact any value 0–6). The weekday header and the grid match. `set_week_start(6)` re-lays out the grid without rebuilding widgets.
5. `monthmath.month_grid_dates(year, month, week_start)` returns exactly 42 consecutive dates. The first is on the `week_start` weekday, on or before the 1st of the month. Tested for every month of 2024–2030 with every week start.
6. `timeutil.now()` returns an aware datetime in the display zone. `today()` returns its date. With `CALPI_FAKE_NOW=2026-02-28T23:59:30`, the app behaves as if it were that time **and the clock keeps moving** (offset mode).
7. Changing the month (`show_month`) only changes label text and CSS classes. It creates **no** new widgets. (Test: count the descendant widgets before and after 12 month changes: they're equal.)
8. On the Pi, a screenshot shows the grid correctly, and the owner confirms that the month title and today's marker are readable from about 3 m away.
9. Smoke: `scripts/smoke.sh` still passes, and the log contains `month_view: showing 2026-09` (or the current month) at INFO level.

---

## Design decisions (already made)

- **D1. Always 6 rows.** The cell size is the same every month (about 274 × 152 px), which US-07's capacity calculation depends on. Months that need only 4 or 5 rows show the next month's days in the last row(s).
- **D2. Widget structure:**
  ```
  MonthView (Gtk.Box vertical, css "screen month-view")
  ├─ Header (Gtk.CenterBox, css "header")
  │   ├─ start: Gtk.Box [ title Label "September 2026" | start_slot Box ]
  │   ├─ center: center_slot Box          ← US-08 puts ‹ Today › here
  │   └─ end:   end_slot Box               ← US-16/19 sync status, US-22 settings button, US-41 weather
  ├─ weekday row (Gtk.Grid, 7 homogeneous columns, css "weekday-row")
  └─ weeks (Gtk.Box vertical, homogeneous, vexpand)
      └─ 6 × WeekRow (Gtk.Overlay, css "week-row")
           ├─ child: Gtk.Grid (7 homogeneous columns) of 7 DayCell  ← backgrounds, borders, day numbers; clickable (US-09)
           └─ overlay: self.content  Gtk.Grid (7 homogeneous columns), can_target=False, margin_top=DAY_NUMBER_HEIGHT
                                         ← US-07 puts event bars and lines here
  ```
  The **content layer is non-targetable**, so taps and clicks go through to the `DayCell` underneath (US-09 opens the day from the cell). The overlay is clipped (`set_clip_overlay(content, True)`), so event content can never enlarge a row.
- **D3. Names are in English, from our own tables** in `monthmath.py`. Don't use `strftime("%B")`, which depends on the locale, and locales may not be installed on Pi OS Lite. Translation is out of scope.
- **D4. Display time zone** = `timeutil.display_tz()`: an explicit override (set by US-28 from settings) if there is one, otherwise the system zone found from `/etc/localtime`, otherwise `UTC`. Always a `zoneinfo.ZoneInfo`, **never** a fixed-offset `tzinfo` (fixed offsets break at DST).
- **D5. The fake clock** (`CALPI_FAKE_NOW`) keeps an **offset** from the real clock, so time keeps moving. That's essential for testing midnight rollover (US-10). `CALPI_TZ` sets the display zone for development.
- **D6. Colours and sizes live in `style.css`.** Suggested starting values (fine-tune them on the real screen):
  - Title: 64 px, weight 300. Weekday labels: 26 px, `@text_dim`, uppercase.
  - Day number: 30 px. Other-month days: 35% opacity on the number (and later the events).
  - Today: the number in a 48 px circle filled with `@accent` and dark text. The cell gets a 3 px `@accent` border.
  - Cell borders: 1 px `alpha(@text, 0.08)`. Weekend cells: a slightly different background, `shade(@bg, 1.1)` (optional; keep it subtle).

---

## Implementation plan

### Step 1 — `calpi/data/timeutil.py` (no gi)

```python
"""The single source of 'now'. Everything that needs the current time or display zone asks here."""
from __future__ import annotations
import logging, os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger("calpi.time")
_override_tz: ZoneInfo | None = None
_fake_offset = None     # timedelta or None

def _init_fake_clock() -> None:
    global _fake_offset
    raw = os.environ.get("CALPI_FAKE_NOW")
    if not raw: return
    fake = datetime.fromisoformat(raw)
    if fake.tzinfo is None:
        fake = fake.replace(tzinfo=display_tz())
    _fake_offset = fake - datetime.now(timezone.utc)
    log.warning("FAKE CLOCK active: now=%s (offset %s)", fake.isoformat(), _fake_offset)

def system_tz_name() -> str:
    env = os.environ.get("CALPI_TZ")
    if env: return env
    try:
        target = os.readlink("/etc/localtime")          # e.g. ../usr/share/zoneinfo/Europe/Paris
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:
        return Path("/etc/timezone").read_text().strip() or "UTC"
    except OSError:
        return "UTC"

def display_tz() -> ZoneInfo:
    if _override_tz is not None:
        return _override_tz
    name = system_tz_name()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("unknown system time zone %r, using UTC", name)
        return ZoneInfo("UTC")

def set_display_tz(name: str | None) -> None:
    """US-28 calls this from settings. None = follow the system zone."""
    global _override_tz
    _override_tz = ZoneInfo(name) if name else None

def now() -> datetime:
    utc = datetime.now(timezone.utc)
    if _fake_offset is not None:
        utc = utc + _fake_offset
    return utc.astimezone(display_tz())

def today() -> date:
    return now().date()

_init_fake_clock()
```
Cache the result of `system_tz_name()`? No. It's cheap, and the owner might change the system zone (US-28). But **don't call `display_tz()` in a tight loop**: resolve it once per refresh.

`ZoneInfo` needs the system tzdata (`/usr/share/zoneinfo`). Pi OS has it (`tzdata` package). The devcontainer too. If it's missing, `ZoneInfo("Europe/Paris")` raises. Mention it in `platform-versions.md` if you run into it.

### Step 2 — `calpi/data/monthmath.py` (no gi)

```python
from datetime import date, timedelta

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
GRID_DAYS = 42

def month_grid_dates(year: int, month: int, week_start: int = 0) -> list[date]:
    """42 consecutive dates covering the month; the first date has weekday() == week_start (0=Mon)."""
    first = date(year, month, 1)
    lead = (first.weekday() - week_start) % 7
    start = first - timedelta(days=lead)
    return [start + timedelta(days=i) for i in range(GRID_DAYS)]

def weekday_order(week_start: int) -> list[int]:
    return [(week_start + i) % 7 for i in range(7)]

def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1

def month_title(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"
```
`add_months` is for US-08. Adding it here now costs nothing and keeps month arithmetic in one place.

Note: with `lead` computed as above, a month whose 1st falls on the week start has **no** leading days, and the first row starts on the 1st. That's correct.

### Step 3 — `calpi/widgets/day_cell.py`

```python
class DayCell(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True,
                         css_classes=["day-cell"])
        self.number = Gtk.Label(css_classes=["day-number"], halign=Gtk.Align.START, valign=Gtk.Align.START)
        self.append(self.number)
        self.date: date | None = None

    def set_day(self, d: date, *, in_month: bool, is_today: bool, is_weekend: bool) -> None:
        self.date = d
        set_text_if_changed(self.number, str(d.day))
        set_class(self, "other-month", not in_month)
        set_class(self, "today", is_today)
        set_class(self, "weekend", is_weekend)
```
The day number label needs a fixed height, `DAY_NUMBER_HEIGHT` (for example 48 px, set with CSS `min-height` and matching the circle), because US-07's content layer uses the same constant as its `margin_top`. **Define `DAY_NUMBER_HEIGHT` once**, in `week_row.py`, and use it both for the CSS (see pitfalls) and for the margin.

### Step 4 — `calpi/widgets/week_row.py`

```python
DAY_NUMBER_HEIGHT = 52   # px; must match .day-number min-height + cell padding in style.css

class WeekRow(Gtk.Overlay):
    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, css_classes=["week-row"])
        self.cells_grid = Gtk.Grid(column_homogeneous=True, hexpand=True, vexpand=True)
        self.cells = [DayCell() for _ in range(7)]
        for i, c in enumerate(self.cells):
            self.cells_grid.attach(c, i, 0, 1, 1)
        self.set_child(self.cells_grid)
        # Layer for US-07 (events). Non-targetable: clicks reach the DayCells.
        self.content = Gtk.Grid(column_homogeneous=True, hexpand=True, vexpand=True,
                                margin_top=DAY_NUMBER_HEIGHT, can_target=False,
                                css_classes=["week-content"])
        self.add_overlay(self.content)
        self.set_clip_overlay(self.content, True)
        self.dates: list[date] = []

    def set_week(self, dates: list[date], month: int, today: date) -> None:
        self.dates = dates
        for cell, d in zip(self.cells, dates):
            cell.set_day(d, in_month=(d.month == month), is_today=(d == today), is_weekend=d.weekday() >= 5)
```
`is_weekend = weekday() >= 5` hard-codes Saturday and Sunday as the weekend. That's fine for now. Record it as a follow-up if the owner wants something else.

Check `set_clip_overlay` exists in the Pi's GTK version (it's available since GTK 4.0). If content still overflows, also set `overflow: hidden` on `.week-row` in CSS (`Gtk.Widget.set_overflow(Gtk.Overflow.HIDDEN)`).

### Step 5 — `calpi/widgets/header.py`

```python
class Header(Gtk.CenterBox):
    def __init__(self):
        super().__init__(css_classes=["header"])
        start = Gtk.Box(spacing=24)
        self.title = Gtk.Label(css_classes=["month-title"], xalign=0)
        self.start_slot = Gtk.Box(spacing=16)
        start.append(self.title); start.append(self.start_slot)
        self.center_slot = Gtk.Box(spacing=16)
        self.end_slot = Gtk.Box(spacing=16)
        self.set_start_widget(start); self.set_center_widget(self.center_slot); self.set_end_widget(self.end_slot)

    def set_title(self, text: str) -> None:
        set_text_if_changed(self.title, text)
```

### Step 6 — `calpi/widgets/month_view.py`

```python
class MonthView(Gtk.Box):
    def __init__(self, week_start: int = 0):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["screen", "month-view"])
        self.week_start = week_start
        self.header = Header()
        self.weekday_row = Gtk.Grid(column_homogeneous=True, css_classes=["weekday-row"])
        self.weekday_labels = [Gtk.Label(css_classes=["weekday-label"]) for _ in range(7)]
        for i, l in enumerate(self.weekday_labels): self.weekday_row.attach(l, i, 0, 1, 1)
        weeks = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, homogeneous=True, vexpand=True, css_classes=["weeks"])
        self.week_rows = [WeekRow() for _ in range(6)]
        for w in self.week_rows: weeks.append(w)
        for w in (self.header, self.weekday_row, weeks): self.append(w)
        t = timeutil.today()
        self.year, self.month = t.year, t.month
        self._apply_weekday_labels()
        self.show_month(t.year, t.month)

    # --- public API (contracts) ---
    def show_month(self, year: int, month: int) -> None:
        self.year, self.month = year, month
        today = timeutil.today()
        dates = monthmath.month_grid_dates(year, month, self.week_start)
        for i, row in enumerate(self.week_rows):
            row.set_week(dates[i*7:(i+1)*7], month, today)
        self.header.set_title(monthmath.month_title(year, month))
        log.info("month_view: showing %04d-%02d", year, month)
        self.emit_month_changed()   # see below

    def refresh_today(self) -> None:
        """Re-mark today (US-10 calls this at midnight)."""
        self.show_month(self.year, self.month)

    def set_week_start(self, week_start: int) -> None:
        if week_start == self.week_start: return
        self.week_start = week_start
        self._apply_weekday_labels()
        self.show_month(self.year, self.month)

    def visible_range(self) -> tuple[date, date]:
        """[first_day, end_day) currently displayed: used by US-07 to query events and US-16 for the sync window."""
        d = self.week_rows[0].dates[0]
        return d, d + timedelta(days=42)
```
**The "month changed" hook**: later stories (US-07 loads events, US-16 widens the sync window, US-08 resets inactivity) need to know when the month changes. Keep it simple: a list of callbacks, `self.month_changed_callbacks: list[Callable[[int, int], None]]`, called at the end of `show_month`, each wrapped in try/except with logging. (A custom GObject signal would also work, but plain callbacks are easier to test and read. **The decision is made: plain callbacks.**)

### Step 7 — Register it as the `calendar` screen

In `MainWindow.__init__`, replace the `PlaceholderScreen`:
```python
self.month_view = MonthView(week_start=0)
self.navigator.add("calendar", self.month_view)
```
Delete `PlaceholderScreen`. The minute clock it had isn't needed any more (US-10 builds the real clock service).

### Step 8 — CSS

Add to `style.css` (starting values, to tune on the device):
```css
.header        { padding: 24px 32px 12px 32px; min-height: 84px; }
.month-title   { font-size: 64px; font-weight: 300; }
.weekday-row   { padding: 0 0 8px 0; }
.weekday-label { font-size: 26px; color: @text_dim; }
.week-row      { border-top: 1px solid alpha(@text, 0.08); }
.day-cell      { border-left: 1px solid alpha(@text, 0.08); padding: 4px 8px; }
.day-cell.weekend      { background-color: shade(@bg, 1.15); }
.day-number    { font-size: 30px; min-height: 44px; min-width: 44px; margin-top: 4px; }
.day-cell.other-month .day-number { opacity: 0.35; }
.day-cell.today        { box-shadow: inset 0 0 0 3px @accent; }
.day-cell.today .day-number { background-color: @accent; color: @bg; border-radius: 999px; font-weight: bold; }
```
Point out in a comment that `.day-number` `min-height` + `margin-top` + cell `padding-top` must add up to `DAY_NUMBER_HEIGHT` in `week_row.py`.

`box-shadow: inset` draws a border without changing the layout. That's better than `border`, which changes the cell's size and would move the content layer.

### Step 9 — Tests

`tests/test_monthmath.py`:
- For every (year 2024–2030, month 1–12, week_start 0–6): 42 dates, consecutive, `dates[0].weekday() == week_start`, `dates[0] <= date(y, m, 1)`, the last day of the month is included, `dates[0] > date(y, m, 1) - 7 days`.
- Specific examples: February 2026 starts on a Sunday → with a Monday start, the first date is 26 January 2026. With a Sunday start, the first date is 1 February 2026.
- `add_months`: (2026, 12, +1) → (2027, 1); (2026, 1, -1) → (2025, 12); (2026, 3, -15) → (2024, 12).

`tests/test_timeutil.py`:
- `CALPI_FAKE_NOW` offset mode: set the environment, reload the module (`importlib.reload`), check `now()` is near the fake time, and **still advances** (`time.sleep(0.05)`, then compare).
- `set_display_tz("America/New_York")` → `now().tzinfo.key == "America/New_York"`. `set_display_tz(None)` → back to the system zone.
- `CALPI_TZ=Nope/Nowhere` → UTC with a warning.
- Use a fixture that resets `_override_tz` and `_fake_offset` after each test.

GTK test (`@pytest.mark.gtk`, runs with `CALPI_GTK_TESTS=1`): extend `scripts/smoke.sh`, or add a second script, that runs with `CALPI_FAKE_NOW=2026-09-15T10:00:00` and checks the log for `month_view: showing 2026-09`.

For the "no new widgets" check (acceptance criterion 7), use a debug-only helper that counts descendants:
```python
def count_widgets(w):
    n, c = 1, w.get_first_child()
    while c: n += count_widgets(c); c = c.get_next_sibling()
    return n
```
Call it from a `--exit-after` hook in a test mode (for example `CALPI_TEST_MONTH_CYCLE=1` makes the app call `show_month` 12 times at startup and log the count before and after). Keep test hooks small and clearly named. Remove them if they turn out to be unnecessary.

### Step 10 — Visual check

1. `scripts/dev-run.sh`, open :8085, zoom the browser out to see the whole 1920×1080. Try `CALPI_FAKE_NOW` with dates in months that start on each weekday, and months that need 4, 5, or 6 rows (February 2026 with a Monday start needs 5 rows; February 2027 with a Monday start needs 4 rows plus 2 of next month's rows). Check that the dimming is right.
2. On the Pi (US-03): `scripts/pi deploy && scripts/pi screenshot`. Read the PNG. Then ask the owner to check readability from about 3 m. Adjust the CSS sizes if needed, and record the final values.

---

## Files

| File | Change |
|---|---|
| `calpi/data/timeutil.py`, `calpi/data/monthmath.py` | New |
| `calpi/widgets/header.py`, `day_cell.py`, `week_row.py`, `month_view.py` | New |
| `calpi/app.py` | The calendar screen is now `MonthView`. Placeholder removed |
| `calpi/style.css` | Grid styles |
| `tests/test_monthmath.py`, `tests/test_timeutil.py` | New |
| `scripts/smoke.sh` | Checks the `month_view: showing` line |

---

## Pitfalls

- **Using `date.today()` or `datetime.now()` directly** anywhere in the app. Always use `timeutil.today()`/`now()`, or the fake clock and the display zone are silently ignored. (A quick check before you finish: `grep -rn "date.today()\|datetime.now()" calpi/ | grep -v timeutil.py` should find nothing.)
- **Rebuilding the rows on every month change.** Mutate them instead (acceptance criterion 7).
- **Using `border` for today's highlight.** It changes the layout. Use an inset `box-shadow`.
- **A mismatch between `DAY_NUMBER_HEIGHT` and the CSS.** Events would overlap the day number (US-07). Keep them in sync.
- **Relying on `strftime`** for names. See D3.
- **Using a fixed-offset time zone.** Use `ZoneInfo`.

---

## Definition of done

- [ ] All acceptance criteria met. Unit tests pass. Smoke passes.
- [ ] Checked visually in Broadway for 4-, 5-, and 6-row months, and every week start.
- [ ] Pi screenshot reviewed, and the owner has confirmed readability (or handed over explicitly).
- [ ] The `grep` for direct `datetime.now()` / `date.today()` use is clean.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `timeutil.now()`, `today()`, `display_tz()`, `set_display_tz(name)`, `CALPI_FAKE_NOW`, `CALPI_TZ` | everything that deals with time: US-07, US-08, US-10, US-15, US-16, US-28, US-30 |
| `monthmath.month_grid_dates`, `add_months`, `month_title`, `MONTH_NAMES`, `WEEKDAY_SHORT`, `weekday_order` | US-07, US-08, US-09, US-28, US-39 |
| `MonthView.show_month(y, m)`, `refresh_today()`, `set_week_start(n)`, `visible_range()`, `year`/`month`, `month_changed_callbacks` | US-07, US-08, US-10, US-16, US-28, US-35 |
| `MonthView.header` with `start_slot`, `center_slot`, `end_slot` | US-08 (nav), US-16/17/19 (sync status), US-22 (settings button), US-39/40 (view switcher), US-41 (weather) |
| `WeekRow.content` (non-targetable overlay grid, 7 columns, `margin_top=DAY_NUMBER_HEIGHT`), `WeekRow.cells`, `WeekRow.dates` | US-07 |
| `DayCell.date` (and the cell being the click target) | US-09, US-11 |
| 6 rows always; cell about 274 × 152 px; `DAY_NUMBER_HEIGHT` | US-07 capacity calculation |
