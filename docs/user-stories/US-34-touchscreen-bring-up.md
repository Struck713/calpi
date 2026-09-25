# US-34 — Touchscreen bring-up

| | |
|---|---|
| **Epic** | 4. Touch and Polish |
| **Priority** | P1 |
| **Blocked by** | US-01 Kiosk OS provisioning, US-11 Pointer and touch input |
| **Blocks** | US-35 Touch gestures |
| **Phase** | 4. Touch and Polish |

## Story

> As the owner, I want the touchscreen detected, correctly oriented and accurate when it replaces the test monitor.

## Context

Up to now, everything has been built and tested on a non-touch portable monitor with a mouse and keyboard, with touch only **emulated** (US-11). This story swaps in the **real touchscreen** and makes sure that:
1. the display works at the right resolution and orientation,
2. the touch controller is **detected** by the kernel and libinput, and cage hands its events to the app,
3. touches land **where the finger is** (after any rotation), accurately enough for 72 px targets,
4. the whole app works **with fingers only**: every screen, the on-screen keyboard, scrolling, and **waking from overnight mode** (US-30),
5. the facts are recorded, so provisioning can recreate them.

Most of the input work was done in US-11 (touch-aware cursor, targets, activate on release) and US-21 (keyboard). This story is **hardware bring-up and checking**, with small fixes where real touch behaves differently from emulated touch.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-01** Kiosk OS provisioning | cage on KMS, the `kiosk` user in the `input` group, `setup-pi.sh` to extend, `docs/platform-versions.md` | `ssh calpi 'id kiosk'` includes `input`. The service runs. |
| **US-11** Pointer and touch input | The touch-aware `CursorManager`, the input conventions, `CALPI_CHECK_TARGETS`, `KeyRouter` | `grep -n "TOUCHSCREEN" calpi/input.py` |

### Soft dependencies
- **US-21** (OSK), **US-22–US-32** (the screens), **US-30** (wake by touch): the checks in step 6 cover every screen that exists at the time. Check whatever is there, and list what wasn't there yet.
- **US-29/US-30**: the brightness and power backends must be **probed again** on the new screen (they probe at startup, so a restart is enough). Record the new capabilities.
- **US-03** for all checks.

### External blockers (this story can't start without them)

| Blocker | What to do |
|---|---|
| **The touchscreen itself**, its model name, and how it connects (HDMI + USB touch, or DSI) | Ask the owner. Record the model. |
| **The screen's native resolution** | **If it isn't 1920×1080, stop and raise it with the owner**: the whole UI is designed for exactly 1920×1080 (US-06 D1 and the `gtk-kiosk-app` skill). Options: (a) run the screen at 1920×1080 if it accepts that mode (many 1366×768 or 1280×800 panels accept 1080p input and scale it down: blurry, but workable); (b) a new story to make the layout scale (CSS sizes + `CELL_HEIGHT`/`CAPACITY` constants, US-07). **Don't start rewriting the layout inside this story.** |
| **Power for the screen** | Portable touch monitors often need more power than the Pi 3B's USB ports can supply (1.2 A total). Use the monitor's own power input. An under-powered monitor causes flicker and touch drop-outs, and can make the Pi under-voltage (`vcgencmd get_throttled`). |
| **The mounting orientation** (landscape or portrait, flipped?) | Ask the owner how it'll hang on the wall. The app is designed for **landscape**. Portrait is a layout change: raise it as a new story if it's wanted. A 180° flip (for cable routing) is fine and in scope. |
| **Physical access**: someone has to touch the screen | The owner does the touch tests, with the agent guiding over the conversation. |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| The touch device isn't seen at all | Check it enumerates: `lsusb`, `dmesg | grep -i -E "touch|hid|input"`, `cat /proc/bus/input/devices`. Some panels need the USB **data** cable (not only power). Some need a kernel module (`hid-multitouch` is standard). |
| Touches register, but are mirrored or rotated | Output rotation and touch mapping must agree. cage/wlroots maps touch to the output, and **may or may not** apply the output transform to touch in the version installed. Test it. If it's wrong, set a `LIBINPUT_CALIBRATION_MATRIX` with udev (step 4). |
| Touches are offset by a few percent near the edges | A calibration issue with the panel. Use a calibration matrix with scale and offset (step 4). |
| Touch acts like a mouse (a cursor appears when touching) | The device may present itself as a mouse (a single-touch "absolute pointer"). `libinput list-devices` shows its capabilities. US-11's cursor logic then sees `MOUSE` as the source. Detect it by device name or capability, and treat it as touch (add a device-name allowlist setting). |
| Touch still works while the display is off (US-30) — or doesn't | Record it. If touch stops when the monitor sleeps, the owner has to use **Dim** mode (US-30 D6), and the "Turn off" option should warn about it. |

