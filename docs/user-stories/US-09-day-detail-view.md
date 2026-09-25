# US-09 — Day detail view

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P1 |
| **Blocked by** | US-07 Events in the grid |
| **Blocks** | — |
| **Phase** | 1. Foundation (P1: needed before the device counts as finished) |

## Story

> As a user, I want to open a day and see all of its events in full when they don't fit in the grid cell.

## Context

A month cell holds about 4 short lines. Busy days show "+N more", and long titles are cut off. The day detail view is where you tap to see **everything** about one day: full titles, times with start and end, locations, which calendar each event comes from, and notes.

It's a new screen, `day`, in the navigator (US-02). You reach it by tapping or clicking a day cell (or its "+N more"), and you leave it with a back button, the Escape key, or automatically after inactivity (US-08 already returns from `day` to `calendar`).

It reuses a lot: the event store query (US-04), `layout.covered_days` and the formatting helpers (US-07), `CalendarColors` (US-07), and the button styles and window key-controller pattern (US-08).

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-07** Events in the grid | Events drawn in cells. `formatting.long_time`/`short_time`, `layout.covered_days`, a shared `CalendarColors` instance, `MonthView.reload()`, and the `.bar`/`.line`/`.dot` CSS | `/usr/bin/python3 -m pytest tests/test_layout.py tests/test_formatting.py` passes. With sample data in Broadway, the busy day shows "+N more". |

(US-07 depends on US-04 and US-06, so the store, the grid, and `DayCell.date` are all there too.)

### Soft dependencies
- **US-08**: the inactivity return from `day` → `calendar`, the `.nav-button` style, and the bubble-phase window key controller. If US-08 isn't done, add the back button and Escape handling here, and leave the automatic return to US-08 (it already lists `day`).
- **US-11**: touch sizes and making tap/click equivalent. Use `Gtk.GestureClick`, which handles touch and mouse the same way, and US-11 is covered.
- **US-16**: a sync can finish while the detail view is open. Provide `DayDetail.reload()` so US-16 can refresh it (acceptance criterion 8).

### External blockers
None.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Clicks on cells don't arrive | The US-06 content layer must be `can_target=False`. If it isn't, fix it in `week_row.py`: that's a US-06 contract. |
| The scrolled list doesn't scroll with touch in Broadway | Broadway has no touch. Test scrolling with the mouse wheel and scrollbar dragging there, and check touch in US-34. `Gtk.ScrolledWindow` has kinetic scrolling on by default. |
| Long descriptions (HTML from some calendars, very long notes) make the screen slow | Cap the description (D5). Show plain text only. |

---

## Scope

### In scope
- `calpi/widgets/day_detail.py`: the `DayDetail` screen.
- Tapping a day cell (anywhere in the cell, including its events and "+N more", because the content layer is non-targetable) opens the detail view for that date.
- Previous/next day buttons, back, and keys.
- Full event details: time range, title (wrapped), location, calendar name and colour, a note excerpt, multi-day context, tentative status.
- Reloading on data change (`reload()`).

