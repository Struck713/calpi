# US-40 — Agenda view

| | |
|---|---|
| **Epic** | 5. Extras |
| **Priority** | P2 |
| **Blocked by** | US-07 Events in the grid |
| **Blocks** | — |
| **Phase** | 5. Extras (optional) |

## Story

> As a user, I want a scrolling list of upcoming events.

## Context

An agenda answers "what's next?" better than a grid: a list of upcoming events, grouped by day, with the full titles and times. On a wall display it's handy as an alternative default view ("show me the next two weeks").

Constraints:
- **Bounded content**: the `gtk-kiosk-app` skill warns against huge scrolling lists on the Pi. Show a fixed horizon (for example 30 days, and at most 200 events), and build the rows once per data change.
- **Kinetic touch scrolling** (`Gtk.ScrolledWindow`) with large rows.
- It fits in with the **view switcher and default view** from US-39 if those exist. Otherwise it adds a minimal switcher itself (D4).

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-07** Events in the grid | `EventStore.events_for_days`, `layout.covered_days`, `formatting.*` (`short_time`, `long_time`, `time_range_text`, `long_date`, `relative_day_word` if US-09 added them), `CalendarColors`/the `.cal-dot` CSS (US-26) or `.bar.cal-N`, `app.on_data_changed` | `grep -n "def events_for_days" calpi/data/event_store.py`; `grep -n "def covered_days" calpi/data/layout.py` |

### Soft dependencies
- **US-39**: `ViewSwitcher`, the `VIEWS` registry, `K_DEFAULT_VIEW`, and the generalised inactivity return. **If US-39 exists**, register `"agenda"` in them. **If not**, implement a minimal switcher (Month | Agenda) and `K_DEFAULT_VIEW` here with the same names and semantics, so US-39 can extend it later (D4).
- **US-09**: tapping a row opens the day detail.
- **US-10**: at midnight the agenda's start moves (today's past events drop off), plus "Today"/"Tomorrow" labels.
- **US-36**: `perf.until_paint("agenda_render")`.
- **US-28**: the time format and zone.

### External blockers
None.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Rebuilding 200 rows is slow on the Pi | Use `Gtk.ListBox` with lightweight rows (one `Gtk.Box` with 3 labels + a dot), and rebuild only when the data key changes. If it's still slow, cap the horizon at 14 days and 120 events and measure again (acceptance criterion 7). |
| Multi-day events would appear on every day they cover | Show them **once**, on the first visible day (today, if they started earlier), with a range text ("until Wed 16"). |

---

## Scope