---

## Scope

### In scope
- Recording the hardware facts (model, resolution, connection, input device name, capabilities).
- Display set-up for the new screen (mode, `video=` in `cmdline.txt`, overscan, rotation 0° or 180°).
- Touch detection under cage, the calibration matrix if needed, and udev rules in provisioning.
- A **dev touch test screen** (`CALPI_DEV_TOUCHTEST=1`): targets at the corners and centre, markers where touches land, and offsets reported.
- A full finger-only walkthrough of every existing screen, the OSK, scrolling, and waking.
- Small fixes to input handling found during the walkthrough (for example device-source quirks).

### Out of scope
- Swipe gestures (US-35).
- Portrait layout, and non-1080p layout scaling (new stories if needed: see the external blockers).
- Multi-touch gestures (pinch and so on): not planned.

---

## Acceptance criteria

1. `docs/platform-versions.md` has a **Touchscreen** section: the model, native resolution, connection, kernel input device name, libinput capabilities, whether a calibration matrix is used (and its value), the orientation, the brightness and power capabilities (the US-29/US-30 probes run again), and **whether touch works while the display is off**.
2. The display runs at **1920×1080** with no overscan borders and the chosen orientation (0° or 180°). `wlr-randr` confirms it. A screenshot matches what the owner sees.
3. The touch device is listed by `libinput list-devices` with the `touch` capability, and the app receives touch events (`TOUCH_BEGIN` logged at DEBUG while the test screen is open).
4. **Accuracy**: on the touch test screen, the owner taps 9 targets (the corners, the edge midpoints, and the centre). Every recorded touch is within **12 px** of the target centre (the test screen reports the offsets). If needed, apply a calibration matrix until this passes.
5. **No cursor** ever appears with touch-only input (US-11 acceptance criterion 1 checked on real touch).
6. **Finger-only walkthrough** (checked by the owner, with the agent following in `scripts/pi logs -f`): month navigation, Today, open a day, scroll the busy day, back; Settings: every section that exists, the list pickers and scrolling, switches, steppers; the OSK: type an email and a 20-character password with symbols; the confirm dialog; (if US-30) the overnight preview and waking by touch, with the first touch swallowed; (if US-32) run setup again and skip through it.
7. Taps activate on release. Drag-off cancels. A light brush while scrolling doesn't activate buttons (GTK's scrolled window claims drags). No accidental activations were seen during the walkthrough, and any that were are fixed.
8. `CALPI_CHECK_TARGETS=1` on every screen: no violations (the same as before, now confirmed with fingers).
9. Provisioning (`setup-pi.sh`) reproduces the display and touch set-up (the `video=` mode, rotation, and a udev calibration rule if used) idempotently.
10. The dev touch test screen is **only** reachable with `CALPI_DEV_TOUCHTEST=1`.

---

## Design decisions (already made)

- **D1. Rotation**: prefer the **kernel** `video=HDMI-A-1:1920x1080@60D,rotate=180` for a 180° flip (it applies from boot, including the console). Fall back to `wlr-randr --output HDMI-A-1 --transform 180` in an `ExecStartPost=` if the kernel option doesn't work with vc4. Record which one works.
- **D2. Calibration** (only if needed) with a udev rule `/etc/udev/rules.d/99-calpi-touch.rules`:
  ```
  ACTION=="add|change", KERNEL=="event*", ATTRS{name}=="<exact device name>", ENV{LIBINPUT_CALIBRATION_MATRIX}="a b c d e f"
  ```
  For a 180° rotation that the compositor doesn't apply to touch: `-1 0 1 0 -1 1`. For scale and offset corrections: `sx 0 ox 0 sy oy`, computed from the test screen's measured offsets (step 4). Restart the service after changing it (libinput reads it when the device is added: `udevadm trigger` + restart cage).
- **D3. The touch test screen** is a `Gtk.DrawingArea` drawn with cairo only when something changes (target dots, touch markers, text). It uses `Gtk.GestureClick` + `Gtk.GestureDrag` in the capture phase to record the raw coordinates, plus a legacy controller to show the device source and name. It lives in `calpi/widgets/dev_touch_test.py`.
- **D4. The device-source quirk handling** (if the panel shows up as a mouse): a hidden setting `K_TOUCH_DEVICE_NAMES` (a list of strings, default `[]`). `CursorManager` treats events from devices whose name contains one of those strings as touch. Set it with the CLI or during provisioning. Only add it if it's actually needed.

---

## Implementation plan

