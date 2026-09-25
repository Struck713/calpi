# US-10 — Midnight rollover

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P0 |
| **Blocked by** | US-06 Month grid |
| **Blocks** | — |
| **Phase** | 1. Foundation |

## Story

> As a user, I want "today" and the displayed month to update on their own when the date changes.

## Context

The device runs for weeks without being restarted. If "today" were only worked out at startup, the marker would stay on the day the app started. At midnight the today marker must move, and on the first of the month the whole grid must move to the new month, all with nobody touching anything.

There are complications on this hardware:
- **The Pi 3B has no real-time clock.** At boot the clock starts from the last saved time (possibly hours or days old) and **jumps** when NTP syncs, maybe a minute after the app started. The date can change "suddenly", forwards or even backwards.
- **Time zone changes** (US-28), and daylight-saving changes, move local midnight.
- **Timers**: GLib timers use monotonic time. A timer set for "midnight" computed at startup would fire at the wrong wall-clock time after an NTP jump or a zone change.

The robust solution is a **clock service** that ticks on every minute boundary (recomputed on each tick, as in the skill's `example_app.py`), and on each tick compares the current local date with the last one it saw. Any difference means "the day changed". That covers midnight, NTP jumps, and zone changes the same way.

This story creates `calpi/clock.py` (`ClockService`), which later stories subscribe to: US-16 (the sync window rolls forward), US-30 (the dim schedule is checked each minute), US-39/40/41.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-06** Month grid | `timeutil.now()`/`today()`/`display_tz()` with the fake clock (`CALPI_FAKE_NOW`, **offset mode**, so time keeps moving), `MonthView.refresh_today()`, `show_month()`, `year`/`month` | `grep -n "_fake_offset\|def refresh_today" calpi/data/timeutil.py calpi/widgets/month_view.py`. The `timeutil` tests pass. |

### Soft dependencies
- **US-07**: after a day change, `MonthView.reload()` should run (the sync window and events can change). If US-07 is done, call `reload(force=True)`. If not, `refresh_today()` is enough.
- **US-08**: `is_current_month()` / `go_today()`. If US-08 isn't done, compare `(year, month)` directly.
- **US-09**: `DayDetail.reload()` refreshes "Today"/"Tomorrow". Call it through `MainWindow.on_data_changed()` if it exists.
- **US-28** will call `ClockService.notify_tz_changed()` after the display zone changes. Provide that method now.

### External blockers
None.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| You want to test midnight without waiting for midnight | `CALPI_FAKE_NOW=2026-09-30T23:59:30` + `--exit-after 45`. The fake clock keeps moving (offset mode, US-06), so the day changes 30 seconds after start. |
| A timer fires a little *before* the minute boundary | Add a small margin (+50 ms, as in `example_app.py`), and **compare dates rather than trusting that the timer fired at the boundary**. |
| Tests using GLib timers are slow or flaky | Test the pure detector with a fake `now()` function. Keep GLib to one integration test. |

---

## Scope

### In scope
- `calpi/clock.py`: `ClockService` with minute ticks, `day_changed`, `minute`, and `tz_changed` subscriptions, and jump detection.
- The pure logic in `calpi/data/timeutil.py` or a small `DayChangeDetector` (no gi).
- Wiring: on a day change, update the today marker; move the month if the user was looking at the "current" month; reload events; refresh the day detail.
- Logging of detected changes and clock jumps.

### Out of scope
- Showing a clock on screen (not requested).
- Setting the system time or zone (US-28).
- Rolling the sync window forward (US-16 subscribes to `day_changed`).

---

## Acceptance criteria

1. A single `ClockService` instance runs, and ticks at the start of every minute (±1 s) using **one** GLib timeout, rescheduled after each tick. No other part of the app creates its own per-minute timer: they subscribe to this one.
2. When the local date changes (midnight, NTP jump, or zone change), within **one minute** (normally < 2 s after midnight):
   - the today marker moves to the new date (`refresh_today()`),
   - if the grid was showing the month of the **old** today, and the new today is in a different month, the grid moves to the new current month,
   - if the grid was showing some other month (the user is browsing), the grid **stays** where it is (the inactivity return in US-08 brings it back later), but the marker is updated wherever the new today is visible,
   - the day detail's "Today"/"Tomorrow" words update if it's open,
   - `day_changed(old_date, new_date)` subscribers are called once.
3. A **wall-clock jump** of more than 90 s (forwards or backwards, compared with monotonic time elapsed) is logged at WARNING as `clock: wall clock jumped by +3h12m (NTP?)` and handled like any other tick (a day change if the date changed).
4. `notify_tz_changed()` (called by US-28) re-evaluates immediately: it runs a tick at once, and calls `tz_changed` subscribers, then `day_changed` subscribers if the local date differs.
5. Integration test: with `CALPI_FAKE_NOW=2026-09-30T23:59:30`, the app logs `clock: day changed 2026-09-30 -> 2026-10-01` and `month_view: showing 2026-10` within 45 s.
6. Integration test: with `CALPI_FAKE_NOW=2026-09-14T23:59:30` and the grid moved to November by a test hook, after midnight the grid **stays** on November, and the log shows the day change.
7. `minute` subscribers get the current aware `datetime` each tick (for US-30). A failing subscriber is logged and doesn't affect the others.
8. Across 24 hours on the Pi, exactly 1,440 ticks (±2) are logged at DEBUG (sample the count in the journal for one hour and check it's about 60), and idle CPU stays close to 0%.

---

## Design decisions (already made)

- **D1. Minute ticks recomputed each time** (from `example_app.py`): `delay_ms = (60 - now.second) * 1000 - now.microsecond // 1000 + 50`. Use `GLib.timeout_add` (ms), because `timeout_add_seconds` can fire up to a second late by design. Return `SOURCE_REMOVE`, and schedule the next tick inside the callback, **in a `finally`**, so an exception can never stop the clock.
- **D2. Detecting a date change**: keep `self._last_date = timeutil.today()`. On each tick, compute `today()`. If it differs, it's a day change. That handles everything: midnight, NTP jumps both ways, zone changes, and DST.
- **D3. Detecting a jump**: at each tick record `(time.monotonic(), timeutil.now())`. On the next tick compare the elapsed wall time with the elapsed monotonic time. A difference over 90 s is a jump. This is for logging and diagnosis only.
- **D4. Whether the user was "on the current month"** is decided with the **old** date: `was_current = (month_view.year, month_view.month) == (old.year, old.month)`. If `was_current` and the new date is in another month → `show_month(new)`. Otherwise → `refresh_today()`.
- **D5. Subscription API**: plain callables in lists (the same style as `month_changed_callbacks`). `subscribe_minute(cb)`, `subscribe_day_changed(cb)`, `subscribe_tz_changed(cb)`, each returning a handle, plus `unsubscribe(handle)`.
- **D6. The fake clock also moves the timer schedule**: `timeutil.now()` includes the fake offset, so `delay_ms` is computed from fake seconds. Because the offset is constant, the boundaries still line up. There's nothing special to do.

---

## Implementation plan

### Step 1 — Pure detector (`calpi/data/timeutil.py` or `calpi/data/daychange.py`, no gi)

```python
@dataclass
class TickResult:
    now: datetime
    day_changed: tuple[date, date] | None
    jump_seconds: float | None

class DayChangeDetector:
    JUMP_THRESHOLD_S = 90
    def __init__(self, now_fn=timeutil.now, mono_fn=time.monotonic):
        self._now, self._mono = now_fn, mono_fn
        n = now_fn()
        self._last_date, self._last_wall, self._last_mono = n.date(), n, mono_fn()

    def tick(self) -> TickResult:
        n, m = self._now(), self._mono()
        wall_elapsed = (n - self._last_wall).total_seconds()
        mono_elapsed = m - self._last_mono
        jump = wall_elapsed - mono_elapsed
        changed = None
        if n.date() != self._last_date:
            changed = (self._last_date, n.date())
            self._last_date = n.date()
        self._last_wall, self._last_mono = n, m
        return TickResult(n, changed, jump if abs(jump) > self.JUMP_THRESHOLD_S else None)

    def reset_date(self) -> tuple[date, date] | None:
        """For tz changes: re-read today() without a wall-clock comparison."""
        ...
```
Note: `n - self._last_wall` between two aware datetimes in **different zones** (after a zone change) is still correct, because Python compares the absolute instants. Good. The zone change doesn't look like a jump.

### Step 2 — `calpi/clock.py`

```python
class ClockService:
    def __init__(self):
        self.detector = DayChangeDetector()
        self._minute, self._day, self._tz = {}, {}, {}
        self._next_handle = 1
        self._schedule()

    def _schedule(self):
        n = timeutil.now()
        delay = (60 - n.second) * 1000 - n.microsecond // 1000 + 50
        GLib.timeout_add(max(delay, 50), self._on_timer)

    def _on_timer(self):
        try:
            self._tick()
        except Exception:
            log.exception("clock tick failed")
        finally:
            self._schedule()
        return GLib.SOURCE_REMOVE

    def _tick(self):
        r = self.detector.tick()
        log.debug("clock: tick %s", r.now.strftime("%Y-%m-%d %H:%M"))
        if r.jump_seconds is not None:
            log.warning("clock: wall clock jumped by %s (NTP?)", _fmt_delta(r.jump_seconds))
        self._call(self._minute, r.now)
        if r.day_changed:
            old, new = r.day_changed
            log.info("clock: day changed %s -> %s", old, new)
            self._call(self._day, old, new)

    def notify_tz_changed(self):
        log.info("clock: display time zone is now %s", timeutil.display_tz().key)
        self._call(self._tz)
        self._tick()          # picks up a date change caused by the zone change

    def _call(self, subs, *args):
        for cb in list(subs.values()):
            try: cb(*args)
            except Exception: log.exception("clock subscriber failed")
    # subscribe_minute / subscribe_day_changed / subscribe_tz_changed / unsubscribe ...
```
**Don't** use `@safe_callback` here: the `finally` rescheduling is the essential part, and it's clearer written out.

### Step 3 — Wiring in `MainWindow`

```python
self.clock = ClockService()
self.clock.subscribe_day_changed(self._on_day_changed)

def _on_day_changed(self, old: date, new: date):
    mv = self.month_view
    was_current = (mv.year, mv.month) == (old.year, old.month)
    if was_current and (new.year, new.month) != (old.year, old.month):
        mv.show_month(new.year, new.month)     # also reloads events via month_changed_callbacks (US-07)
    else:
        mv.refresh_today()
        if hasattr(mv, "reload"): mv.reload(force=True)
    if hasattr(self, "on_data_changed"): self.on_data_changed()   # day detail words etc.
```
Expose `app.clock` (or `window.clock`) so later stories can subscribe. Put it where US-16 and US-30 can reach it easily: **`CalpiApp.clock`**, created in `_on_activate` before the window.

### Step 4 — Tests

`tests/test_daychange.py` (pure):
- Fake `now_fn` / `mono_fn`: advance by 60 s at a time from 23:58 → a change reported exactly once, at 00:00.
- A wall jump of +3 h while mono advances 60 s → `jump_seconds ≈ 10740`, and the day changes if midnight was crossed.
- A backwards jump over midnight (00:05 → 23:50 the previous day) → a change reported (new < old). The consumer must cope: check that `_on_day_changed` doesn't assume `new > old` (it doesn't).
- A zone change: `now_fn` returns the same instant in a different zone, where the date differs → change reported, no jump.
- DST spring-forward and fall-back nights in `Europe/Berlin`: exactly one change at local midnight. No false jumps (wall time is compared as absolute instants).

GTK integration (`CALPI_GTK_TESTS=1`), add a script `scripts/test-midnight.sh`, or extend `smoke.sh` with a mode:
```bash
CALPI_FAKE_NOW=2026-09-30T23:59:30 SMOKE_SECONDS=45 scripts/smoke.sh
# then grep for "clock: day changed 2026-09-30 -> 2026-10-01" and "month_view: showing 2026-10"
```
For acceptance criterion 6 (browsing stays put), add a tiny test hook `CALPI_TEST_START_MONTH=2026-11` that makes `MonthView` start on that month. Check that after the change the log **doesn't** contain `month_view: showing 2026-10`.

### Step 5 — Pi check (US-03)

1. Deploy with `CALPI_FAKE_NOW` set through a temporary systemd drop-in:
   ```bash
   scripts/pi ssh 'sudo mkdir -p /etc/systemd/system/calpi-kiosk.service.d && printf "[Service]\nEnvironment=CALPI_FAKE_NOW=2026-09-30T23:59:00\n" | sudo tee /etc/systemd/system/calpi-kiosk.service.d/fakenow.conf && sudo systemctl daemon-reload'
   scripts/pi restart
   ```
   Wait 70 s, then take a screenshot: it should show October 2026 with the 1st marked.
2. **Remove the drop-in** (`sudo rm .../fakenow.conf && sudo systemctl daemon-reload && scripts/pi restart`). Double-check it's gone: `systemctl cat calpi-kiosk` mustn't show `CALPI_FAKE_NOW`.
3. Real midnight: leave it running overnight, and check `scripts/pi logs | grep "day changed"` the next morning. Take a screenshot.
4. NTP jump (optional; ask the owner): `sudo date -s '+2 hours'` then `sudo systemctl restart systemd-timesyncd`. Watch the log for the jump warning. **Put the time back right afterwards.**

---

## Files

| File | Change |
|---|---|
| `calpi/clock.py` | New |
| `calpi/data/daychange.py` (or inside `timeutil.py`) | New `DayChangeDetector` |
| `calpi/app.py` | `CalpiApp.clock`, the `_on_day_changed` wiring |
| `tests/test_daychange.py` | New |
| `scripts/smoke.sh` | A midnight mode, or a separate script |

---

## Pitfalls

- **One timer computed for midnight.** It breaks after NTP jumps and zone changes. Use minute ticks plus date comparison (D2).
- **Forgetting to reschedule after an exception.** The clock stops forever. Use `finally`.
- **Several per-minute timers** in different modules. Subscribe to the one clock.
- **Leaving the fake-clock drop-in on the Pi.** Always remove it and check.
- **Assuming dates only move forward.**

---

## Definition of done

- [ ] All acceptance criteria met. The pure tests and the midnight integration test pass.
- [ ] Fake-midnight check on the Pi done, **and the drop-in removed**.
- [ ] A real overnight rollover seen in the journal (can be done later, but note it).

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `app.clock.subscribe_minute(cb(now))` | US-30 (the dim schedule), US-31 (status refresh, optional), US-41 |
| `app.clock.subscribe_day_changed(cb(old, new))` | US-16 (roll the sync window), US-39, US-40 |
| `app.clock.subscribe_tz_changed(cb())`, `app.clock.notify_tz_changed()` | US-28 calls it. US-16 and others subscribe |
| The log lines `clock: day changed` and `clock: wall clock jumped` | US-31/US-38 diagnostics, US-37 soak test |
