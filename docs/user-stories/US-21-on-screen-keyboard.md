# US-21 — On-screen keyboard

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P0 |
| **Blocked by** | US-11 Pointer and touch input |
| **Blocks** | US-23 Wi-Fi scan and connect, US-25 Account management |
| **Phase** | 3. Setup and Settings |

## Story

> As a user, I want an on-screen keyboard for entering text such as passwords without a physical keyboard.

## Context

On the finished device there's no keyboard. Setting up Wi-Fi needs a Wi-Fi password, and signing in to iCloud needs an Apple ID email and a 19-character app-specific password (`abcd-efgh-ijkl-mnop`). Both have to be typed **on the screen**.

There's **no system on-screen keyboard** we can use: `cage` has no input-method or virtual-keyboard panel, and squeekboard/wvkbd need compositor support and a desktop session. So the keyboard is **part of the app**: a GTK widget that docks at the bottom of the screen and inserts characters into the focused `Gtk.Entry`/`Gtk.PasswordEntry`.

Requirements that shape the design:
- **Every printable ASCII character** must be typeable (Wi-Fi passwords can contain any of them).
- **Big keys** (US-11: ≥ 72 px, and bigger is better here: about 110 × 80 px).
- **Keys must never steal focus** from the entry being edited.
- **No long-press, no double-tap, no key-preview bubbles** (US-11), and nothing is logged.
- The **physical keyboard keeps working** on the test monitor.
- It has to be **fast** on the Pi: prebuilt layers, and switching layers without rebuilding anything.

Load the `gtk-kiosk-app` skill, and read US-11's input conventions.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-11** Pointer and touch input | Input conventions (tap on release, ≥ 72 px, no hover, `:active` feedback), `KeyRouter` with screen `on_key` and **the rule that entries get their own keys first**, `CALPI_CHECK_TARGETS`, one window event hub | `grep -n "class KeyRouter\|class CursorManager" calpi/input.py`. The Input conventions docstring is present. |

(US-11 depends on US-02, so `window.overlay` exists for docking the keyboard.)

### Soft dependencies
- **US-22** (the settings shell) is the first real host screen. Until it exists, test with a **dev demo screen** (step 7) behind a flag.
- **US-34** (the touchscreen) is where it gets checked with real fingers. Here: mouse, emulated touch (US-11 step 6), and the physical keyboard.

### External blockers
None.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Pressing a key moves the focus out of the entry, so the next character goes nowhere | Every key button needs `set_focus_on_click(False)` **and** `set_focusable(False)`. Check that `Gtk.Button` in the Pi's GTK version respects `focus_on_click` for touch-emulated clicks as well. |
| `Gtk.Editable.insert_text` signature confusion in PyGObject | In GTK 4 PyGObject, `editable.insert_text(text, length, position)` returns the **new position**. Check it on both GTK versions with a tiny test (step 3). |
| `Gtk.PasswordEntry` isn't a `Gtk.Entry` | It's a separate widget that implements `Gtk.Editable`. Always code against `Gtk.Editable` (`get_position`, `set_position`, `insert_text`, `delete_text`, `get_selection_bounds`, `delete_selection`). |
| The keyboard covers the entry being typed into | The host screens must keep their entries in the top ~620 px, or scroll them into view (D6). This is a contract for US-22/23/25/32. |
| The US-11 target checker complains about small keys | Keys are about 110 × 80 px, above the 72 px minimum. Make sure the CSS padding doesn't shrink them. |

---

## Scope

### In scope
- `calpi/widgets/keyboard.py`: `OnScreenKeyboard` (the widget) and `KeyboardDock` (manages showing and hiding and the connection to the focused entry).
- `calpi/data/keyboard_layouts.py` (no gi): layout definitions per purpose, and a test that every printable ASCII character is reachable in the `password` and `text` purposes.
- Purposes: `text`, `email`, `password`, `url`, `number`.
- Special keys: Shift (off → one-shot → caps lock → off), a layer switch (`?123` / `#+=` / `ABC`), Backspace, Space, cursor ← / →, Clear, Done/Next, Hide.
- Hiding and showing on entry focus. The API: `dock.attach(entry, purpose, on_done=None)`.
- The physical keyboard coexisting with it.
- A dev demo screen for testing.