### Step 1 — Record the hardware
With the new screen connected (monitor powered separately if needed) and the Pi rebooted (with the owner's OK):
```bash
scripts/pi ssh 'cat /sys/class/drm/card*-HDMI-A-1/modes | head; cat /sys/class/drm/card*-HDMI-A-1/status'
scripts/pi ssh 'lsusb; cat /proc/bus/input/devices'
scripts/pi ssh 'sudo apt-get install -y libinput-tools evtest && sudo libinput list-devices'
scripts/pi health          # throttling after the swap!
```
Check the resolution against the external blocker (1920×1080?). Write down the device name exactly as libinput reports it.

### Step 2 — Display mode and orientation
If the native or accepted mode is 1920×1080: keep US-01's `video=` setting. Add `,rotate=180` if the owner mounts it upside down (D1). If there's overscan: `disable_overscan=1`. Reboot (with OK), take a screenshot, and have the owner confirm.

### Step 3 — Does touch arrive in the app?
Build the dev touch test screen (D3) first:
- 9 target circles (40 px) at 60 px from the edges and at the centre.
- On press: draw a small cross at `(x, y)`, record it, and show `dx`, `dy` from the nearest target, plus the event's device name and source.
- A "Clear" button (a large one) and a summary line (max and mean offset).
Deploy with the `CALPI_DEV_TOUCHTEST=1` drop-in (temporary). Ask the owner to tap each target. Read the results from the screen (screenshot) and the log (it also logs each measurement at INFO).

### Step 4 — Calibrate if needed
- Touches mirrored or rotated → the rotation matrix (D2) → rerun.
- A consistent offset or scale → compute: with targets at known `(tx, ty)` and measured `(mx, my)`, fit `tx = sx*mx + ox` and `ty = sy*my + oy` by least squares (a tiny pure helper in the test module, `fit_calibration(points) -> matrix`; add a unit test). Express the matrix in libinput's normalised units (divide the offsets by the width and height). Apply, restart, rerun, and repeat until it's ≤ 12 px (acceptance criterion 4).
- Add the rule to `setup-pi.sh` (a `TOUCH_NAME` and `TOUCH_MATRIX` variable pair; skipped when empty).

### Step 5 — Device-source quirk (only if needed)
If the log shows touches arriving as `MOUSE`: implement D4. Otherwise skip it.

### Step 6 — The finger-only walkthrough
Remove the touch-test drop-in. Unplug the mouse and keyboard. Guide the owner through the acceptance criterion 6 checklist. Watch `scripts/pi logs -f` for `screen=...` lines, errors, and accidental navigation. Make a table: `screen | action | OK? | notes`. Fix small issues (for example a control that's hard to hit: raise its size; a scroll that activates rows: use `released` + a movement threshold as in US-09 D3).

### Step 7 — Re-probe the display capabilities
Restart the app, and look at `brightness: backend=...` (US-29) and the US-30 display-power probe. Test waking from Turn off **by touch** (only if Turn off is supported), and record the result in the platform file (acceptance criterion 1).

### Step 8 — Clean up
Remove the drop-ins. `libinput-tools`/`evtest` can stay as dev tools (note them). Make sure `setup-pi.sh` is idempotent with the new sections.

---

## Files

| File | Change |
|---|---|
| `docs/platform-versions.md` | The Touchscreen section |
| `.claude/skills/pi-kiosk-setup/setup-pi.sh` | Rotation / calibration rule (if needed) |
| `.claude/skills/pi-kiosk-setup/SKILL.md` | Notes on the touchscreen set-up |
| `calpi/widgets/dev_touch_test.py` | New (dev only) |
| `calpi/input.py` | Only if D4 is needed |
| `tests/test_touch_calibration.py` | New (the fit helper) |

---

## Pitfalls

- **Starting a layout rewrite** because the screen isn't 1080p. Raise it with the owner instead (external blockers).
- **Powering the monitor from the Pi's USB.** Check throttling.
- **Forgetting that US-29/US-30 capabilities change** with the new screen.
- **Leaving the touch-test drop-in** active.
- **Calibrating on an unstable mount** (it shifts later). Calibrate in the final position if you can.

---

## Definition of done

- [ ] All acceptance criteria met, with the walkthrough table in the hand-off notes.
- [ ] Hardware facts recorded, including touch-while-off.
- [ ] The provisioning script reproduces the set-up.
- [ ] Drop-ins removed.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| Recorded touchscreen facts (resolution, orientation, touch-while-off) | US-30 (Turn off warning), US-35, US-36 (performance numbers on the final screen) |
| `K_TOUCH_DEVICE_NAMES` (if created) | US-11 cursor logic, US-35 |
| `dev_touch_test` screen | US-35 (checking swipe thresholds) |
