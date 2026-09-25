# US-30 — Overnight dim and sleep schedule

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P1 |
| **Blocked by** | US-29 Brightness control |
| **Blocks** | — (adds a step to US-32's wizard if US-32 is already done) |
| **Phase** | 4. Touch and Polish |

## Story

> As a user, I want the display to dim or turn off overnight on a schedule I choose, and wake when touched.

## Context

A bright calendar in a hallway or kitchen at 3 a.m. is annoying, and it wastes power. The owner sets a nightly window (for example 22:30–06:30) and chooses what happens in it:
- **Dim**: the screen stays on at a low brightness (for example 10 %), so it's still readable if you look.
- **Turn off**: the display is powered down (or goes black if it can't be powered down).

During the night window, **touching the screen** (or moving the mouse, or pressing a key) **wakes it** for a few minutes, then it goes back to the night state. The **first touch only wakes the screen**: it must not also press whatever button happened to be under the finger in the dark.

US-29 provides the brightness controller (with `set_override`) and the backend's `power()` where it exists. This story adds:
1. `calpi/system/display_power.py`: the ways to turn the output **off and on**, probed for what works on this compositor and screen.
2. `calpi/dimming.py`: the **schedule controller** (a pure state machine plus GLib wiring through `app.clock` minute ticks and `window.inactivity`).
3. The **wake catcher**: an invisible full-screen layer that swallows the first input while in the night state.
4. An **Overnight** group in Settings → Display, and the **wizard step** (if US-32 exists).

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-29** Brightness control | `app.brightness` (`set_override`, `level`, `backend_name`, `supports_power_off`, `backend.power`), `window.dim_layer`, the Display section (extensible with groups), `K_BRIGHTNESS`, the provisioning pattern | `grep -n "def set_override" calpi/system/brightness.py`. Settings → Display shows Brightness on the Pi, and `scripts/pi logs \| grep "brightness: backend="` shows the probed backend. |

### Soft dependencies

| Soft blocker | Why | If it isn't done |
|---|---|---|
| **US-10** `app.clock.subscribe_minute` | Evaluating the schedule every minute | Required in practice (P0, done earlier). |
| **US-08/US-11** `window.inactivity` + the shared event hub (`event_hooks`) | Detecting activity for the wake timeout, and the global input hook | Required in practice. |
| **US-22** rows, the ListPicker | Time pickers | It came with US-29. |
| **US-32** wizard | The dimming step ("added once US-30 is done") | If US-32 **exists**: add the step (step 7). If **not**: leave a note for US-32 to include `DimSchedulePanel`. |
| **US-34** touchscreen | Real "wake by touch" | Test with the mouse and keyboard here. Check again with touch in US-34. |

### External blockers

| Blocker | What to do |
|---|---|
| **Which "screen off" methods work** on this compositor and monitor | Probe them on the Pi (step 1): `wlopm` (the wlr output power management protocol; needs cage support), backlight `bl_power`, DDC VCP `0xD6`, `wlr-randr --off`. Record the results in `docs/platform-versions.md`. |
| **Whether touch still works while the display is off** | Some portable touch monitors cut power to their touch controller in standby, and then **touch can't wake them**. You can only check that with the final touchscreen (US-34). Design for it: "Turn off" mode shows a warning if waking hasn't been confirmed (D6). |
| **`wlopm` or `wayland-utils` packages** | `apt-cache policy wlopm wayland-utils`. If `wlopm` isn't packaged, skip that method (don't build it from source). |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| `wlr-randr --output HDMI-A-1 --off` makes the GTK window lose its output, and after `--on` the layout is wrong or the app crashes | That's a known risk with disabling the only output. Prefer DPMS-style methods (`wlopm`, `bl_power`, DDC `D6`) that keep the mode. If only `wlr-randr` works, test the on/off cycle 20 times (step 1), and use it only if it's reliable. Otherwise fall back to the black overlay (D4). |
| The first tap in the dark opens a day or presses a button | The wake catcher must be **above** everything, **targetable**, and visible whenever the screen is in the night state. The tap is consumed by it. |
| The schedule crosses midnight and DST | Use the pure `in_window(now_local, start, end)` with `start > end` meaning "crosses midnight". Evaluate from `timeutil.now()` each minute (US-10 pattern), which handles DST and NTP jumps. |

---

## Scope

### In scope
- `calpi/system/display_power.py`: the probe plus `off()`/`on()` for the methods in D3.
- `calpi/dimming.py`: `DimSchedule` (pure) and `DimController` (GLib).
- The wake catcher overlay.
- The settings key `K_DIM_SCHEDULE` (a dict) and its validator.
- An "Overnight" group in the Display section: enable, mode, start, end, night brightness, wake duration, and "Preview".
- `DimSchedulePanel` for the wizard, plus the wizard step if US-32 exists.
- Provisioning of any needed package (`wlopm`, if available).

### Out of scope
- Several schedules, or different schedules per weekday. (Possible later. Keep the data model extensible, D1.)
- Motion or light sensors.
- Stopping sync at night (sync continues).

---

## Acceptance criteria

1. **Settings → Display → Overnight** has: **Overnight mode** (switch), **When** (start and end times in 30-minute steps through full-page pickers, default 22:30 → 06:30), **Mode** (`Dim` | `Turn off`: "Turn off" is disabled with "Not supported on this screen" if no off-method was found), **Night brightness** (5–50 %, default 10 %, only for Dim), **Stay awake after touch** (1 / 5 / 15 minutes, default 5), and **Preview** (applies the night state for 10 s).
2. **Evaluated every minute** (through `app.clock` minute ticks) **and** immediately when the settings change, at startup, and after a zone change. `in_window` handles windows that cross midnight (22:30–06:30) and ones that don't (13:00–14:00). A window with start == end is invalid (rejected by the validator).
3. **Entering night**: Dim → `app.brightness.set_override(night_level)`. Turn off → `display_power.off()` using the best available method (D3). The wake catcher is shown. Logged at INFO: `dim: night (mode=off, method=wlopm)`.
4. **Leaving night** (at the end time): the override is cleared (`set_override(None)`) or `display_power.on()`, the wake catcher is hidden, and it's logged.
5. **Waking**: during night, any input (touch, click, mouse motion, key) → the screen goes back to normal (`override None` / power on) within **1 s**. The **first** touch or click is **swallowed** (it doesn't activate anything underneath). Mouse motion and key presses wake it too (the wake catcher only swallows clicks and touches; keys are swallowed while it's still asleep).
6. **Going back to sleep**: after `wake_minutes` with no input (`window.inactivity` idle callback), if still inside the window → back to the night state (and the wake catcher shown again).
7. **At boot inside the window**: the device starts in the night state, **after** the first frame (the screen must come on briefly at power-on, so the owner can see it boots. Wait **30 s** after READY before applying night at boot).
8. **Robustness**: if `display_power.off()` fails, fall back to Dim at the minimum brightness, log a WARNING, and use the same fallback for the rest of the night. If `on()` fails, retry 3 times over 10 s, then restart the output with the most reliable method (`wlr-randr --on`), and log an ERROR. The display must never be stuck off outside the window.
9. **Pure logic is tested**: `in_window` (crossing midnight, boundaries, DST days in `Europe/Berlin`), the state machine transitions (day → night → woken → night → day; settings changes mid-night; disabling mid-night returns to day immediately), and the probe ordering with fake runners.
10. **The wizard step** (if US-32 exists): "Overnight" with `DimSchedulePanel` (enable, times, mode) and Skip.
11. **No wasted work at night**: while the screen is off, the grid doesn't re-render on its own except for data changes and the day change. That's already true by design. Check that idle CPU stays close to 0 % at night.

---

## Design decisions (already made)

- **D1. Setting** `K_DIM_SCHEDULE = "dim_schedule"`: a dict `{"enabled": false, "mode": "dim", "start": "22:30", "end": "06:30", "night_level": 10, "wake_minutes": 5}`. The validator checks each field (times `^\d{2}:\d{2}$` on a 30-minute grid, and `start != end`). Keep it a single dict so it's written as one unit (one atomic write).
- **D2. The state machine** (`DimSchedule`, pure): states `DAY`, `NIGHT`, `NIGHT_AWAKE`. Inputs: `tick(now_local, config)`, `activity()`, `idle_timeout()`, `config_changed(config)`, `preview(seconds)`. Output: the desired effect `("normal" | "dim" | "off")` and whether the wake catcher should show. The GLib controller only applies the effects.
- **D3. Display-off methods, in order of preference** (probed once at startup, in a worker, and cached for the session):
  1. `wlopm --off <output>` / `--on`: DPMS through wlr-output-power-management (keeps the mode). Needs cage support and the `wlopm` package. Probe: `wlopm` (with no arguments) lists the outputs and their power state.
  2. **Backlight `bl_power`** (US-29 backend `power()`), if `supports_power_off`.
  3. **DDC VCP `D6`** (US-29 DDC backend `power()`), if `supports_power_off`. Risk: some monitors can't be woken over DDC. The probe must do an off/on cycle **once, during setup** (from the "Preview" button, with the owner watching), before it's trusted. Until it's confirmed, don't use it automatically.
  4. `wlr-randr --output <out> --off` / `--on`: only if a test cycle succeeds without the window breaking.
  5. **The black overlay**: `dim_layer` at opacity 1.0 (the backlight stays on, but the screen looks off). Always works.
  The environment for the subprocess commands: `WAYLAND_DISPLAY` and `XDG_RUNTIME_DIR` are inherited from the app's own environment (it runs inside cage). The output name comes from `wlr-randr` (`HDMI-A-1`, recorded in US-01).
- **D4. The wake catcher**: a `Gtk.Box` added to `window.overlay` **last** (on top of everything), `can_target=True`, fully transparent (no background, so there's no blending cost), visible only in `NIGHT`. It has a `Gtk.GestureClick` (capture phase, it claims the sequence) → `controller.wake()`. The key hook (through the window event hub) wakes it and **consumes** keys while the catcher is visible. Motion (from the event hub) → wake, without consuming anything.
- **D5. After waking**, `window.inactivity.add_idle_callback(wake_minutes*60, ...)` → `idle_timeout()`. The handle is re-registered when `wake_minutes` changes.
- **D6. "Turn off" warning**: when the mode is set to Turn off, show a one-time `ConfirmDialog`: "Some screens can't be woken by touch once they're turned off. Try Preview first. If the screen doesn't wake, use Dim instead." Preview (10 s) + confirmation → mark the method `confirmed` in a small key (`dim_schedule.confirmed_method`) for that method.

---

## Implementation plan

### Step 1 — Probe the methods on the real hardware (manually first)
```bash
scripts/pi ssh 'apt-cache policy wlopm wayland-utils | grep -E "^[a-z]|Candidate"'
scripts/pi ssh 'sudo apt-get install -y wayland-utils wlopm 2>/dev/null || true'
ENV='env XDG_RUNTIME_DIR=/run/user/$(id -u kiosk) WAYLAND_DISPLAY=wayland-0'
scripts/pi ssh "sudo -u kiosk $ENV wayland-info | grep -iE 'output_power|gamma|screencopy'"
scripts/pi ssh "sudo -u kiosk $ENV wlopm"                       # lists outputs if supported
scripts/pi ssh "sudo -u kiosk $ENV wlopm --off HDMI-A-1; sleep 5; sudo -u kiosk $ENV wlopm --on HDMI-A-1"
```
**Ask the owner to watch the screen** during every off/on test. Then try `wlr-randr --off` / `--on` **only if wlopm isn't supported**, and check the app is still fine afterwards (take a screenshot, and look at the journal for GTK errors). Repeat each working method 10 times. Record which methods work reliably, and whether the monitor wakes by touch or mouse while off (with the test monitor: mouse motion).

Add `wlopm` to provisioning (`setup-pi.sh`) if it's available and works.

### Step 2 — `calpi/system/display_power.py`
```python
class Method(Protocol):
    name: str
    def off(self) -> None: ...
    def on(self) -> None: ...

class Wlopm: ...            # subprocess ["wlopm", "--off", out] with timeout 5
class BacklightPower: ...   # wraps app.brightness.backend.power
class DdcPower: ...
class WlrRandr: ...
class BlackOverlay: ...     # main-thread: dim_layer opacity 1.0 / restore

def probe(app) -> list[Method]:     # worker: returns the ordered list of usable methods (D3), always ending with BlackOverlay
```
The subprocess methods run in a single worker (a `ThreadPoolExecutor(max_workers=1)`, like US-29) and report results through callbacks. `BlackOverlay` runs on the main thread.

### Step 3 — `calpi/dimming.py`
Pure:
```python
def parse_hhmm(s) -> time: ...
def in_window(now: datetime, start: time, end: time) -> bool:
    t = now.timetz().replace(tzinfo=None)
    return start <= t < end if start < end else (t >= start or t < end)

class DimSchedule:
    def __init__(self): self.state = "DAY"; self.preview_until = None
    def evaluate(self, now, cfg) -> Effect: ...
    def activity(self, now, cfg) -> Effect: ...
    def idle_timeout(self, now, cfg) -> Effect: ...
```
The GLib controller:
```python
class DimController:
    BOOT_DELAY_S = 30
    def __init__(self, app, window):
        self.app, self.window = app, window
        self.sched = DimSchedule()
        self.methods = [BlackOverlay(window)]           # until probed
        run_in_thread(lambda: display_power.probe(app), on_done=self._probed)
        self.catcher = WakeCatcher(window, on_wake=self._on_activity)
        app.clock.subscribe_minute(lambda now: self._evaluate())
        app.clock.subscribe_tz_changed(self._evaluate)
        app.settings.subscribe(K_DIM_SCHEDULE, lambda *_: self._evaluate())
        window.event_hub.event_hooks.append(self._on_event)      # motion/keys (US-11 hub)
        GLib.timeout_add_seconds(self.BOOT_DELAY_S, safe_callback(self._evaluate, repeat=False))
    def _apply(self, effect: Effect): ...    # normal/dim/off + catcher visibility; logs transitions
```
Only apply effects when they **change** (don't call `wlopm --off` every minute).

`_on_event(event)`: in NIGHT, a motion or key event → `_on_activity()`. For keys, return a "consume" signal to the hub if the hub supports it. If US-11's hub doesn't support consuming, handle keys in `KeyRouter` instead: if `dim.catcher.get_visible()` → wake and return True. **Choose the KeyRouter route** (it's already the place for key precedence).

### Step 4 — The wake catcher
```python
class WakeCatcher(Gtk.Box):
    def __init__(self, window, on_wake):
        super().__init__(hexpand=True, vexpand=True, can_target=True, visible=False, css_classes=["wake-catcher"])
        g = Gtk.GestureClick(); g.set_button(0)
        g.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        g.connect("pressed", lambda gest, *a: (gest.set_state(Gtk.EventSequenceState.CLAIMED), on_wake()))
        self.add_controller(g)
        window.overlay.add_overlay(self)          # must be the LAST overlay added (topmost)
```
CSS: `.wake-catcher { background: none; }`. After `on_wake()`, the catcher hides straight away, so the next tap reaches the UI.

**Order check**: the wake catcher is created **after** every other overlay (keyboard, dialogs, blocking overlay, toast, dim layer). Make it an explicit step at the end of `MainWindow.__init__`, with a comment.

### Step 5 — The Overnight settings group (`display.py`)
Add a `SettingsGroup("Overnight")` to the Display section:
- `SwitchRow("Overnight mode")`, bound to the `enabled` field (a custom getter/setter that updates the dict, **copying** it: `d = dict(settings.get(K)); d["enabled"] = v; settings.set(K, d)`).
- `ListPickerRow("Starts at")` and `ListPickerRow("Ends at")` with 48 choices (00:00–23:30), labelled with `formatting.short_time`-style 12h/24h text.
- `ChoiceRow("When it's night", [("dim", "Dim"), ("off", "Turn off")])`. "off" is insensitive with the note if no off-method except BlackOverlay exists? **No**: BlackOverlay is a valid "off" (it looks off). Label it honestly: if only BlackOverlay is available, the description says "The screen will go black but stays powered."
- `StepperRow("Night brightness", 5–50, step 5)` (Dim only; hidden for off).
- `ChoiceRow("Stay awake after touch", [(1, "1 min"), (5, "5 min"), (15, "15 min")])`.
- `ButtonRow("Preview", "Try it for 10 seconds", ...)`: the current mode for 10 s, then back. The D6 confirmation for off-methods that haven't been confirmed yet.

Write it as `DimSchedulePanel(ctx)` so the wizard can reuse it.

### Step 6 — Tests
- `tests/test_dimming.py`: `in_window` for 22:30–06:30 at 22:29/22:30/03:00/06:29/06:30, and for 13:00–14:00. DST nights (29 March, 25 October 2026 in Europe/Berlin): `in_window` uses local wall time, so the window is entered and left at local 22:30/06:30 on those nights too. The state transitions listed in acceptance criterion 9. Preview. Disabling mid-night → DAY. `wake_minutes` changes.
- The probe with fake subprocess runners: wlopm OK → first; wlopm fails → falls through; always ends with BlackOverlay.
- The validator: bad times, equal start and end, out-of-range levels.

### Step 7 — Wizard step (only if US-32 exists)
Add a step `"overnight"` after the refresh step, using `DimSchedulePanel(ctx)` with Skip and Next. Update US-32's step list in the wizard module and its tests.

### Step 8 — Pi check (with the owner)
1. Set a window starting 2 minutes from now and lasting 10 minutes. Mode Dim → the screen dims at the start (the owner watches). Mouse motion → normal. After the wake time (set to 1 min) → dims again. At the end → normal.
2. Mode Turn off (with the probed method) → off, then mouse motion → on within 1 s. The first **click** doesn't open a day (check the log: no `screen=day`).
3. Boot inside the window → on for about 30 s, then night.
4. Look at the journal: one INFO line per transition, no repeated `wlopm` calls every minute.
5. Record the method used and the results. Keep the test window setting **turned off** afterwards, or set the owner's preferred schedule.

---

## Files

| File | Change |
|---|---|
| `calpi/system/display_power.py` | New |
| `calpi/dimming.py` | New (the pure schedule plus the controller) |
| `calpi/widgets/settings/display.py` | `DimSchedulePanel`, the Overnight group |
| `calpi/app.py` | `app.dimming = DimController(...)`, the wake catcher created last |
| `calpi/input.py` | `KeyRouter`: wake first when the catcher is visible |
| `calpi/data/settings_store.py` | `K_DIM_SCHEDULE` |
| `calpi/widgets/wizard/*` | The step (if US-32 exists) |
| `.claude/skills/pi-kiosk-setup/setup-pi.sh` | `wlopm` (if it works) |
| `docs/platform-versions.md` | The working display-off methods |
| `tests/test_dimming.py`, `tests/test_display_power.py` | New |

---

## Pitfalls

- **The first tap in the dark activating something.** The wake catcher must be the topmost overlay.
- **Calling off/on every minute.** Only on transitions.
- **Being stuck off** because `on()` failed. Retry, then fall back (acceptance criterion 8).
- **Trusting DDC D6 or `wlr-randr --off` without a confirmed wake.**
- **Wall-clock timers for the window edges.** Evaluate on minute ticks from `timeutil.now()`.
- **Changing the settings dict in place.** Always copy, then `set`.
- **Night mode straight away at boot.** The owner wouldn't see that the device started (acceptance criterion 7).

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] Dim and off cycles checked on the Pi with the owner. The method recorded.
- [ ] The wizard step added (or the note left for US-32).
- [ ] The owner's preferred schedule set (or disabled).

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `DimSchedulePanel(ctx)` | US-32 (wizard step) |
| `app.dimming.state` (`DAY`/`NIGHT`/`NIGHT_AWAKE`), `app.dimming.wake()` | US-31 (status), US-34 (touch wake check), US-35 (gestures ignored while asleep) |
| The wake catcher is the topmost overlay | anything that adds overlays later: **add them before the wake catcher** |
| `K_DIM_SCHEDULE` dict schema | US-32 |