### Out of scope
- Non-ASCII characters (é, ß, emoji): out of scope. Document it (Wi-Fi and iCloud app passwords are ASCII in practice).
- Autocorrect, suggestions, and swipe typing.
- Any system-wide keyboard.

---

## Acceptance criteria

1. When an attached entry gets focus (by tap or click), the keyboard appears docked at the bottom, full width, about **420 px** tall, straight away (no animation), in the purpose's layout. When focus moves to a non-attached widget, or Hide is pressed, or the host screen is hidden, it disappears.
2. Tapping a key inserts its character at the cursor position (replacing any selection) in the focused entry, and **the entry keeps focus**. The cursor moves forward.
3. **Backspace** deletes the selection, or the character before the cursor. **← / →** move the cursor. **Clear** empties the entry. **Space** inserts a space.
4. **Shift**: one tap = the next letter is uppercase, then it returns to lowercase. A second tap = caps lock (shown clearly with a filled key), and a third tap = off. The letter keys' labels change case to match.
5. **Layers**: `?123` shows digits and common symbols. `#+=` shows the rest. `ABC` goes back. **Every printable ASCII character (0x20–0x7E) is reachable** with the `password` purpose (checked by a unit test over the layout data).
6. **Email** purpose: letters plus quick keys `@`, `.`, `-`, `_`, `.com`, and **no autocapitalisation**. **URL** purpose: letters plus `/`, `:`, `.`, `-`, `_`, `~`, `?`, `=`, `&`, and `https://`. **Number**: digits only, large.
7. **Done/Next**: emits the entry's `activate` signal (so forms can move to the next field or submit), or calls the `on_done` callback given in `attach()`. Its label is set per attach (`"Next"`, `"Connect"`, `"Sign in"`, `"Done"`).
8. Every key is at least **110 × 80 px**, with visible `:active` feedback and no transitions. No key shows a preview bubble. Nothing about key presses is logged (not even at DEBUG).
9. The physical keyboard keeps working in the entries while the on-screen keyboard is visible. Escape hides the on-screen keyboard first (a second Escape goes back, following the US-11 rule).
10. **Performance on the Pi**: the first show takes under 300 ms (the layers are built lazily on first use). Later shows and every layer switch take under 50 ms. Each key press is reflected in the entry in under 50 ms.
11. `dock.reserved_height` (px) is available, so host screens can keep their fields visible (D6).
12. A dev demo screen (`CALPI_DEV_OSK=1`) shows three entries (email, password, URL) for manual testing. It isn't reachable in normal runs.

---

## Design decisions (already made)