### Out of scope
- Editing events (out of scope for the whole project).
- Maps, links, and attendees.
- Swipe between days (possible later with US-35. Don't add it now).

---

## Acceptance criteria

1. Tapping or clicking **any day cell** (in or out of the displayed month) shows the `day` screen for that date. It appears in **under 150 ms** on the Pi for a day with 10 events.
2. The header shows the full date, for example "Tuesday, 15 September 2026", plus "Today" / "Tomorrow" / "Yesterday" when that applies, and three buttons: `← Back` (left), `‹` and `›` (previous and next day, right). All are at least 88 × 72 px.
3. Events are listed in the store's order (US-04 D6): all-day and multi-day first, then timed. Each row shows:
   - a calendar colour marker (a vertical bar or a dot, using the calendar's CSS class),
   - the time: "All day", or "09:30 – 10:45" (in the configured 12h/24h format, US-07's `long_time`). An event that ends on a later day gets a suffix: "22:30 – 01:00 (+1 day)". A multi-day event shows "Day 2 of 3" and its full range ("Mon 14 – Wed 16 Sep"),
   - the **full title**, wrapping over up to 3 lines (ellipsized after that),
   - the location (if there is one), in dimmed text, one line, ellipsized,
   - the calendar's name,
   - the description (if there is one): **plain text, the first 300 characters, at most 4 lines**, ellipsized,
   - tentative events marked "(tentative)" and dimmed.
4. A day with no events shows "No events" in the middle of the screen.
5. If the events don't fit on one screen, the list scrolls vertically (mouse wheel, scrollbar drag, touch). The header stays fixed.
6. `Escape` or `BackSpace` → back to the calendar. `Left`/`Right` → previous/next day. They're only active while `day` is showing.
7. Going back returns to the month that was showing (not necessarily the current month), unless the inactivity return (US-08) already reset it.
8. `DayDetail.reload()` rebuilds the list if the store's revision changed since the list was built. Otherwise it does nothing.
9. Opening and closing the view 200 times doesn't increase the widget count, and doesn't leak (checked with a test hook or by hand: see Testing).
10. Moving to the previous/next day past a month boundary also moves the underlying month view to that month (so "Back" lands on the month of the day you ended up on).

---

## Design decisions (already made)

- **D1. One `DayDetail` instance** is created at startup and added to the navigator as `day`. `on_show(date=...)` fills it in. It's never recreated.
- **D2. The rows are rebuilt** on each `on_show` and `reload()`. A day holds at most a few dozen events, so pooling is optional. **But** the old rows must be removed from the list box so they're freed. Use `Gtk.Box` rows inside a `Gtk.Box` list (not `Gtk.ListView`: a factory-based list is overkill here and heavier to set up), and remove children with a `while (c := box.get_first_child()): box.remove(c)` loop.
- **D3. Opening the day**: a `Gtk.GestureClick` on each `DayCell` (7 × 6 = 42 gestures, created once in US-06's widgets). On `released`, when the pointer is still inside the cell, call `on_day_activated(date)`. Use `released`, not `pressed`, so a press that turns into a swipe (US-35) doesn't open the day. (US-35 will make the swipe claim the sequence, which cancels the click.)
- **D4. Which events a day has** = `store.events_for_days(d, d + 1 day, tz)`. The multi-day context comes from `layout.covered_days(event, tz)`: "Day k of n" with k = (d - first_day).days + 1.
- **D5. Descriptions** can contain HTML (some Exchange/Outlook-origin events do) or huge text. Remove tags with a simple regex (`<[^>]+>` → a space), unescape entities (`html.unescape`), collapse whitespace, cut to 300 characters, and set the label to `wrap=True`, `lines=4`, `ellipsize=END`. **Never** use `Gtk.Label.set_markup` with event text: server text isn't trusted, and Pango markup would interpret `<` and `&`. Use `set_text` only.
- **D6. Relative day words** ("Today", "Tomorrow", "Yesterday") come from comparing with `timeutil.today()` when the view is shown and when it's reloaded.

---

## Implementation plan

### Step 1 — Tap handling on day cells (`day_cell.py` / `month_view.py`)

```python
# DayCell.__init__
self.activate_callback = None
click = Gtk.GestureClick()
click.set_button(0)                          # any button; touch counts as button 1 emulation
click.connect("released", self._on_released)
self.add_controller(click)

def _on_released(self, gesture, n_press, x, y):
    if self.date is None or self.activate_callback is None: return
    w, h = self.get_width(), self.get_height()
    if 0 <= x <= w and 0 <= y <= h:
        self.activate_callback(self.date)
```
`MonthView` sets each cell's `activate_callback = self._on_day_activated`, which calls `window.navigator.show("day", date=d)`. Pass the navigator (or a callback) into `MonthView` when it's constructed. Don't reach up with `get_root()` in a hot path.

Add `cursor: pointer`? No: the cursor is hidden or managed by US-11. Add an `:active` style on `.day-cell` for press feedback (`background-color: alpha(@accent, 0.08)`).

### Step 2 — `calpi/widgets/day_detail.py`

```python
class DayDetail(Gtk.Box):
    def __init__(self, store, colors, navigator, month_view):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["screen", "day-detail"])
        self.store, self.colors, self.navigator, self.month_view = store, colors, navigator, month_view
        self.date: date | None = None
        self._built_key = None
        # header
        hdr = Gtk.CenterBox(css_classes=["header"])
        self.btn_back = Gtk.Button(label="← Back", css_classes=["nav-button"])
        self.title = Gtk.Label(css_classes=["day-title"])
        self.subtitle = Gtk.Label(css_classes=["day-subtitle"])
        tbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); tbox.append(self.title); tbox.append(self.subtitle)
        nav = Gtk.Box(spacing=16)
        self.btn_prev = Gtk.Button(label="‹", css_classes=["nav-button", "nav-arrow"])
        self.btn_next = Gtk.Button(label="›", css_classes=["nav-button", "nav-arrow"])
        nav.append(self.btn_prev); nav.append(self.btn_next)
        hdr.set_start_widget(self.btn_back); hdr.set_center_widget(tbox); hdr.set_end_widget(nav)
        # body
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["day-list"])
        self.empty = Gtk.Label(label="No events", css_classes=["day-empty"], vexpand=True)
        self.scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroller.set_child(self.list)
        for w in (hdr, self.scroller, self.empty): self.append(w)
        self.btn_back.connect("clicked", lambda *_: self.navigator.back())
        self.btn_prev.connect("clicked", lambda *_: self.shift(-1))
        self.btn_next.connect("clicked", lambda *_: self.shift(+1))

    def on_show(self, date: date | None = None, **_):
        if date is not None: self.date = date
        self._build(force=True)
        self.scroller.get_vadjustment().set_value(0)

    def on_hide(self):
        self._clear()                 # free the rows while hidden (memory, US-37)
        self._built_key = None

    def shift(self, days: int):
        self.date += timedelta(days=days)
        if (self.date.year, self.date.month) != (self.month_view.year, self.month_view.month):
            self.month_view.show_month(self.date.year, self.date.month)
        self._build(force=True)

    def reload(self):
        if self.navigator.current == "day": self._build(force=False)
```
`navigator.back()` returns to the previous screen (`calendar`). Check that US-02's `Navigator.back()` does this, and that it doesn't push `day` onto the history again when you move between days (`shift` doesn't call `navigator.show`, so it's fine).

### Step 3 — Building the rows

```python
def _build(self, force: bool):
    tz = timeutil.display_tz()
    key = (self.date, self.store.revision(), tz.key, formatting.time_format())
    if not force and key == self._built_key: return
    self._built_key = key
    self._set_titles()
    events = self.store.events_for_days(self.date, self.date + timedelta(days=1), tz)
    self._clear()
    for e in events: self.list.append(self._row(e, tz))
    set_visible_if_changed(self.empty, not events)
    set_visible_if_changed(self.scroller, bool(events))
```
The row:
```
Gtk.Box horizontal (css "event-row")
├─ Gtk.Box (css "cal-marker bar <cal-N>")   ← 8px wide, full height, uses the calendar's colour class
└─ Gtk.Box vertical
   ├─ Label time line     ("All day · Day 2 of 3 · Mon 14 – Wed 16 Sep" / "09:30 – 10:45")  css "event-time"
   ├─ Label title          wrap, lines=3, ellipsize END, xalign 0                           css "event-title"
   ├─ Label location       ellipsize END (only if non-empty)                                 css "event-meta"
   ├─ Label calendar name  (plus "(tentative)")                                             css "event-meta"
   └─ Label description    wrap, lines=4, ellipsize END (only if non-empty)                  css "event-notes"
```
Put the pure text-building helpers in `formatting.py` (tested without GTK):
- `time_range_text(event, day, tz) -> str`
- `multi_day_text(event, day, tz) -> str | None`
- `clean_description(text, limit=300) -> str` (D5)
- `relative_day_word(day, today) -> str | None`
- `long_date(day) -> str` → "Tuesday, 15 September 2026"

**The colour marker** reuses `CalendarColors` classes: `.bar.cal-N` sets `background-color`. Give the marker the classes `["cal-marker", "bar", cls]` and override the size in CSS (`.cal-marker { min-width: 8px; border-radius: 4px; padding: 0; margin: 0; }`). That way no second colour mechanism is needed.

### Step 4 — Keys

Extend the window key controller from US-08 (bubble phase):
```python
if self.navigator.current == "day":
    if name in ("Escape", "BackSpace"): self.navigator.back(); return True
    if name == "Left":  self.day_detail.shift(-1); return True
    if name == "Right": self.day_detail.shift(+1); return True
```

### Step 5 — Register the screen and the reload hooks

In `MainWindow`: create `DayDetail(store, colors, navigator, month_view)`, then `navigator.add("day", ...)`. Provide an app-level `on_data_changed()` that calls `month_view.reload()` and `day_detail.reload()`. US-16 will call it after each sync. (If US-16 already exists and calls only `month_view.reload()`, change it to call `on_data_changed()`.)

### Step 6 — CSS

```css
.day-title    { font-size: 48px; font-weight: 300; }
.day-subtitle { font-size: 24px; color: @accent; }
.day-list     { padding: 16px 64px 48px 64px; }
.event-row    { background: @surface; border-radius: 14px; padding: 16px 20px; }
.cal-marker   { min-width: 8px; border-radius: 4px; margin: 0 20px 0 0; padding: 0; }
.event-time   { font-size: 24px; color: @text_dim; }
.event-title  { font-size: 34px; }
.event-meta   { font-size: 22px; color: @text_dim; }
.event-notes  { font-size: 22px; color: @text_faint; margin-top: 6px; }
.day-empty    { font-size: 36px; color: @text_faint; }
.day-cell:active { background-color: alpha(@accent, 0.08); }
```

### Step 7 — Tests

`tests/test_formatting.py` additions:
- `time_range_text`: a same-day event (24h and 12h), crossing midnight → "(+1 day)", all-day → "All day".
- `multi_day_text`: day 2 of 3; the first and last days; a one-day event → `None`.
- `clean_description`: HTML tags removed, `&amp;` unescaped, whitespace collapsed, cut at 300 characters with "…".
- `relative_day_word`: today/tomorrow/yesterday/None.
- `long_date` format.

GTK checks (by hand in Broadway, or with a `CALPI_GTK_TESTS` hook):
- With sample data: click the busy day → 9 rows, scrollable. Click an empty day → "No events". Move with `›` across the end of the month → the underlying month changes (Back shows the new month).
- **Leak check** (acceptance criterion 9): a dev hook `CALPI_TEST_DAY_CYCLE=200` that opens and closes the day view 200 times at startup and logs `count_widgets(window)` (the helper from US-06) before and after. It must be equal. Also log the RSS from `/proc/self/statm` before and after (a small increase is fine; steady growth over repeated runs isn't).

### Step 8 — Pi check (US-03)

Deploy with sample data. Take a screenshot of the day view for the busy day (use a test hook, or ask the owner to click). Measure the open time: log `perf: day_open NN ms` (measured until after-paint, like `month_render`). The target is < 150 ms.

---

## Files

| File | Change |
|---|---|
| `calpi/widgets/day_detail.py` | New |
| `calpi/widgets/day_cell.py` | `GestureClick`, `activate_callback` |
| `calpi/widgets/month_view.py` | Wires the cell activation |
| `calpi/app.py` | Registers the `day` screen, key handling, `on_data_changed()` |
| `calpi/data/formatting.py` | Detail text helpers |
| `calpi/style.css` | Detail styles |
| `tests/test_formatting.py` | New cases |

---

## Pitfalls

- **`set_markup` with event text.** Use `set_text` only (D5).
- **Opening on `pressed`.** It breaks the swipe later (D3).
- **Not clearing the rows on hide.** Memory slowly grows over weeks (US-37).
- **Showing UTC times.** Always `astimezone(tz)` using `timeutil.display_tz()`.
- **Pushing history on every day step**, so "Back" walks back through each day. Only `navigator.show` pushes history. `shift` must not call it.

---

## Definition of done

- [ ] All acceptance criteria met. The formatting tests pass.
- [ ] The leak check done (numbers in the hand-off notes).
- [ ] Pi screenshot and open-time measurement recorded.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| The `day` screen: `navigator.show("day", date=d)` | US-39 (week view taps), US-40 (agenda taps) |
| `DayDetail.reload()`, `MainWindow.on_data_changed()` | US-10, US-16, US-26, US-28 |
| `formatting.time_range_text`, `multi_day_text`, `clean_description`, `long_date`, `relative_day_word` | US-39, US-40 |
| `DayCell.activate_callback` and the tap-on-`released` pattern | US-11, US-35 |