### In scope
- `calpi/data/agenda.py` (pure): building the agenda items (grouping, dedupe of multi-day events, the horizon, and "now/next" markers).
- `calpi/widgets/agenda_view.py`: the `AgendaView` screen (`"agenda"`), with a header (title "Upcoming", the view switcher, and the same end slot as the other views), a scrolled list grouped by day, and a "No upcoming events" state.
- Registering the view (US-39's registry, or the minimal one) and the `default_view` option "Agenda".
- Refreshing on data changes and at midnight. The "now" marker refreshes every minute.

### Out of scope
- Infinite scrolling or loading older and further events. The horizon is fixed (a setting could come later).
- Search and filters.

---

## Acceptance criteria

1. The agenda shows the events from **now** until **30 days** ahead (at most **200** items), grouped under day headings ("Today", "Tomorrow", then "Thursday 17 September"). Days without events are left out.
2. **Row** (≥ 88 px): the calendar colour dot, the time ("All day", or "09:30 – 10:45" in the configured format), the title (up to 2 lines, then ellipsized), and the location (1 line, dimmed, if there is one). Tentative events are marked.
3. **Timed events already finished today** aren't shown. **Ongoing** events (started, not finished) are shown first under "Today" with a "Now" tag. The **next** upcoming event is highlighted slightly.
4. **Multi-day events** appear **once**: on the day they start, or under "Today" if they started earlier and are still going, with the range text (for example "Mon 14 – Wed 16" / "until Wed 16").
5. Scrolling works with a finger (kinetic), the mouse wheel, and dragging the scrollbar. Selecting and activating a row (tap/click) → the day detail for that event's day.
6. **Refreshing**: on `app.on_data_changed` (rebuilt only if `(revision, today, tz, time format, the current hour for the "now" split)` changed), at midnight (the day change), and every minute only to update the "Now" and ended markers (cheap: recompute and rebuild only if the set of visible items changed).
7. **Performance** on the Pi with real data: opening the agenda p90 ≤ 250 ms, and the list scrolls without visible stalls (the owner confirms on the touchscreen if US-34 is done, otherwise with the mouse).
8. The **view switcher** includes "Agenda". `K_DEFAULT_VIEW` accepts `"agenda"`. The app can start in the agenda. Inactivity returns to the default view (scrolled to the top).
9. Empty state: "No upcoming events in the next 30 days."
10. The pure item building is unit-tested (grouping, ended and ongoing, multi-day dedupe, the cap, DST days).

---

## Design decisions (already made)

- **D1. The horizon**: `[now, today + 30 days)` in the display zone. `AGENDA_DAYS = 30`, `AGENDA_MAX_ITEMS = 200`. If it's capped, the last row reads "More events after <date>…" (not tappable, or it opens the day detail of the last date).
- **D2. Items** (pure):
  ```python
  @dataclass(frozen=True)
  class AgendaItem: event: Event; day: date; kind: str   # "ongoing" | "upcoming" | "allday" | "multiday"
                    time_text: str; range_text: str | None; is_next: bool
  def build_agenda(events, now, tz, days=30, cap=200) -> list[tuple[date, list[AgendaItem]]]: ...
  ```
  The order within a day follows US-04 D6 (all-day first), except that ongoing events go first under "Today".
- **D3. The widgets**: `Gtk.ScrolledWindow` → `Gtk.ListBox` (`selection_mode=NONE`, `activate-on-single-click`), with `Gtk.ListBoxRow`s for the day headings (not activatable) and the items. They're rebuilt only when the item key tuple changes.
- **D4. Without US-39**: create `calpi/widgets/view_switcher.py` with `VIEWS = [("month", "calendar", "Month"), ("agenda", "agenda", "Agenda")]` (view id, screen name, label), and `K_DEFAULT_VIEW` with a validator based on `VIEWS`. Put the same generalised inactivity return in `MainWindow` that US-39 describes. US-39 then only appends `("week", "week", "Week")`.

---

## Implementation plan

1. **The pure builder** (`calpi/data/agenda.py`) + `tests/test_agenda.py`: events ending before `now` today are excluded; ongoing first; multi-day dedupe (an event from Mon 14 to Wed 16, with now = Tue 15 → one item under Today, `range_text` "until Wed 16"); all-day today is included all day; the cap and the truncation marker; day headings via `relative_day_word`/`long_date`; `is_next` = the first upcoming timed item after now; a DST day in `Europe/Berlin`.
2. **`AgendaView`**:
   ```python
   class AgendaView(Gtk.Box):
       def __init__(self, app, window): ... header (title "Upcoming", ViewSwitcher, end-slot items), scroller → listbox, empty label
       def on_show(self, **_): self.reload(force=True); self.scroller.get_vadjustment().set_value(0)
       def reload(self, force=False):
           now = timeutil.now(); tz = timeutil.display_tz()
           key = (app.store.revision(), now.date(), tz.key, formatting.time_format(), now.hour, now.minute // 5)
           if not force and key == self._key: return
           groups = agenda.build_agenda(app.store.events_for_days(now.date(), now.date() + timedelta(days=30), tz), now, tz)
           item_key = tuple((d, tuple((i.event.uid, i.event.recurrence_id, i.kind, i.is_next) for i in items)) for d, items in groups)
           if item_key != self._item_key: self._rebuild(groups); self._item_key = item_key
           self._key = key
   ```
   The minute ticks call `reload()`. It rebuilds only when the visible item set changes (D2/acceptance criterion 6). `row-activated` → `navigator.show("day", date=item.day)`.
3. **Register it**: `navigator.add("agenda", AgendaView(...))`. Switcher and default view per D4 (or US-39's). The Preferences "Start with" row gains "Agenda".
4. **CSS**: `.agenda-day-heading { font-size: 30px; color: @accent; padding: 24px 48px 8px; }`, `.agenda-row { min-height: 88px; padding: 12px 48px; }`, `.agenda-row.next { background: alpha(@accent, 0.08); }`, `.agenda-now-tag { ... }`.
5. **Pi check**: a screenshot with real data. Opening time (`perf`). Scroll smoothness (the owner). Midnight rollover (fake clock drop-in, **removed afterwards**: the US-10 method) → Today's heading moves.

---

## Files

| File | Change |
|---|---|
| `calpi/data/agenda.py` | New |
| `calpi/widgets/agenda_view.py` | New |
| `calpi/widgets/view_switcher.py` | New or extended (D4) |
| `calpi/app.py` | Registers `agenda`, default view, inactivity |
| `calpi/widgets/settings/preferences.py` | "Start with: Agenda" |
| `calpi/data/settings_store.py` | `K_DEFAULT_VIEW` (if not done by US-39) |
| `calpi/style.css` | Agenda styles |
| `tests/test_agenda.py` | New |

---

## Pitfalls

- **Unbounded lists.** Cap the horizon and the item count (D1).
- **Rebuilding every minute.** Only when the visible set changes.
- **Repeating multi-day events on every day.**
- **Using `set_markup` with event titles** (untrusted text). Use `set_text` only.
- **Forgetting to scroll back to the top** on inactivity return.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] A Pi screenshot, opening timing, and a scroll check recorded.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `agenda.build_agenda(...)` | a possible "next events" widget in the month header (future) |
| `VIEWS` registry (if created here) | US-39 |