- **D1. The layout data is pure Python** (`keyboard_layouts.py`): each purpose maps to a list of **layers**. A layer is a list of rows, and each row is a list of key specs: `Key(label, insert=None, action=None, width=1.0)`. `action` is one of `shift`, `backspace`, `space`, `left`, `right`, `clear`, `done`, `hide`, `layer:<name>`. Letter keys have `insert` = the lowercase letter, and shift upper-cases it.
- **D2. The QWERTY letter layer** (every purpose except `number`):
  ```
  q w e r t y u i o p   ⌫
  a s d f g h j k l     (purpose extras, e.g. @ for email)
  ⇧ z x c v b n m  . -  ⇧
  ?123  ←  space  →  Clear  Hide  [Done]
  ```
  The symbols layer `?123`: `1–0`, then `- / : ; ( ) $ & @ "`, then `#+= . , ? ! '`. The layer `#+=`: `[ ] { } # % ^ * + =`, then `_ \ | ~ < > € £ ¥ •`, and **also the remaining ASCII characters** (`` ` ``). **Remove €, £, ¥, and • (non-ASCII)** from the product layer: keep only ASCII. The unit test enforces ASCII-only **and** full coverage.
- **D3. Prebuilt layers in a `Gtk.Stack`** (transition NONE), created on the **first** `show`, never rebuilt. The shift state changes only the labels of the letter keys (`set_label`, 26 calls: cheap).
- **D4. The dock** is an overlay child of `window.overlay`, `valign=END`, `halign=FILL`, with a solid background (no transparency, which is expensive with cairo), and `can_target=True`. It sits above the screens. **One dock for the whole app.**
- **D5. Attaching**: `dock.attach(editable, purpose, done_label="Done", on_done=None)` adds a `Gtk.EventControllerFocus` to the entry (`enter` → show and set the target, `leave` → schedule a hide check on idle, so that tapping a keyboard key, which doesn't take focus, doesn't hide it). The dock keeps a **weak reference** to the target, so a destroyed entry doesn't keep it alive.
- **D6. Keeping the entry visible**: the contract for host screens is either (a) keep the entries in the top `1080 - reserved_height - header` ≈ 540 px, or (b) put the form in a `Gtk.ScrolledWindow` with a bottom margin equal to `reserved_height` while the keyboard is shown (the dock calls `on_keyboard_visible(bool)` on the current screen if it exists). **Prefer (a)**: most of our forms have 1–3 fields.
- **D7. Autocapitalisation**: off for every purpose (emails, passwords, and URLs must never be changed on their own). The `text` purpose (calendar names in US-26) starts with shift on (one-shot) only when the entry is empty.

---

## Implementation plan

### Step 1 — Layout data and coverage test (no gi)
Write `keyboard_layouts.py` with the dataclasses and `LAYOUTS: dict[str, dict[str, list[list[Key]]]]` (purpose → layer name → rows). Also `reachable_chars(purpose) -> set[str]`: every `insert` value in every layer, plus the uppercase letters when a shift key exists, plus a space if there's a space key.

`tests/test_keyboard_layouts.py`:
- `reachable_chars("password") ⊇ {chr(c) for c in range(0x20, 0x7F)}`, and the same for `text` and `url`.
- Every `insert` is ASCII.
- Every row's total width ≤ 11.5 units (so the keys fit at ≥ 110 px each on 1920 px, with margins: 1920 / 11.5 ≈ 167 px per unit. Adjust the unit width to 150–160 px).
- Every layer has `backspace`, a layer switch, and `hide`.

### Step 2 — `OnScreenKeyboard` (the widget)
```python
class OnScreenKeyboard(Gtk.Box):
    def __init__(self, on_key):                # on_key(Key) callback into the dock
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["osk"])
        self._on_key = on_key
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE)
        self.append(self._stack)
        self._built: dict[str, dict[str, Gtk.Widget]] = {}    # purpose -> layer -> widget
        self._letter_buttons: dict[str, list[tuple[Gtk.Button, str]]] = {}
        self.shift = "off"                     # off | once | lock

    def set_purpose(self, purpose: str): ...   # builds that purpose's layers on first use, shows its first layer
    def set_layer(self, name: str): ...
    def set_done_label(self, text: str): ...
    def set_shift(self, state: str): ...       # updates letter labels + shift key css
```
Build each row as a `Gtk.Box` (horizontal, homogeneous=False), with keys as `Gtk.Button` sized by width: `set_size_request(int(UNIT * key.width), KEY_H)`. Every key: `focusable=False`, `focus_on_click=False`, css `osk-key` (plus `osk-special`, `osk-done`, `osk-shift`). Connect `clicked` → `self._on_key(key)`.

Button labels: `⌫` (U+232B), `⇧` (U+21E7), `←`, `→`. Check they're in DejaVu Sans on the Pi (screenshot). Fall back to the words "Del" / "Shift".

**The "Done" key** is one button per layer. Keep references so `set_done_label` can update all of them.

### Step 3 — Editing operations (in the dock)
```python
def _apply(self, key: Key):
    ed = self._target()           # weakref deref; None -> hide
    if ed is None: self.hide(); return
    if key.insert is not None:
        ch = key.insert
        if self.osk.shift != "off" and ch.isalpha(): ch = ch.upper()
        self._insert(ed, ch)
        if self.osk.shift == "once": self.osk.set_shift("off")
        return
    match key.action:
        case "backspace": self._backspace(ed)
        case "left":  ed.set_position(max(0, ed.get_position() - 1))
        case "right": ed.set_position(ed.get_position() + 1)
        case "space": self._insert(ed, " ")
        case "clear": ed.set_text("")
        case "shift": self.osk.set_shift({"off": "once", "once": "lock", "lock": "off"}[self.osk.shift])
        case "hide":  self.hide()
        case "done":  self._done(ed)
        case a if a.startswith("layer:"): self.osk.set_layer(a.split(":", 1)[1])

