# US-11 — Pointer and touch input

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P0 |
| **Blocked by** | US-02 App skeleton |
| **Blocks** | US-21 On-screen keyboard, US-22 Settings shell, US-34 Touchscreen bring-up |
| **Phase** | 1. Foundation |

## Story

> As a user, I want every control to work with touch as well as a mouse and keyboard, so the app works on both the test monitor and the touchscreen.

## Context

The device is being developed on a **non-touch** portable monitor with a mouse and keyboard, and it will end up on a **touchscreen** with no mouse or keyboard at all. Every screen has to work in both setups from the start. Retro-fitting touch at the end is how kiosk apps end up with tiny buttons and hover-only menus.

This story sets the **input conventions** for the whole app and puts them in code:
1. **The cursor policy**: invisible for touch, visible while a mouse is being used, and hidden again when the mouse is idle.
2. **Target sizes**: everything tappable is at least 72 × 72 px, and a checker finds violations.
3. **No hover dependence**, and no "sticky hover" after a tap.
4. **Instant press feedback** (`:active` styles, with no transitions).
5. **Keyboard**: a single `KeyRouter` sends keys to the current screen. There's a visible focus ring for keyboard users, and `Escape` always means "back".
6. **Gesture rules**: taps act on release, there are no long-presses or double-taps, and scrolling works with the wheel, scrollbar drag, and touch drag.

