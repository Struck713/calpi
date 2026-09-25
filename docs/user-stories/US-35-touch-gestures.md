# US-35 — Touch gestures

| | |
|---|---|
| **Epic** | 4. Touch and Polish |
| **Priority** | P2 |
| **Blocked by** | US-08 Month navigation, US-34 Touchscreen bring-up |
| **Blocks** | — |
| **Phase** | 4. Touch and Polish (optional extra) |

## Story

> As a user, I want to swipe between months on the touchscreen.

## Context

On a touchscreen, people expect to **swipe** the calendar sideways to change months. The buttons from US-08 keep working. This adds a gesture on the grid:
- swipe **left** (the finger moves right to left) → **next** month,
- swipe **right** → **previous** month.

Constraints that shape it:
- **No animation** (the Pi 3B's software renderer: US-02 D6 / the `gtk-kiosk-app` skill). The month changes **instantly** when the swipe ends. There's no dragging of the grid with the finger.
- **Taps on day cells must keep working** (US-09 opens a day on `released`). A swipe that starts on a cell must **not** open that day. A tap must **not** be taken for a swipe.
- **Vertical movement** is ignored (the grid doesn't scroll, but a slightly diagonal tap mustn't turn into a swipe).
- While the screen is asleep at night (US-30), the wake catcher swallows the first touch. Swipes only apply when it's awake.

US-08 provides `MonthView.go_relative(delta, reason)`. US-34 has checked real touch and provides the touch test screen, which is handy for tuning the thresholds.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-08** Month navigation | `MonthView.go_relative(±1, reason)`, the inactivity reset on input, the `nav:` log line | `grep -n "def go_relative" calpi/widgets/month_view.py` |
| **US-34** Touchscreen bring-up | A working, accurate touchscreen on the Pi, the recorded device facts, the dev touch test screen, and the finger-only walkthrough | `docs/platform-versions.md` has the Touchscreen section, and US-34's hand-off lists the walkthrough as OK |

### Soft dependencies
- **US-09**: the day-cell `GestureClick` that acts on `released`. The swipe must cancel it (D2).
- **US-39** (week view): if it exists, add the same gesture there (next/previous week) through the shared helper (D4).
- **US-30**: the wake catcher is above everything, so there's nothing to do. Check it.

### External blockers
- **The owner's help** for testing on the real touchscreen (the thresholds are tuned by feel).

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Swipes also open the day where they started | The drag gesture must **claim** the event sequence once it's clearly a horizontal swipe (`gesture.set_state(Gtk.EventSequenceState.CLAIMED)`), which cancels the cell's `GestureClick`. Make sure the drag gesture sits on an **ancestor** of the cells (the weeks container), and runs in the **capture** phase so it sees the sequence. |
| Taps get swallowed | The drag gesture must **not** claim until the movement passes the threshold. Before that, it stays `NONE`, so the click gesture completes normally. |
| The gesture doesn't fire in Broadway with the mouse | By design, `set_touch_only(True)`. For testing with the mouse, set `CALPI_SWIPE_MOUSE=1` (dev), which sets `touch_only=False`. |

---

## Scope

### In scope
- `calpi/data/gestures.py` (pure): `classify_swipe(dx, dy, dt_s) -> -1 | 0 | +1`.
- `calpi/widgets/swipe.py`: `attach_horizontal_swipe(widget, on_swipe)`, which wraps a `Gtk.GestureDrag` with claim logic.
- Hooking it onto the month grid's weeks container.
- The dev mouse flag.
- Tuning the thresholds on the real touchscreen.

### Out of scope
- Animated transitions or following the finger.
- Swipes in the day detail (scrolling conflicts). Consider it only if the owner asks.
- Vertical swipes, and pull-to-refresh.

---

## Acceptance criteria

1. On the touchscreen, a horizontal swipe on the grid of at least **150 px** (about 8 % of the width) that is mostly horizontal (`|dx| ≥ 2·|dy|`), done within **1 s**, changes the month: leftward → next, rightward → previous. It's logged as `nav: month -> YYYY-MM (reason=swipe)`.
2. **Fast flicks** count even if they're shorter: ≥ 80 px with a velocity ≥ 800 px/s.
3. **Taps** (movement < 20 px) open the day as before (US-09). Diagonal or vertical movements and slow drags (> 1 s) do nothing.
4. A swipe that starts on a day cell **never** opens that day (claiming cancels the click).
5. One swipe = one month (no repeats while the finger keeps moving).
6. The mouse doesn't trigger swipes (touch only) unless `CALPI_SWIPE_MOUSE=1` is set.
7. Swipes reset the inactivity timer (they're input, and US-08's monitor sees the events).
8. `classify_swipe` is unit-tested at the threshold edges.
9. The owner confirms on the real touchscreen: 20 swipes each way → at least 19 recognised; 20 taps on cells → 20 day openings, no month changes.

---

## Design decisions (already made)

- **D1. Thresholds** (constants in `gestures.py`, tunable): `MIN_DIST = 150`, `FLICK_DIST = 80`, `FLICK_VELOCITY = 800` px/s, `MAX_DURATION = 1.0` s, `DIRECTION_RATIO = 2.0`, `CLAIM_DIST = 40` (the movement at which the gesture claims the sequence, if it's horizontal-dominant).
- **D2. `Gtk.GestureDrag`** in `PropagationPhase.CAPTURE` on the **weeks container** (the parent of all `WeekRow`s, US-06). `drag-update`: once `|dx| ≥ CLAIM_DIST` and `|dx| ≥ DIRECTION_RATIO·|dy|` → claim (cancels child click gestures). `drag-end`: classify with the total `dx`, `dy`, and elapsed time (from `drag-begin`), then call `on_swipe(direction)` if it's non-zero **and** the gesture had claimed.
- **D3. Timing** from the events' timestamps if they're available (`gesture.get_current_event_time()` in ms), otherwise `time.monotonic()`.
- **D4. A reusable helper** `attach_horizontal_swipe(widget, on_swipe, touch_only=True) -> Gtk.GestureDrag`, for US-39's week view.

---

## Implementation plan

### Step 1 — Pure classifier + tests
```python
def classify_swipe(dx: float, dy: float, dt: float) -> int:
    """Return +1 (next: finger moved left), -1 (previous), or 0."""
    if dt <= 0 or dt > MAX_DURATION: return 0
    if abs(dx) < DIRECTION_RATIO * abs(dy): return 0
    v = abs(dx) / dt
    if abs(dx) >= MIN_DIST or (abs(dx) >= FLICK_DIST and v >= FLICK_VELOCITY):
        return +1 if dx < 0 else -1
    return 0

def should_claim(dx: float, dy: float) -> bool:
    return abs(dx) >= CLAIM_DIST and abs(dx) >= DIRECTION_RATIO * abs(dy)
```
Tests: exactly at the thresholds, just below, diagonal (dx=200, dy=110 → 0), slow (dt=1.2 → 0), flick (dx=-90, dt=0.08 → +1), a tap (dx=5 → 0), and the sign conventions.

### Step 2 — The helper (`calpi/widgets/swipe.py`)
```python
def attach_horizontal_swipe(widget, on_swipe, touch_only=True):
    g = Gtk.GestureDrag()
    g.set_touch_only(touch_only and os.environ.get("CALPI_SWIPE_MOUSE") != "1")
    g.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    st = {"t0": 0.0, "claimed": False}
    def begin(gest, x, y): st.update(t0=time.monotonic(), claimed=False)
    def update(gest, dx, dy):
        if not st["claimed"] and should_claim(dx, dy):
            gest.set_state(Gtk.EventSequenceState.CLAIMED); st["claimed"] = True
    def end(gest, dx, dy):
        if not st["claimed"]: return
        d = classify_swipe(dx, dy, time.monotonic() - st["t0"])
        if d: on_swipe(d)
    g.connect("drag-begin", begin); g.connect("drag-update", update); g.connect("drag-end", end)
    widget.add_controller(g)
    return g
```
Wrap the callbacks with try/except + logging (they're signal handlers, not GLib sources, but exceptions should still never propagate). Keep a reference to the gesture on the widget (`widget._swipe = g`), so it isn't collected.

Check `set_state` on a `GestureDrag` (a `GestureSingle` subclass) cancels the sibling `GestureClick` on the child cells. That's GTK's documented behaviour for gestures on the same event sequence. **Confirm it with the real touchscreen** (acceptance criterion 4).

### Step 3 — Hook it up in `MonthView`
`attach_horizontal_swipe(self.weeks_box, lambda d: self.go_relative(d, reason="swipe"))`. `weeks_box` is the vertical box holding the week rows (US-06 D2). Keep a reference to it in `MonthView` if it's currently a local variable.

### Step 4 — Tune it on the device
Deploy. Ask the owner to swipe and tap as in acceptance criterion 9, while you watch the `nav:` and `screen=day` log lines. If swipes are missed, lower `MIN_DIST`/`CLAIM_DIST` a little. If taps turn into swipes, raise `CLAIM_DIST`. Record the final values and the pass rate.

Optionally, use US-34's touch test screen to log `(dx, dy, dt)` for a few natural swipes (add a DEBUG log in `end`), and choose the thresholds from real data.

### Step 5 — Week view (only if US-39 exists)
`attach_horizontal_swipe(week_view.grid_area, lambda d: week_view.go_relative(d, reason="swipe"))`.

---

## Files

| File | Change |
|---|---|
| `calpi/data/gestures.py` | New |
| `calpi/widgets/swipe.py` | New |
| `calpi/widgets/month_view.py` | Attaches the swipe to the weeks box |
| `tests/test_gestures.py` | New |

---

## Pitfalls

- **Claiming too early**: taps stop working.
- **Attaching to each cell** instead of the container: 42 gestures, and a swipe across cells gets lost.
- **Animating the change.** Don't.
- **Testing only with `CALPI_SWIPE_MOUSE`**: the real touchscreen behaves differently. The acceptance test is with fingers.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] The owner's swipe and tap test passed (numbers recorded), with the final thresholds noted.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `attach_horizontal_swipe(widget, on_swipe, touch_only=True)` | US-39 (week view), US-40 (optional) |
| `gestures.classify_swipe`, the thresholds | same |