def _insert(self, ed, text):
    if ed.get_selection_bounds():               # returns (start, end) or () / False depending on version
        ed.delete_selection()
    pos = ed.get_position()
    new_pos = ed.insert_text(text, -1, pos)     # PyGObject returns the new position
    ed.set_position(new_pos if isinstance(new_pos, int) else pos + len(text))

def _backspace(self, ed):
    if ed.get_selection_bounds(): ed.delete_selection(); return
    pos = ed.get_position()
    if pos > 0: ed.delete_text(pos - 1, pos)
```
**Check `get_selection_bounds()`'s return shape** on both GTK versions (it may be `(bool, start, end)` or `(start, end)`), and write a small helper `_has_selection(ed)`.

`match` statements need Python 3.10+. That's fine (the minimum is 3.11).

`ed.set_position(... + 1)` beyond the end: GTK clamps it. Check.

`_done`: if `on_done` is set, call it. Otherwise `ed.activate()` (for a `Gtk.Entry`), or `ed.emit("activate")` (for a `Gtk.PasswordEntry`, which has its own `activate` signal). Check which works for each widget type.

### Step 4 — `KeyboardDock`
```python
class KeyboardDock(Gtk.Box):
    HEIGHT = 420
    def __init__(self, window):
        super().__init__(valign=Gtk.Align.END, halign=Gtk.Align.FILL, css_classes=["osk-dock"])
        self.set_visible(False)
        self.osk = None                                   # built lazily
        self._target_ref = None
        window.overlay.add_overlay(self)
        self.reserved_height = self.HEIGHT

    def attach(self, editable, purpose="text", done_label="Done", on_done=None):
        fc = Gtk.EventControllerFocus()
        fc.connect("enter", lambda *_: self._show_for(editable, purpose, done_label, on_done))
        fc.connect("leave", lambda *_: GLib.idle_add(self._maybe_hide))
        editable.add_controller(fc)

    def _show_for(self, ed, purpose, done_label, on_done): ...  # build osk if needed, set purpose/label, set target, set_visible(True)
    def _maybe_hide(self):
        root_focus = self.get_root().get_focus() if self.get_root() else None
        if not isinstance(root_focus, Gtk.Editable) or root_focus is not self._target():
            ... # only hide if focus moved to another non-attached widget
        return GLib.SOURCE_REMOVE
    def hide(self): ...
