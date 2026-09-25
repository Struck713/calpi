# US-29 — Brightness control

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P1 |
| **Blocked by** | US-22 Settings shell |
| **Blocks** | US-30 Overnight dim and sleep schedule |
| **Phase** | 3. Setup and Settings (P1) |

## Story

> As a user, I want to adjust the screen's brightness from Settings, where the display hardware allows it.

## Context

"Where the display hardware allows it" is the important part. How brightness can be controlled depends entirely on the screen:

| Screen type | Mechanism | How we reach it |
|---|---|---|
| DSI panels (the official Pi touchscreens), some HATs | **Kernel backlight** device: `/sys/class/backlight/<name>/brightness` | Write the number (needs write permission: a udev rule) |
| External HDMI monitors (the current test monitor, and probably the final touchscreen) | **DDC/CI** over the HDMI cable's I²C lines, VCP feature `0x10` (luminance) | `ddcutil setvcp 10 <value>` (needs `i2c-dev` and the `i2c` group). Slow (100–500 ms per call). **Many portable monitors don't support it.** |
| Anything else | **Software dimming**: a black, semi-transparent layer over the whole app | Always available. It dims the picture, but **not** the backlight, so there's no power saving and blacks stay grey. |

This story builds a **brightness controller** that probes for the best available backend at startup, applies the saved brightness, and exposes a simple API. It also adds a **Display** section to Settings with a brightness control and a plain note about which method is in use. **US-30** (the overnight schedule) builds on the same controller.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-22** Settings shell | `register_section`, `StepperRow` (with the 500 ms debounced write), `SettingsGroup`, `InfoRow`, `app.toast` | `grep -n "class StepperRow" calpi/widgets/settings/rows.py` |

(US-22 brings US-05's settings store and US-11's input rules.)

### Soft dependencies
- **US-01 / provisioning**: the udev rule, `i2c-dev`, the `i2c` group, and the `ddcutil` package are provisioning changes to `setup-pi.sh` (step 1). They're part of this story.
- **US-03** for every check on the Pi. The backends can only be tested on hardware.
- **US-34** (touchscreen) will change the screen. **Probe again** when it happens (the probe runs at every startup anyway).

### External blockers (important)

| Blocker | What to do |
|---|---|
| **Which display is connected, and what it supports** | Ask the owner for the monitor model. Check on the Pi: `ls /sys/class/backlight/` (usually empty for HDMI), `sudo ddcutil detect` and `sudo ddcutil getvcp 10` (after step 1). Record the results in `docs/platform-versions.md` ("Display: DDC/CI supported? backlight device?"). |
| **`ddcutil` in apt** on the Pi's release | `apt-cache policy ddcutil`. It's in Debian. If it's missing, the DDC backend is simply unavailable. |
| **DDC on the Pi 3B under KMS** | The vc4 HDMI driver exposes the DDC bus as an I²C adapter once `i2c-dev` is loaded. `ddcutil detect` should find it. If it says "No displays found" even with a monitor that supports DDC, try `ddcutil detect --verbose`, check `ls /dev/i2c-*`, and record what you find. **Don't spend more than an hour on it**: software dimming is an acceptable result for this story. |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| `ddcutil` needs root | Add `kiosk` to the `i2c` group, and make sure `/dev/i2c-*` is `root:i2c 0660` (the ddcutil package ships a udev rule for this, `60-ddcutil-i2c.rules`; if it doesn't, add one). |
| DDC calls sometimes fail or time out | Retry once. After 3 failures in a row, mark the backend unhealthy, fall back to software dimming, and log a WARNING. |
| The monitor's OSD pops up on every DDC change | Some monitors show an on-screen banner when the brightness changes. Note it. It's harmless. |
| Software dimming makes month changes slower | Measure `perf: month_render` with the dim layer on (acceptance criterion 8). If it's much slower, lower the redraw cost (the layer must be a single widget with a plain background and `can_target=False`). |

---

## Scope

### In scope
- Provisioning: the backlight udev rule, the `i2c-dev` module, the `i2c` group for `kiosk`, the `ddcutil` package (a `setup-pi.sh` section).
- `calpi/system/brightness.py`: the backends `BacklightSysfs`, `DdcCi`, `SoftwareDim`; the probe; `BrightnessController`.
- The settings key `K_BRIGHTNESS` (10–100, default 100).
- Applying it at startup (after probing in a worker).
- The **Display** section (`"display"`, order 50): the brightness stepper with presets, the method note, and a "Test" flash (optional).
- The API for US-30: temporary overrides (a dim level, and screen off where supported) that don't change the saved setting.