It also goes back over what already exists (US-06/08/09 widgets, if they're done) and brings it in line with the rules.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-02** App skeleton | `MainWindow` (with the cursor currently set to `none` for good), `style.css`, `widgets/util.py`, `--exit-after`, `smoke.sh` | `grep -n 'new_from_name("none"' calpi/app.py` finds the current cursor line. `scripts/smoke.sh` → `SMOKE OK` |

### Soft dependencies
- **US-06, US-08, US-09**: if they're done, move their key handling into the `KeyRouter` (step 4) and check their targets with the size checker. If not, those stories must follow the conventions written here. Their files already point to US-11.
- **US-03**: needed to test the cursor behaviour under cage with the real mouse (acceptance criteria 1–3).
- **US-34**: real touch testing happens there, on the touchscreen. Here, touch is **emulated** (step 6).

### External blockers
- **The test monitor with a USB mouse and keyboard connected to the Pi**, for acceptance criteria 1–3 on hardware. Ask the owner to plug them in.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| The cursor stays visible under cage even after `set_cursor(none)` | cage draws a cursor from the client's cursor surface. If `none` doesn't hide it, try `Gdk.Cursor.new_from_texture` with a 1×1 transparent texture. Record which one works on the Pi's cage version. |
| You can't tell touch events from mouse events | `event.get_device().get_source()` returns `Gdk.InputSource.TOUCHSCREEN` / `MOUSE` / `TOUCHPAD`. For touch, the event type is also `TOUCH_BEGIN`/`TOUCH_UPDATE`/`TOUCH_END`. **Emulated pointer events** that GTK creates from touch come from the touchscreen device, so the source check is reliable. Test it in US-34. |
| There's no touch device for testing | See step 6: GTK's debug flag. Final checks are in US-34. |
| Adwaita (GTK's built-in theme) styles fight yours | GTK 4 always loads its built-in Adwaita CSS. Override with more specific selectors, or at the app priority. Test `button:hover` and `button:active`. |

---

## Scope

### In scope
- `calpi/input.py`: `CursorManager`, `KeyRouter`, `is_touch(event)`, the target-size checker (dev only).
- CSS conventions: `.touch-target`, neutralised `:hover`, `:active` feedback, `:focus-visible` rings, `* { transition: none; }`.
- Conventions written into the module docstring **and** into the "Contracts" section below.
- Bringing existing widgets in line (month nav, day cells, day detail).
- Emulated-touch testing notes.

### Out of scope
- The on-screen keyboard (US-21).
- Swipes (US-35).
- Touchscreen hardware set-up, orientation, and calibration (US-34).

---

## Acceptance criteria

1. **Cursor**: with no mouse connected, no cursor is ever visible. With a mouse, the cursor **appears on the first mouse motion**, and **disappears 3 s after the last mouse motion** or at once on any touch event. It never appears because of touch.
2. The cursor logic adds no timers while the mouse is idle: one GLib timeout is scheduled after motion and replaced on later motion, with at most one pending at a time.
3. With the mouse on the Pi: every existing control (nav buttons, day cells, day detail buttons, scrolling) works with left-click. The **mouse wheel scrolls** the day detail list.
4. **Targets**: every `Gtk.Button`, and every widget with a click gesture, is at least **72 × 72 px** when allocated, except where one axis is explicitly allowed to be smaller (list rows ≥ 72 px tall and full width). The dev checker (`CALPI_CHECK_TARGETS=1`) logs `input: small target <widget> WxH` for violations, and there are **none** on the calendar and day screens.
5. **Keyboard**: `Tab`/`Shift+Tab` moves focus between controls, with a clearly visible focus ring (3 px accent outline). `Enter`/`Space` activates the focused button. `Escape` goes back (from `day`, and later from settings) and never quits the app. Screen shortcuts (the month and day arrows) are handled by `KeyRouter` through the current screen's `on_key`.
6. **Hover**: no information or action is reachable only by hovering. `:hover` looks the same as the normal state (so there's no sticky highlight after a tap). There are no tooltips.
7. **Press feedback**: every tappable control changes appearance **immediately** when pressed (`:active`), with no transition.
8. **Activate on release**: tapping a control and dragging off it before releasing doesn't activate it (GTK buttons already behave this way; day cells check the release position, see US-09 D3).
9. **No long-press or double-tap** anywhere in the app (a code search for `GestureLongPress` and `n_press == 2` finds nothing).
10. Emulated touch (step 6) in Broadway or on the Pi: the nav buttons and day cells work, and the cursor stays hidden.

---

## Design decisions (already made)

- **D1. Cursor states**: `HIDDEN` (the default) and `VISIBLE`. `VISIBLE` on a motion event whose device source is `MOUSE` or `TOUCHPAD`. `HIDDEN` after `CURSOR_HIDE_S = 3` s with no mouse motion, or at once on any event from a `TOUCHSCREEN` source. Visible cursor = the default arrow (`Gdk.Cursor.new_from_name("default")`). Hidden = `none` (or the transparent-texture fallback).
- **D2. One capture-phase `Gtk.EventControllerLegacy`** on the window does the cursor handling. **Reuse the same controller as US-08's inactivity monitor**, if it exists: give `InactivityMonitor` a hook list (`event_hooks`), and register the cursor handler there, so each event goes through **one** Python callback instead of two. (If US-08 isn't done, create the controller here in `input.py`, and US-08 adds its hook.)
- **D3. `KeyRouter`**: one `Gtk.EventControllerKey` on the window (bubble phase). On `key-pressed`, it calls `navigator.get(current).on_key(keyname, state)` if that method exists. If that returns False, it applies the global keys: `Escape` → `navigator.back()` unless the current screen is `calendar`. Screens own their shortcuts. **US-08/US-09's handlers move into `MonthView.on_key` and `DayDetail.on_key`.**
- **D4. Minimum target: 72 × 72 px.** At 1080p on a 15–22" panel, 72 px is about 13–18 mm, above the common 9–10 mm minimum for touch. That leaves room for imprecise taps on a wall-mounted screen. The primary controls (nav, back) are larger (88 × 72).
- **D5. Spacing**: at least 16 px between neighbouring targets, so a tap never lands between two controls ambiguously.
- **D6. The focus ring only for the keyboard**: use `:focus-visible` (GTK 4 sets it only after keyboard navigation). Style: `outline: 3px solid @accent; outline-offset: 2px;`.
- **D7. CSS globals** (at the top of `style.css`):
  ```css
  * { transition: none; animation: none; }
  button:hover { background-image: none; }         /* no sticky hover: match the normal state */
  ```
  plus per-component `:active` styles.
- **D8. No tooltips.** Don't call `set_tooltip_text` anywhere.

---

## Implementation plan

### Step 1 — `calpi/input.py`: `CursorManager`

```python
class CursorManager:
    HIDE_AFTER_MS = 3000
    def __init__(self, window: Gtk.Window):
        self._window = window
        self._hidden = self._make_hidden_cursor()
        self._arrow = Gdk.Cursor.new_from_name("default", None)
        self._visible = False
        self._timer_id = 0
        self._apply(False)

    def _make_hidden_cursor(self):
        c = Gdk.Cursor.new_from_name("none", None)
        return c   # fallback: 1x1 transparent texture (see blockers) if "none" doesn't hide on cage

    def on_event(self, event) -> None:
        et = event.get_event_type()
        dev = event.get_device()
        src = dev.get_source() if dev else None
        if src == Gdk.InputSource.TOUCHSCREEN or et in _TOUCH_TYPES:
            self._apply(False); return
        if et == Gdk.EventType.MOTION_NOTIFY and src in (Gdk.InputSource.MOUSE, Gdk.InputSource.TOUCHPAD):
            self._apply(True)
            self._restart_timer()

    def _restart_timer(self):
        if self._timer_id:
            GLib.source_remove(self._timer_id)
        self._timer_id = GLib.timeout_add(self.HIDE_AFTER_MS, self._on_hide_timer)

    def _on_hide_timer(self):
        self._timer_id = 0
        self._apply(False)
        return GLib.SOURCE_REMOVE

    def _apply(self, visible: bool):
        if visible == self._visible and self._window.get_cursor() is not None: return
        self._visible = visible
        self._window.set_cursor(self._arrow if visible else self._hidden)
```
**Performance**: `_restart_timer` on every motion event removes and re-adds a GLib source. That's cheap, but motion can arrive at 125 Hz. Optimisation (required): store `self._last_motion = time.monotonic()`, and only create the timer if none is pending. When the timer fires, check whether `monotonic() - _last_motion >= 3 s`. If it isn't, re-arm it for the remaining time. That way there's at most one timer and no churn.

`Gdk.Cursor.new_from_name` takes `(name, fallback)` in GTK 4. `new_from_name("none", None)` is what US-02 used.

### Step 2 — Hook it into the shared event controller

If US-08's `InactivityMonitor` exists: add `self.event_hooks: list[Callable[[Gdk.Event], None]]` to it, call each hook inside `_on_event`, and register `cursor.on_event`. **Keep `_on_event` cheap** (a type check, then the hooks).

If it doesn't exist yet: create a `WindowEventHub` in `input.py` with the legacy controller and the hook list. The inactivity monitor (US-08) then registers with the hub. Either way there's **one** capture controller for the window.

### Step 3 — Replace US-02's permanent hidden cursor

In `MainWindow.__init__`: remove `self.set_cursor(Gdk.Cursor.new_from_name("none", None))` and create `self.cursor = CursorManager(self)`, which starts hidden.

### Step 4 — `KeyRouter`

```python
class KeyRouter:
    def __init__(self, window, navigator):
        self._nav = navigator
        ctl = Gtk.EventControllerKey()      # bubble phase (default): entries get keys first
        ctl.connect("key-pressed", self._on_key)
        window.add_controller(ctl)

    def _on_key(self, _ctl, keyval, _keycode, state) -> bool:
        name = Gdk.keyval_name(keyval) or ""
        screen = self._nav.get(self._nav.current)
        handler = getattr(screen, "on_key", None)
        try:
            if handler and handler(name, state):
                return True
        except Exception:
            log.exception("on_key failed for %s", self._nav.current)
        if name == "Escape" and self._nav.current != "calendar":
            self._nav.back(); return True
        return False
```
Move the US-08/US-09 key logic into `MonthView.on_key` and `DayDetail.on_key` (return True when handled). Remove the old window-level handler. **Check again that `Left`/`Right` still change the month after a nav button has keyboard focus** (see US-08 step 4). If a focused `Gtk.Button` eats the arrow keys, use `set_propagation_phase(Gtk.PropagationPhase.CAPTURE)` on this controller **and** skip routing when `window.get_focus()` is a `Gtk.Editable` (text entries in later stories must get their own keys).

### Step 5 — CSS and the size audit

Add to `style.css`:
```css
* { transition: none; animation: none; }
button { min-width: 72px; min-height: 72px; }             /* baseline; components may go larger */
button:hover { background-image: none; }
button:focus-visible, .day-cell:focus-visible { outline: 3px solid @accent; outline-offset: 2px; }
.touch-target { min-width: 72px; min-height: 72px; }
```
Be careful with the global `button { min-width: 72px }`: GTK uses buttons inside some composite widgets (spin buttons, scrollbar steppers, the entry clear icon). If something looks broken, limit the rule to `.screen button` and see which widgets are affected.

**The size checker** (dev only, `CALPI_CHECK_TARGETS=1`): 2 s after each `navigator.show`, walk the widget tree of the visible screen. For every `Gtk.Button`, and every widget that has a `Gtk.GestureClick` controller (look through `widget.observe_controllers()`: a `Gio.ListModel` you can iterate), check `get_width()` and `get_height()` against 72 and log violations. Mark allowed exceptions with a CSS class `.target-exempt` (for example the whole-row targets that are full width but only 72 px tall are fine: check `max(w, h) >= 72 and min(w, h) >= 72`, and exempt narrow decorative widgets that aren't clickable).

### Step 6 — Emulated touch testing

GTK 4 has a debug flag that treats the mouse as a touchscreen. Check the exact name on the installed version: `GTK_DEBUG=help /usr/bin/python3 run.py --windowed` prints the list. Look for `touchscreen`. If it's there:
```bash
GTK_DEBUG=touchscreen scripts/dev-run.sh
```
Check that the buttons and cells work, the cursor stays hidden (in Broadway the browser draws its own cursor, so check the logs: add a DEBUG line `input: cursor visible=%s` in `_apply`), and scrolling works by dragging.

If the flag doesn't exist, note that, and leave touch checks to US-34.

### Step 7 — Checks on the Pi with a mouse and keyboard (US-03)

1. Deploy. With the mouse **unplugged**: take a screenshot. `grim` doesn't capture the cursor by default, so **ask the owner to look** at the physical screen: there should be no cursor.
2. Plug the mouse in. Move it: the cursor appears. Stop: it disappears after about 3 s (the owner watches).
3. Click through: nav buttons, a day cell, back, the day arrows, scroll the busy day with the wheel.
4. Keyboard: Tab through the controls (the focus ring is visible), Enter activates, Escape goes back from `day`, and the arrows move months and days.
5. Run with `CALPI_CHECK_TARGETS=1` (a temporary drop-in; **remove it afterwards**) and check `scripts/pi logs | grep "small target"` finds nothing.

### Step 8 — Write down the conventions

Put a short "Input conventions" docstring at the top of `calpi/input.py`, and a section in the README if you think it helps. Later stories (US-21 onwards) have to follow them:
- Use `Gtk.Button` for anything you press. If a custom widget has to be clickable, use `Gtk.GestureClick` and act on `released` inside the bounds.
- Targets ≥ 72 × 72 px, with ≥ 16 px spacing.
- Instant `:active` feedback. No hover dependence, no tooltips.
- No long-press or double-tap.
- Screen keys through `on_key(name, state) -> bool`. `Escape` = back.
- Scrollable content goes in a `Gtk.ScrolledWindow` (kinetic scrolling on).

---

## Files

| File | Change |
|---|---|
| `calpi/input.py` | New: `CursorManager`, `KeyRouter`, the size checker, the event hub (if needed) |
| `calpi/inactivity.py` | `event_hooks` (if US-08 is done) |
| `calpi/app.py` | Uses `CursorManager` and `KeyRouter`. The old cursor line and key handler removed |
| `calpi/widgets/month_view.py`, `day_detail.py` | `on_key` methods (if they exist) |
| `calpi/style.css` | Global input rules |

---

## Testing

- Unit test (no display): the timing logic of `CursorManager` can be split into a pure `CursorPolicy` class (fed events as `(source, type, t)` tuples, it returns the desired visibility and the next check time). Test: touch hides it, mouse motion shows it, hidden after 3 s, and further motion extends the time without creating extra timers (count the timer requests).
- `KeyRouter`: a test with fake navigator and screen objects (pure Python, if you pass the keyval name in, and keep `_on_key`'s Gdk call in a thin wrapper).
- Manual checks as in steps 6–7, recorded in the hand-off notes.

---

## Pitfalls

- **Two capture controllers** (inactivity and cursor). Merge them into one (D2).
- **A GLib timer per motion event.** Use the "one pending timer" approach (step 1).
- **Global `button` min-size breaking GTK's composite widgets.** Scope it if needed.
- **Keys swallowed by focused buttons.** Test the arrows after clicking a button.
- **Escape quitting the app** (for example through a leftover dev shortcut). Only `Ctrl+Q` in `--windowed` mode quits.
- **Testing touch only in Broadway.** It has no real touch. The final check is US-34.

---

## Definition of done

- [ ] All acceptance criteria met, with the mouse and keyboard checked on the Pi.
- [ ] One capture controller for the window.
- [ ] No small targets reported on the existing screens.
- [ ] Conventions written in the `input.py` docstring.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| Input conventions (step 8) | every UI story from US-21 on |
| Screen `on_key(name, state) -> bool` through `KeyRouter`; `Escape` = back | US-21 (the OSK closes on Escape), US-22, US-32 |
| `window.cursor` (`CursorManager`) | US-30 (hide the cursor while dimmed), US-34 |
| One shared capture event hub (`event_hooks`) | US-30 (wake on touch), US-35 |
| `CALPI_CHECK_TARGETS=1` target checker | US-21 onwards (run it for each new screen) |
| `.touch-target`, `:focus-visible` ring, `* { transition: none }` | all UI stories |