```
Careful with **focus inside `Gtk.PasswordEntry`**: its internal `Gtk.Text` child gets the focus, not the `PasswordEntry` itself. `get_focus()` then returns the inner `Gtk.Text`. Compare with `focus.is_ancestor(target)`, or `focus == target or focus.get_ancestor(Gtk.PasswordEntry) is target`. The same applies to `Gtk.Entry` (it has an inner `Gtk.Text` too). **Write a helper `_focus_belongs_to(focus, target)` and test it with both entry types.**

Also hide the dock when the navigator changes screens: hook into `Navigator.show` (add a `screen_changed_callbacks` list in US-02's Navigator if it's missing). Escape: in `KeyRouter`, before the screen's `on_key`: if the dock is visible → hide it, return True.

### Step 5 — CSS
```css
.osk-dock { background-color: #0b0f13; border-top: 2px solid alpha(@text, 0.12); padding: 12px 16px 16px 16px; }
.osk-key  { min-height: 80px; min-width: 110px; margin: 5px; border-radius: 12px; font-size: 34px;
            background: #26303a; color: @text; border: none; box-shadow: none; padding: 0; }
.osk-key:active   { background: @accent; color: @bg; }
.osk-special      { background: #1b232b; font-size: 26px; }
.osk-shift.on     { background: #3a4a5a; }
.osk-shift.lock   { background: @accent; color: @bg; }
.osk-done         { background: @accent; color: @bg; font-weight: bold; }
```

### Step 6 — The password entry helper
Hosts (US-23, US-25) will want a "show/hide password" toggle. `Gtk.PasswordEntry` has `set_show_peek_icon(True)`, but that icon is small (about 16 px), below the 72 px target. **Provide a helper** `make_password_field() -> (Gtk.Box, Gtk.PasswordEntry, toggle_button)`: a `PasswordEntry` plus a separate 72 × 72 "Show" / "Hide" button that toggles `set_show_peek_icon(False)` / the entry's visibility. GTK 4 `PasswordEntry` doesn't expose `set_visibility`, so **use a `Gtk.Entry` with `set_visibility(False)`** plus `input_purpose=PASSWORD` instead of `PasswordEntry` if the toggle is needed. **Decision: use `Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)`** for password fields, which makes the toggle trivial (`set_visibility(not ...)`). Put this helper in `keyboard.py` or `widgets/forms.py`.

### Step 7 — The dev demo screen
`calpi/widgets/dev_osk_demo.py`: a screen with an email entry, a password field (the step 6 helper), and a URL entry, each attached with its purpose, plus a label showing the **length** of each field (never the password itself). Register it only when `CALPI_DEV_OSK=1`, and show it at startup instead of the calendar. **It's not reachable otherwise.**

### Step 8 — Tests
- The layout tests (step 1).
- GTK tests (`CALPI_GTK_TESTS=1`, Broadway): a small test app, or the demo screen with a test hook: programmatically focus the email entry, call `dock._apply(Key(insert="a"))` × 3, then shift-once + `a`, then backspace → the text is `"aa"`, then `"aaA"`, then `"aa"`. The cursor position is right. Focus stays on the entry (`window.get_focus()` belongs to the entry). Select all + insert `"x"` → `"x"`. Do the same with the password `Gtk.Entry`.
- `_focus_belongs_to` with `Gtk.Entry` and `Gtk.PasswordEntry`.

### Step 9 — Manual checks
- Broadway with the mouse: type a 63-character Wi-Fi-style password containing every symbol class, and the app-specific password format. Compare the field length.
- `GTK_DEBUG=touchscreen` (if available, per US-11) → the same with emulated touch. The focus never leaves the entry.
- The physical keyboard in the entry while the on-screen keyboard is shown.
- The Pi (US-03): `CALPI_DEV_OSK=1` in a **temporary** drop-in. Take a screenshot of the keyboard (legibility and sizes). Time the first show and the layer switches (log `perf: osk_show` at DEBUG/`CALPI_PERF`). `CALPI_CHECK_TARGETS=1` shows no small targets. **Remove the drop-in.**

---

## Files

| File | Change |
|---|---|
| `calpi/data/keyboard_layouts.py` | New |
| `calpi/widgets/keyboard.py` | New (`OnScreenKeyboard`, `KeyboardDock`, the password field helper) |
| `calpi/widgets/dev_osk_demo.py` | New (dev only) |
| `calpi/app.py` | Creates `window.keyboard = KeyboardDock(window)`, the dev demo flag |
| `calpi/input.py` | Escape hides the keyboard first |
| `calpi/style.css` | OSK styles |
| `tests/test_keyboard_layouts.py` | New |

---

## Pitfalls

- **Keys that take focus.** Set both `focusable=False` and `focus_on_click=False`.
- **Comparing focus with the entry directly** (the inner `Gtk.Text` has it). Use `_focus_belongs_to`.
- **Logging key presses or entry contents.** Never, not even for debugging. Log lengths if you have to.
- **Non-ASCII keys**, which some Wi-Fi setups would reject, or which break the coverage test.
- **Rebuilding layers on every show or shift.** Build once, change labels.
- **A translucent dock background.** It's expensive with the cairo renderer. Use a solid colour.
- **Using `Gtk.PasswordEntry` when a large show/hide toggle is required.** See step 6.

---

## Definition of done

- [ ] All acceptance criteria met. The layout coverage test and the GTK editing tests pass.
- [ ] Manual checks with the mouse, emulated touch, and the physical keyboard done.
- [ ] Pi screenshot and timings recorded. The drop-in removed.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `window.keyboard.attach(editable, purpose, done_label, on_done)` | US-23 (Wi-Fi password, hidden SSID), US-25 (Apple ID, app password), US-26 (rename), US-20, US-32, US-41 (city search) |
| Purposes `text`, `email`, `password`, `url`, `number` | same |
| `window.keyboard.reserved_height`, and the rule to keep fields in the top ~540 px | US-22, US-23, US-25, US-32 |
| `make_password_field()` (a `Gtk.Entry` with a 72 px Show/Hide toggle) | US-23, US-25 |
| Escape hides the keyboard before navigating back | US-11 `KeyRouter` |
| **Never log entry contents** | all form stories |
