# US-08 — Month navigation

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P0 |
| **Blocked by** | US-06 Month grid |
| **Blocks** | US-35 Touch gestures |
| **Phase** | 1. Foundation |

## Story

> As a user, I want to move to the previous or next month, and have the view return to the current month after a period of inactivity.

## Context

A wall calendar is mostly looked at, not touched. When someone does move to another month (to check next month's holiday, say), the device must **go back to the current month on its own** after a while, or the next person walking past sees the wrong month and doesn't notice. That automatic return is the more important half of this story.

This story adds:
1. **Previous / Today / Next** buttons in the header's `center_slot` (US-06).
2. Keyboard shortcuts (the test monitor has a keyboard; US-11 makes sure all input works everywhere).
3. `calpi/inactivity.py`: a reusable **InactivityMonitor** that notices *any* user input on the window and calls back after N seconds of no input. US-09 (day detail), US-22 (settings), and US-30 (wake on touch) reuse it.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-06** Month grid | `MonthView.show_month(y, m)`, `year`/`month`, `header.center_slot`, `monthmath.add_months`, `timeutil.today()` | `grep -n "def show_month\|center_slot\|def add_months" calpi/widgets/month_view.py calpi/widgets/header.py calpi/data/monthmath.py` finds all three. `scripts/smoke.sh` passes. |

### Soft dependencies
- **US-05** Settings store: the timeout should come from the `inactivity_return_seconds` setting. If US-05 is done, register the key (default 120, valid range 30–3600) and read it. **If it isn't, use a module constant `DEFAULT_RETURN_SECONDS = 120` and a `set_timeout()` method**, and note in the hand-off that the setting still has to be connected. There's no settings UI for it in P0 (it's fine as a hidden setting).
- **US-07**: when it's done, a month change reloads events through `month_changed_callbacks`. Nothing to do here.
- **US-11** (input) comes after this story or alongside it. Build the buttons with `Gtk.Button`, which works with mouse, touch, and keyboard. US-11 then checks sizes and focus.

### External blockers
None.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Key presses don't arrive | Keyboard focus is inside another widget that swallows the keys, or the window isn't focused (Broadway: click the page first). Use a `Gtk.ShortcutController` with scope `GLOBAL` or `MANAGED` on the window, or a key controller on the window in the **capture** phase. |
| The inactivity controller swallows clicks | A capture-phase controller must **not** claim or stop events. With `Gtk.EventControllerLegacy`, return `False` from the `event` handler. |
| The return fires while the user is still reading | Check that `motion` events count as activity, and that the timer is **reset** on every input, not just started once. |

---

## Scope

### In scope
- Header buttons: `‹` (previous), `Today`, `›` (next), wired to `MonthView`.
- Keyboard: `Left`/`Page_Up` → previous, `Right`/`Page_Down` → next, `Home`/`t` → today.
- `calpi/inactivity.py`: `InactivityTracker` (pure logic) + `InactivityMonitor` (GLib/GTK wiring).
- Returning to the current month after `inactivity_return_seconds` of no input, while the `calendar` screen (or the `day` screen, once US-09 exists) is showing.

### Out of scope
- Swipe gestures (US-35).
- Returning from Settings or the wizard (US-22 decides its own policy using the same monitor).
- Transition animations (never).

---

## Acceptance criteria

1. The header shows three buttons in its centre: `‹`, `Today`, `›`. Each is at least **88 × 72 px**.
2. Clicking or tapping `‹` / `›` shows the previous / next month straight away. Year boundaries work (December 2026 → January 2027 and back).
3. `Today` shows the month containing `timeutil.today()`. When that month is already showing, `Today` is **insensitive** (greyed out, and not clickable) but stays in place, so the layout doesn't jump.
4. Keyboard: `Left`/`Page_Up` = previous, `Right`/`Page_Down` = next, `Home` or `t` = today. They work when the calendar screen is showing, with no extra click first. They do **not** act while a text entry has focus (later stories add entries).
5. With no user input (pointer motion, click, touch, key, or scroll) for `inactivity_return_seconds` (default **120 s**), while the `calendar` screen shows a month other than the current one, the view goes back to the current month. **Any** input resets the countdown.
6. If the current month is already showing, the inactivity return does nothing (no reload and no log noise).
7. The monitor adds **one** coarse timer (for example every 5 s, using `GLib.timeout_add_seconds`), and **doesn't** create timers on each input event. Idle CPU use stays close to zero.
8. `InactivityTracker` is unit-tested with an injected clock (no GTK).
9. Navigation limits: years are kept within 1970–2100. At the limit, the corresponding button is insensitive.
10. The log records `nav: month -> YYYY-MM (reason=button|key|inactivity|today)` at INFO.

---

## Design decisions (already made)

- **D1. Button glyphs**: `‹` (U+2039) and `›` (U+203A) in DejaVu Sans at 44 px. Check that they render on the Pi (DejaVu has them). The word "Today" is text. **No icon theme is needed.**
- **D2. The monitor watches the whole window** with a single `Gtk.EventControllerLegacy` in `PropagationPhase.CAPTURE`. It sees every event before any widget does, records the activity time, and returns `False` so the event carries on normally.
  - Events that count as activity: `MOTION_NOTIFY`, `BUTTON_PRESS`, `BUTTON_RELEASE`, `TOUCH_BEGIN`, `TOUCH_UPDATE`, `KEY_PRESS`, `SCROLL`. Check these `Gdk.EventType` names against the installed PyGObject, and fall back to "any event except enter/leave/focus" if a name is missing.
- **D3. The tracker uses `time.monotonic()`**, never wall-clock time. That way NTP jumps at boot (the Pi has no RTC) can't trigger or suppress a return.
- **D4. Several listeners** can register with different timeouts: `monitor.add_idle_callback(seconds, callback) -> handle`. Each fires **once** per idle period and re-arms after the next input. US-22 and US-30 use this.
- **D5. What the return does** (in `MainWindow`, not in the monitor): if `navigator.current in ("calendar", "day")`, then `navigator.reset("calendar")` and `month_view.show_month(today)` if needed. For other screens it does nothing (their own stories decide).
- **D6. `Today` insensitive vs hidden**: insensitive (D3 in the acceptance criteria), so the header doesn't jump.

---

## Implementation plan

### Step 1 — `calpi/inactivity.py`: pure tracker first

```python
class InactivityTracker:
    """Pure logic. `clock` returns monotonic seconds (injectable for tests)."""
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._last = clock()
        self._listeners: dict[int, list] = {}   # handle -> [seconds, callback, fired]
        self._next = 1

    def touch(self) -> None:
        self._last = self._clock()
        for l in self._listeners.values():
            l[2] = False                         # re-arm

    def idle_seconds(self) -> float:
        return self._clock() - self._last

    def add(self, seconds: float, callback) -> int:
        h = self._next; self._next += 1
        self._listeners[h] = [seconds, callback, False]
        return h

    def remove(self, handle: int) -> None:
        self._listeners.pop(handle, None)

    def set_timeout(self, handle: int, seconds: float) -> None:
        if handle in self._listeners: self._listeners[handle][0] = seconds

    def check(self) -> None:
        idle = self.idle_seconds()
        for l in list(self._listeners.values()):
            seconds, cb, fired = l
            if not fired and idle >= seconds:
                l[2] = True
                try: cb()
                except Exception: log.exception("inactivity callback failed")
```

### Step 2 — The GTK wrapper

```python
class InactivityMonitor:
    CHECK_INTERVAL_S = 5
    def __init__(self, window: Gtk.Window):
        self.tracker = InactivityTracker()
        ctl = Gtk.EventControllerLegacy()
        ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        ctl.connect("event", self._on_event)
        window.add_controller(ctl)
        GLib.timeout_add_seconds(self.CHECK_INTERVAL_S, safe_callback(self._check, repeat=True))

    _ACTIVITY = {...}   # set of Gdk.EventType values (D2)

    def _on_event(self, _ctl, event) -> bool:
        if event.get_event_type() in self._ACTIVITY:
            self.tracker.touch()
        return False            # never consume

    def _check(self):
        self.tracker.check()

    # passthroughs
    def add_idle_callback(self, seconds, cb): return self.tracker.add(seconds, cb)
    def remove(self, h): self.tracker.remove(h)
    def poke(self): self.tracker.touch()          # for programmatic "activity" (e.g. wake from dim)
```
With a 5 s check interval, the return happens between 120 and 125 s. That's fine.

Keep the per-event work tiny: one set lookup and one assignment. Motion events can arrive at 60+ per second from a mouse.

Put **one** monitor on the window (`MainWindow.inactivity`), created in `MainWindow.__init__`.

### Step 3 — Header buttons

In `MonthView` (or a small `MonthNav` widget in `month_view.py`):
```python
self.btn_prev  = Gtk.Button(label="‹", css_classes=["nav-button", "nav-arrow"])
self.btn_today = Gtk.Button(label="Today", css_classes=["nav-button", "nav-today"])
self.btn_next  = Gtk.Button(label="›", css_classes=["nav-button", "nav-arrow"])
for b in (self.btn_prev, self.btn_today, self.btn_next): self.header.center_slot.append(b)
self.btn_prev.connect("clicked", lambda *_: self.go_relative(-1, reason="button"))
self.btn_next.connect("clicked", lambda *_: self.go_relative(+1, reason="button"))
self.btn_today.connect("clicked", lambda *_: self.go_today(reason="button"))
```
Methods:
```python
MIN_YEAR, MAX_YEAR = 1970, 2100
def go_relative(self, delta: int, reason: str) -> None:
    y, m = monthmath.add_months(self.year, self.month, delta)
    if not (MIN_YEAR <= y <= MAX_YEAR): return
    self.show_month(y, m); log.info("nav: month -> %04d-%02d (reason=%s)", y, m, reason)

def go_today(self, reason: str) -> None:
    t = timeutil.today()
    if (self.year, self.month) != (t.year, t.month):
        self.show_month(t.year, t.month); log.info(...)

def is_current_month(self) -> bool: ...
```
Update the button sensitivity at the end of `show_month` (the `Today` button, and the arrows at the year limits). Use a small helper that only calls `set_sensitive` when the value changes.

CSS:
```css
.nav-button { min-width: 88px; min-height: 72px; font-size: 28px; border-radius: 16px;
              background: @surface; color: @text; border: none; box-shadow: none; }
.nav-arrow  { font-size: 44px; padding: 0 12px; }
.nav-button:active { background: shade(@surface, 1.4); }   /* instant press feedback, no transition */
.nav-button:disabled { opacity: 0.3; }
```
GTK's default theme (Adwaita, built in) adds gradients, borders, and transitions to buttons. Override `background`, `border`, and `box-shadow`, and make sure `transition: none` applies globally, as a guard: `* { transition: none; }`. (GTK 4.8+ supports `transition` in CSS. Check that the `*` rule doesn't cause warnings.)

### Step 4 — Keyboard

In `MainWindow`, a `Gtk.ShortcutController` with `set_scope(Gtk.ShortcutScope.GLOBAL)`? **No**: global shortcuts would fire while an entry has focus. Use a `Gtk.EventControllerKey` on the **MonthView** (so it only acts while the month view is visible and focused), plus make sure `MonthView` can take focus (`set_focusable(True)`, and `grab_focus()` in `on_show`).

Alternative (simpler and more robust): one key controller on the window in the **bubble** phase. It only receives keys that no child handled (entries handle their own keys), and it checks `navigator.current == "calendar"` before acting:
```python
def _on_key(self, _ctl, keyval, _code, state) -> bool:
    if self.navigator.current != "calendar": return False
    name = Gdk.keyval_name(keyval)
    if name in ("Left", "Page_Up"):    self.month_view.go_relative(-1, "key"); return True
    if name in ("Right", "Page_Down"): self.month_view.go_relative(+1, "key"); return True
    if name in ("Home", "t"):          self.month_view.go_today("key"); return True
    return False
```
**Use this bubble-phase window controller.** Watch out: `Gtk.Button` uses `Left`/`Right` for focus movement when a button has focus. The bubble phase means the button gets them first. Test it: after clicking `›` (which focuses the button), `Right` should still change the month. If it moves focus instead, switch the controller to the **capture** phase and skip it when the focus widget is a `Gtk.Editable` (`isinstance(self.get_focus(), Gtk.Editable)`).

### Step 5 — The automatic return

In `MainWindow.__init__`, after the month view exists:
```python
self.inactivity = InactivityMonitor(self)
self._return_handle = self.inactivity.add_idle_callback(self._return_seconds(), self._on_idle_return)

def _on_idle_return(self):
    if self.navigator.current in ("calendar", "day"):
        if self.navigator.current != "calendar":
            self.navigator.reset("calendar")
        self.month_view.go_today(reason="inactivity")
```
If US-05 is done: `_return_seconds()` reads `settings.get(K_INACTIVITY_RETURN_SECONDS)`, and a `settings.subscribe(...)` calls `inactivity.tracker.set_timeout(handle, new)`.

### Step 6 — Tests

`tests/test_inactivity.py` with a fake clock (a list you can move forward):
- No callback before the timeout. Exactly one call after it. No second call while idle continues. Re-armed after `touch()`, then called again after another timeout.
- Two listeners with different timeouts fire independently.
- `remove` stops the calls. `set_timeout` changes the threshold.
- An exception in one callback doesn't stop the others.

`tests/test_month_nav.py`: `go_relative` year wrap-around (this needs GTK. Make it `@pytest.mark.gtk`, **or** factor the arithmetic into `monthmath.add_months`, which US-06 already tests, and keep the widget logic thin). Prefer the second option.

GTK smoke (`CALPI_GTK_TESTS=1`): a test hook that, with `CALPI_TEST_NAV=1`, calls `go_relative(+1)` at startup, waits for an inactivity timeout set to a few seconds (by setting the timeout to 3 s through the test hook), and logs the month. Check the log contains `reason=inactivity`. **Keep the hook tiny**, or skip it and do the check by hand in Broadway, documenting what you did.

### Step 7 — Manual checks

- Broadway: click `›` three times, wait 2 minutes without moving the mouse over the page → back to the current month. Move the mouse over the page now and then while waiting → no return.
- Pi (US-03): the same with the test monitor's mouse and keyboard. Record the observed time to return.

---

## Files

| File | Change |
|---|---|
| `calpi/inactivity.py` | New |
| `calpi/widgets/month_view.py` | Nav buttons, `go_relative`, `go_today`, `is_current_month` |
| `calpi/app.py` | `MainWindow.inactivity`, key controller, idle return |
| `calpi/data/settings_store.py` | `K_INACTIVITY_RETURN_SECONDS` (if US-05 is done) |
| `calpi/style.css` | Nav button styles, global `transition: none` |
| `tests/test_inactivity.py` | New |

---

## Pitfalls

- **Wall-clock time in the tracker.** Use monotonic time (D3).
- **Returning `True` from the capture controller.** That swallows every click in the app.
- **A timer per event.** Use one periodic check (acceptance criterion 7).
- **The Today button disappearing** and the header re-laying out. Make it insensitive instead.
- **Keys acting inside text entries** (later stories). The bubble phase plus the screen check prevents it.

---

## Definition of done

- [ ] All acceptance criteria met. Inactivity tests pass.
- [ ] Checked in Broadway and on the Pi with the mouse and keyboard.
- [ ] The inactivity return observed on the Pi (time recorded).

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `MainWindow.inactivity` (`add_idle_callback(seconds, cb) -> handle`, `remove(handle)`, `poke()`, `tracker.set_timeout`) | US-09, US-22, US-30, US-32 |
| `MonthView.go_relative(delta, reason)`, `go_today(reason)`, `is_current_month()` | US-10, US-35, US-39 |
| `K_INACTIVITY_RETURN_SECONDS` (default 120) | US-22 (if a UI is ever added) |
| The window-level key controller (bubble phase, checks `navigator.current`) | US-09, US-11 (the pattern to follow for screen-specific keys) |
| `.nav-button` CSS class (large, flat, instant `:active` feedback) | US-09, US-22, and everything with buttons |