### Out of scope
- The schedule (US-30).
- Automatic brightness (no light sensor).
- Turning the display off (that's US-30, with `display_power.py`). The controller only reports `supports_power_off`.

---

## Acceptance criteria

1. **Probe order** at startup (in `run_in_thread`, never blocking the UI): (1) a writable `/sys/class/backlight/*` device → `backlight`; (2) `ddcutil detect --terse` finds a display **and** `getvcp 10` works → `ddc`; (3) otherwise → `software`. The result is logged: `brightness: backend=ddc (display "XYZ", max=100)`.
2. The probe finishes in under 10 s (`ddcutil detect` can be slow). Until it finishes, the brightness isn't changed. The UI isn't affected.
3. The saved `K_BRIGHTNESS` is applied once the probe finishes (the backlight is reset at boot; DDC monitors may have been changed with their own buttons, so our setting wins).
4. **Settings → Display → Brightness**: a `StepperRow` in 10 % steps (10–100 %), **plus** preset buttons 25 % / 50 % / 75 % / 100 %. Changes take effect **visibly within 0.5 s** (DDC is slower: it's coalesced). The setting is written with a 500 ms debounce.
5. A note under the control, depending on the backend: backlight → "Screen backlight"; ddc → "Controlled through the monitor (DDC/CI)"; software → "This screen can't be dimmed directly, so calpi darkens the picture instead. For deeper dimming, use the monitor's own buttons."
6. **Minimum brightness**: 10 % for backlight and DDC. For software, 10 % maps to an overlay opacity of **0.75** at most (so the screen is never unreadably black).
7. DDC writes are **serialised and coalesced**: at most one `ddcutil` process at a time. If the user taps 5 times quickly, only the first and the last values are sent.
8. **Health**: 3 DDC failures in a row → the backend is switched to software for the rest of the session, with a WARNING, and the note updates.
9. **Software dim performance**: with the software layer at 50 %, `perf: month_render` p90 on the Pi stays under 150 ms (US-07's target). Idle CPU stays close to 0 %.
10. **API for US-30**: `controller.set_override(percent | None)` applies a temporary level (for example 10 % at night) without writing the setting, and `None` goes back to the saved value. `controller.backend_name`, `controller.supports_power_off` (backlight: `bl_power`; ddc: VCP `0xD6`, if supported; software: False).
11. The pure parts (level mapping, coalescing logic, parsing `ddcutil` output) are unit-tested.

---

## Design decisions (already made)

- **D1. Provisioning** (a `setup-pi.sh` section):
  ```bash
  echo "==> display brightness access"
  apt-get install -y --no-install-recommends ddcutil
  echo i2c-dev > /etc/modules-load.d/calpi-i2c.conf; modprobe i2c-dev || true
  getent group i2c >/dev/null || groupadd --system i2c
  usermod -aG i2c,video kiosk
  cat > /etc/udev/rules.d/60-calpi-backlight.rules <<'EOF'
  SUBSYSTEM=="backlight", ACTION=="add", RUN+="/bin/chgrp video /sys%p/brightness /sys%p/bl_power", RUN+="/bin/chmod g+w /sys%p/brightness /sys%p/bl_power"
  SUBSYSTEM=="i2c-dev", KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"
  EOF
  udevadm control --reload-rules && udevadm trigger
  ```
  The group change only affects the kiosk process after a **service restart**.
- **D2. `ddcutil` calls**: `["ddcutil", "--noverify", "--sleep-multiplier", "0.5", "setvcp", "10", str(value)]` with the bus fixed after detection (`--bus N`, which is much faster than letting ddcutil search every time). Read: `["ddcutil", "--bus", N, "--terse", "getvcp", "10"]` → `VCP 10 C 50 100` (current, max). Parse with a regex. Scale our % to the monitor's max. Timeout 5 s per call. **Check the exact flags against the installed ddcutil version** (`ddcutil --help`): `--sleep-multiplier` exists in 1.x and 2.x.
- **D3. The software layer** is a `Gtk.Box` in `window.overlay`, css `dim-layer`, `can_target=False`, `hexpand`/`vexpand`. Its opacity is set with `widget.set_opacity(alpha)` (not CSS), where `alpha = 0.75 * (100 - percent) / 90` for 10–100 %. It's hidden completely (`set_visible(False)`) at 100 %, so it costs nothing then. It must sit **above** the screens and **below** the keyboard, dialogs, and toasts (so dialogs stay readable when dimmed? **Decision: it sits above everything except the wake-catcher from US-30**, so the whole picture dims evenly).
- **D4. `BrightnessController`** lives in the UI process (it needs the overlay for software dimming). Backend I/O (sysfs writes, ddcutil) runs in **one** dedicated worker (a `concurrent.futures.ThreadPoolExecutor(max_workers=1)`), with "latest value wins" coalescing.
- **D5. `K_BRIGHTNESS`**: int, default 100, validator 10 ≤ v ≤ 100.

---

## Implementation plan

### Step 1 — Provision and look at the hardware
Add the D1 section, run it, and restart the service. Then:
```bash
scripts/pi ssh 'ls -l /sys/class/backlight/ 2>/dev/null; ls -l /dev/i2c-*; id kiosk'
scripts/pi ssh 'sudo -u kiosk ddcutil detect --terse; sudo -u kiosk ddcutil --terse getvcp 10'
```
Record the output in `docs/platform-versions.md`. This decides which backend you can actually test.

### Step 2 — `calpi/system/brightness.py`
Pure helpers (tested):
```python
def percent_to_raw(percent: int, raw_max: int, raw_min: int = 0) -> int: ...
def software_alpha(percent: int) -> float: ...                 # D3
def parse_getvcp_terse(stdout: str) -> tuple[int, int] | None: ...   # "VCP 10 C 50 100" -> (50, 100)
def parse_detect_terse(stdout: str) -> list[dict]: ...          # "Display 1\n   I2C bus: /dev/i2c-2\n   Monitor: ..." -> [{bus: 2, model: "..."}]
class Coalescer:        # pure: submit(value) -> whether to start now; done() -> next value or None
```
Backends (their I/O methods run in the worker):
```python
class BacklightSysfs:
    name = "backlight"
    def __init__(self, path: Path): self.path = path; self.max = int((path / "max_brightness").read_text())
    def set(self, percent): (self.path / "brightness").write_text(str(percent_to_raw(percent, self.max, 1)))
    supports_power_off = property(lambda self: (self.path / "bl_power").exists())
    def power(self, on: bool): (self.path / "bl_power").write_text("0" if on else "4")

class DdcCi:
    name = "ddc"
    def __init__(self, bus: int, raw_max: int): ...
    def set(self, percent): _run(["ddcutil", "--bus", str(self.bus), "--noverify", "setvcp", "10", str(percent_to_raw(percent, self.raw_max))])
    supports_power_off: bool     # probe VCP D6 once: getvcp d6 succeeds
    def power(self, on: bool): _run([... "setvcp", "d6", "1" if on else "4"])   # 1=on, 4=off (DPMS) — monitor-dependent

class SoftwareDim:
    name = "software"
    supports_power_off = False
    def __init__(self, layer: Gtk.Widget): self.layer = layer
    def set(self, percent): call_on_main(self._apply, percent)   # UI work on the main thread
```
`probe(layer) -> backend` (it runs in the worker): check backlight first (a writable `brightness` file), then DDC (`detect --terse` → the first display's bus → `getvcp 10` works), else software.

The controller (main thread):
```python
class BrightnessController:
    def __init__(self, app, layer):
        self.app = app; self.layer = layer
        self.backend = None; self.override = None; self._failures = 0
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="brightness")
        self._coalescer = Coalescer()
        self.ready_callbacks = CallbackList()
        run_in_thread(lambda: probe(layer), on_done=self._on_probed, on_error=self._probe_failed)
    def level(self) -> int: return self.override if self.override is not None else self.app.settings.get(K_BRIGHTNESS)
    def apply(self): ...                 # submit level() through the coalescer to the executor
    def set_override(self, percent): self.override = percent; self.apply()
    @property
    def backend_name(self): return self.backend.name if self.backend else "probing"
```
On a backend error: `_failures += 1`. At 3, switch to `SoftwareDim` (on the main thread), log a WARNING, and notify `ready_callbacks` (so the note updates).

Subscribe to `K_BRIGHTNESS` → `apply()`.

### Step 3 — The dim layer
In `MainWindow`: `self.dim_layer = Gtk.Box(css_classes=["dim-layer"], can_target=False, visible=False)` added to `window.overlay` **after** the other overlays except the wake-catcher (D3). CSS: `.dim-layer { background-color: black; }`. The opacity is set in code.

`SoftwareDim._apply(percent)`: `alpha = software_alpha(percent)`. If `alpha <= 0.001` → `set_visible(False)`, else `set_opacity(alpha); set_visible(True)`. Only change it when the value is different.

### Step 4 — The Display section (`calpi/widgets/settings/display.py`)
```
SettingsGroup "Brightness"
  StepperRow("Brightness", value=settings[K_BRIGHTNESS], min=10, max=100, step=10, format="{}%", on_change=...)
  preset row: [25%] [50%] [75%] [100%]   (ChoiceRow-like buttons, write immediately)
  note label (backend-dependent text, D-texts in acceptance criterion 5)
```
While probing: the note says "Checking what this screen supports…" and the controls are enabled anyway (the value applies once probing finishes).

Register it: `SectionSpec("display", "Display", 50, DisplaySection)`. **US-30 adds its schedule group to this same section.** Design the section as a vertical list of groups that US-30 can extend (a `self.groups_box` it can append to, or a small hook: `DISPLAY_GROUP_FACTORIES` list).

### Step 5 — Tests
- Pure: `percent_to_raw` (1 → raw_min, 100 → raw_max, rounding), `software_alpha` (100 → 0, 10 → 0.75), the ddcutil parsers (fixtures from the real Pi output **and** from the ddcutil docs), the `Coalescer` (submit 1, 2, 3, 4 while busy → after `done()` the next value is 4 only).
- Controller with a fake backend: failures → fallback after 3. The override doesn't write the setting.

### Step 6 — Pi check
- With the test monitor: whatever the probe found. Change the brightness in Settings, and the owner confirms the screen visibly changes. Screenshot for software dimming (`grim` captures the dim layer, since it's part of the app). DDC and backlight changes **don't** show in screenshots: ask the owner.
- Performance with software dim at 50 %: `perf: month_render` (acceptance criterion 9).
- A restart → the saved brightness is applied after the probe (the owner confirms).
- If the probe found `software` but the owner's monitor supports DDC: record it as a follow-up investigation. Don't block the story.

---

## Files

| File | Change |
|---|---|
| `.claude/skills/pi-kiosk-setup/setup-pi.sh` | The brightness access section |
| `calpi/system/brightness.py` | New |
| `calpi/widgets/settings/display.py` | New (the Brightness group; extensible for US-30) |
| `calpi/widgets/settings/__init__.py` | Imports `display` |
| `calpi/app.py` | The dim layer, `app.brightness = BrightnessController(...)` |
| `calpi/data/settings_store.py` | `K_BRIGHTNESS` |
| `calpi/style.css` | `.dim-layer`, preset buttons |
| `docs/platform-versions.md` | The display's capabilities |
| `tests/test_brightness.py`, `tests/fixtures/ddcutil/*` | New |

---

## Pitfalls

- **`ddcutil` on the main thread.** It can take seconds. Use the worker.
- **Several `ddcutil` processes at once.** They fight over the I²C bus. Serialise them (D4).
- **Brightness 0.** Never. A black screen looks broken. The minimum is 10 %.
- **Software dim above everything, including the OSK, at night.** That's acceptable (D3), but check the keyboard stays readable at the minimum level.
- **Treating "no DDC" as a bug.** Many monitors simply don't support it. Software dimming is the fallback, by design.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] Display capabilities recorded. The working backend checked with the owner watching the screen.
- [ ] The software-dim performance measured.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `app.brightness` (`BrightnessController`): `set_override(percent | None)`, `level()`, `backend_name`, `supports_power_off`, `backend.power(on)`, `ready_callbacks` | US-30 |
| `window.dim_layer` (the software dimming layer) | US-30 |
| The Display section (`"display"`, order 50), extensible with groups | US-30 |
| `K_BRIGHTNESS` | US-30, US-32 (optional) |
