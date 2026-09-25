# US-22 — Settings shell

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P0 |
| **Blocked by** | US-05 Settings store, US-11 Pointer and touch input |
| **Blocks** | US-23 Wi-Fi, US-25 Account management, US-27 Sync settings, US-28 Regional preferences, US-29 Brightness control, US-31 Status screen |
| **Phase** | 3. Setup and Settings |

## Story

> As a user, I want a settings area, reached from the main screen, with clear sections and a way back to the calendar.

## Context

Settings is where everything from the first-time setup can be changed later: network, accounts and calendars, syncing, display, preferences, and status. This story builds the **frame** that all those sections plug into, plus a **small library of touch-friendly setting rows and overlays**. Each later story then only builds its own section's content.

Getting this frame right saves a lot of work later:
- **The section registry**: each story registers its section with an id, a title, an order, and a factory. The shell builds the sidebar from the registry. Adding a section doesn't mean editing the shell.
- **Lazy building**: a section's widgets are built the first time it's opened, which keeps opening Settings fast (the US-36 target: < 250 ms).
- **Visibility hooks** (`on_show`/`on_hide` per section), so for example Wi-Fi scanning only runs while that section is visible.
- **Reusable content**: section content is built so the **setup wizard (US-32) can reuse it** (the same Wi-Fi picker, account form, preference rows). That's a design requirement from day one.
- **The row library**: switches, segmented choices, a full-page list picker, steppers, button rows, and info rows. All ≥ 72 px tall, following US-11.
- **In-app overlays**: a confirm dialog and a toast. **Not `Gtk.AlertDialog`/`Gtk.MessageDialog`**: separate windows are awkward under cage, and `AlertDialog` needs GTK ≥ 4.10.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-05** Settings store | `app.settings` with `get/set/subscribe`, the key registry | `grep -n "def subscribe" calpi/data/settings_store.py`. The settings tests pass. |
| **US-11** Pointer and touch input | Input conventions, `KeyRouter` + screen `on_key`, `CALPI_CHECK_TARGETS`, the focus ring, `* { transition: none }` | `grep -n "class KeyRouter" calpi/input.py`. |

### Soft dependencies
- **US-06** `MonthView.header.end_slot`: where the Settings button goes. (It's on the critical path, so it'll be there.)
- **US-08** `window.inactivity`: to return to the calendar after 10 minutes. If it's missing, skip that criterion and note it.
- **US-21** `window.keyboard`: sections with text fields use it. The shell must hide the keyboard when switching sections (`keyboard.hide()`), if it exists.
- **US-03** for checking on the Pi.

### External blockers
None.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| `Gtk.Switch` is tiny by default | Enlarge it with CSS (`switch { min-width: 110px; min-height: 56px; } switch slider { min-width: 52px; min-height: 52px; }`), **and** make the whole row clickable to toggle it. Check how it looks on the Pi. |
| `Gtk.DropDown` popovers are small and fiddly for touch | Don't use them. Use a segmented `ChoiceRow` for ≤ 5 options, and a full-page `ListPicker` for longer lists (D4). |
| A semi-transparent backdrop for dialogs looks slow | With the cairo renderer, one full-screen blend when the dialog opens is fine, as long as nothing underneath redraws continuously. If it's slow on the Pi, use an opaque backdrop. |
| A section factory raises an exception | The shell must catch it, log it, and show "This section couldn't be loaded" in its place. Settings must never crash the app. |

---

## Scope

### In scope
- `calpi/widgets/settings/shell.py`: `SettingsScreen` (screen name `settings`), the section registry, the sidebar, the content stack, the back button, lazy building, visibility hooks, and the inactivity return.
- `calpi/widgets/settings/rows.py`: `SettingsGroup`, `SwitchRow`, `ChoiceRow`, `ListPickerRow` + `ListPickerPage`, `StepperRow`, `ButtonRow`, `InfoRow`.
- `calpi/widgets/overlays.py`: `ConfirmDialog`, `Toast` (an app-wide instance), and a `BlockingOverlay` ("Connecting…").
- `calpi/widgets/settings/about.py`: the **About** section (version, build, IP address, uptime), which is the one real section this story ships.
- The Settings button (⚙) in the calendar header, plus a keyboard shortcut.
- CSS for all of the above.

### Out of scope
- The real content of the other sections: Network (US-23/24), Accounts (US-25), Calendars (US-26), Sync (US-27), Preferences (US-28), Display (US-29/30), Status (US-31). **Only register sections that are implemented.** No "coming soon" placeholders.
- The wizard (US-32). But design for reuse (D5).

---

## Acceptance criteria

1. The calendar header has a **⚙ Settings** button (≥ 72 × 72 px) at the far right. Tapping it opens the `settings` screen in **under 250 ms** on the Pi (with About as the only section, and measured the same way as `month_render`).
2. The Settings screen layout: a header with `← Calendar` (≥ 88 × 72) and the title "Settings". A left **sidebar** (about 380 px wide) with one large entry per registered section (≥ 88 px tall, with the selected one highlighted). The selected section's content on the right, in a vertical `Gtk.ScrolledWindow`.
3. Sections appear in the registry `order`. The first time Settings opens, the first section is selected. After that, the last selected section is remembered **for as long as the app is running** (not persisted).
4. A section's content is built **the first time it's selected**, and kept afterwards. `on_show()` / `on_hide()` are called when it becomes visible or hidden, including when the whole Settings screen is shown or hidden.
5. `← Calendar`, **Escape**, and (after **10 minutes** with no input) the inactivity return all go back to the calendar. The inactivity return **doesn't** happen while a `BlockingOverlay` is shown (for example "Connecting…").
6. Keyboard: Up/Down move between sidebar entries when the sidebar has focus, Tab reaches the content, and `s` on the calendar screen opens Settings.
7. **The row library** (each row ≥ 72 px tall, full width, the label on the left and the control on the right, an optional dimmed description underneath):
   - `SwitchRow(title, key=None, getter/setter=None, description=None)`: a large switch. Tapping anywhere on the row toggles it. Bound to a settings key, writes on toggle, and updates when the setting changes elsewhere (it subscribes and unsubscribes).
   - `ChoiceRow(title, options=[(value, label)], key=...)`: segmented buttons (2–5 options), ≥ 110 × 72 each, with the selected one filled.
   - `ListPickerRow(title, value_label, open_picker)` + `ListPickerPage(title, items, on_pick, search=False)`: a full-page list with rows ≥ 80 px, kinetic scrolling, and an optional search entry (using the OSK). It replaces the section content while open, with its own back button.
   - `StepperRow(title, value, min, max, step, format, on_change)`: `−` value `+`, with buttons ≥ 88 × 72. It commits on each tap, but writes to settings **debounced by 500 ms** (the US-05 D5 rule).
   - `ButtonRow(title, button_label, on_click, destructive=False)`.
   - `InfoRow(title, value)`: read-only. Updates only when the text changes.
8. **Overlays** on `window.overlay`:
   - `ConfirmDialog.ask(title, body, confirm_label, on_confirm, destructive=False, cancel_label="Cancel")`: a centred panel (about 900 × 420) on a dimmed backdrop. Buttons ≥ 200 × 88. Escape = cancel. Only one at a time.
   - `app.toast(text, seconds=4)`: a bottom-centre label that disappears on its own, never covering the header controls. A newer toast replaces an older one.
   - `BlockingOverlay.show(text)` / `.hide()`: a full-screen "please wait" panel ("Connecting to Wi-Fi…"), static text, no spinner.
9. **About section**: app version and build stamp (US-03), IP address(es) (read without blocking, D6), uptime, the state directory path, and the OS release (from `/etc/os-release`). Values refresh when the section is shown.
10. A section that raises while being built shows an error placeholder, and the rest of Settings keeps working (a test with a deliberately failing factory).
11. `CALPI_CHECK_TARGETS=1` reports no small targets on the Settings screen, About, the confirm dialog, and a demo list picker.
12. Opening and closing Settings 100 times doesn't grow the widget count (the sections are built once) or the RSS (by more than 2 MB).

---

## Design decisions (already made)

- **D1. The registry** (`shell.py`):
  ```python
  @dataclass(frozen=True)
  class SectionSpec:
      id: str                          # "network", "accounts", "calendars", "sync", "display", "preferences", "status", "about"
      title: str
      order: int                       # network 10, accounts 20, calendars 30, sync 40, display 50, preferences 60, status 70, about 90
      factory: Callable[["SectionContext"], "Section"]
      available: Callable[[Any], bool] = lambda app: True

  SECTIONS: dict[str, SectionSpec] = {}
  def register_section(spec: SectionSpec) -> None: ...
  ```
  Sections register themselves when their module is imported. The shell imports a fixed list of section modules in `calpi/widgets/settings/__init__.py` (`from . import about` plus the others as they're added). Keep that list in **one** place.
- **D2. The `Section` protocol**: `widget: Gtk.Widget`, and optional `on_show()`, `on_hide()`, `on_key(name, state) -> bool`, `dispose()`. Hold subscriptions in the section and remove them in `dispose()` (called only at app shutdown, since sections live for the whole app).
- **D3. `SectionContext`**: `app`, `window`, `mode` (`"settings"` or `"wizard"`), `navigate_back()`, `push_page(widget, title)` / `pop_page()` (for sub-pages such as the list picker or an account form: a small page stack **inside** the content area).
- **D4. Choosing among many options** uses a full-page `ListPickerPage` pushed with `ctx.push_page`, **never** a popover or dropdown.
- **D5. Reuse by the wizard**: a section factory must work in both modes. In `"wizard"` mode, sections may hide advanced rows, and must not assume the sidebar exists. Content widgets must not reach into `SettingsScreen` directly; everything goes through `ctx`. **This is a contract that US-23, US-25, US-27, US-28, and US-30 follow.**
- **D6. The IP address** for About: read `/proc/net/fib_trie` or run `ip -4 -brief addr` in a worker thread (`run_in_thread`). **Never** a blocking subprocess on the main thread. Simple option: `socket.getaddrinfo` doesn't help, so use `ip -j addr` (JSON) in a worker and parse it. `ip` is always installed on Pi OS.
- **D7. Immediate apply**: setting rows write straight away. There's no "Save" button. Multi-field forms (Wi-Fi password, account sign-in) have an explicit action button.
- **D8. Settings' inactivity timeout** = 600 s, registered with `window.inactivity.add_idle_callback(600, ...)`, and it only acts if `navigator.current == "settings"` and no `BlockingOverlay` is visible.

---

## Implementation plan

### Step 1 — Overlays (`calpi/widgets/overlays.py`)
Build these first, because sections need them.
```python
class ConfirmDialog(Gtk.Box):
    """Full-window overlay: dim backdrop + centered panel. One instance, reused."""
    def __init__(self, window):
        super().__init__(css_classes=["modal-backdrop"], hexpand=True, vexpand=True)
        self.set_visible(False)
        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, css_classes=["modal-panel"],
                             halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(css_classes=["modal-title"], wrap=True)
        self.body = Gtk.Label(css_classes=["modal-body"], wrap=True, max_width_chars=48)
        btns = Gtk.Box(spacing=24, halign=Gtk.Align.END)
        self.cancel = Gtk.Button(css_classes=["modal-button"]); self.ok = Gtk.Button(css_classes=["modal-button"])
        btns.append(self.cancel); btns.append(self.ok)
        for w in (self.title, self.body, btns): self.panel.append(w)
        self.append(self.panel)
        self.cancel.connect("clicked", lambda *_: self._close(False))
        self.ok.connect("clicked", lambda *_: self._close(True))
        window.overlay.add_overlay(self)
        self._cb = None

    def ask(self, title, body, confirm_label, on_confirm, destructive=False, cancel_label="Cancel"):
        ...; set_class(self.ok, "destructive", destructive); self.set_visible(True); self.cancel.grab_focus()

    def _close(self, confirmed):
        self.set_visible(False); cb, self._cb = self._cb, None
        if confirmed and cb: cb()
```
- The backdrop catches all clicks (it's a visible, targetable box covering everything), so taps don't reach the screen underneath.
- Escape while it's visible → cancel. Handle that in `KeyRouter` before the screens: check the overlays in order (the confirm dialog, then the keyboard, then the screen).
- Focus goes to **Cancel** by default, so Enter on a physical keyboard doesn't confirm a destructive action by accident.

`Toast`: a label in an overlay (`halign=CENTER`, `valign=END`, `margin_bottom=40`), shown by `app.toast(text)`. Hidden by a one-shot timer (cancel the previous timer if a new toast comes). **`can_target=False`**, so it never blocks taps.

`BlockingOverlay`: like the backdrop, with a single large label. `show(text)` / `hide()`. While it's visible, `KeyRouter` ignores Escape (the operation can't be cancelled there; sections provide a Cancel button inside it if needed: `show(text, on_cancel=None)` adds a Cancel button when given).

The z-order matters: the overlays added later are on top. The order of creation in `MainWindow`: keyboard dock (US-21) → confirm dialog → blocking overlay → toast. The keyboard must sit **above** screens but **below** the dialogs. Adjust the creation order, or use `Gtk.Overlay.reorder_overlay` if needed.

### Step 2 — Rows (`calpi/widgets/settings/rows.py`)
A common base:
```python
class _Row(Gtk.Box):
    def __init__(self, title, description=None):
        super().__init__(css_classes=["settings-row"], spacing=24)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(label=title, xalign=0, css_classes=["row-title"], wrap=True)
        texts.append(self.title)
        self.description = Gtk.Label(label=description or "", xalign=0, css_classes=["row-desc"], wrap=True)
        self.description.set_visible(bool(description)); texts.append(self.description)
        self.append(texts)
```
- `SwitchRow`: adds a `Gtk.Switch` (`valign=CENTER`) and a `Gtk.GestureClick` on the row that toggles the switch when the tap wasn't on the switch itself. If `key` is given: initial value = `settings.get(key)`, `notify::active` → `settings.set(key, value)` (catch `ValueError`/`OSError`, show a toast "Couldn't save setting", and revert the switch). Subscribe to the key to follow external changes, and **guard against feedback loops** (don't re-set when the values are equal).
- `ChoiceRow`: a `Gtk.Box` of `Gtk.ToggleButton`s grouped with `set_group` (GTK 4 radio-style toggles). The selection writes the key.
- `StepperRow`: `−` / value label / `+`. The value updates on each tap. The write is debounced by 500 ms (one GLib timer, re-armed on each tap). On `on_hide`, flush any pending write at once.
- `ListPickerPage`: an optional search `Gtk.Entry` at the top (attached to the OSK with purpose `text`), then a `Gtk.ScrolledWindow` → `Gtk.ListBox` (with `selection_mode=NONE`, rows activated by tap). **Filtering**: `ListBox.set_filter_func`, with `invalidate_filter()` on text change, **debounced by 150 ms** (400 time zones × filtering on each key press is fine, but debounce anyway). Each row: a label ≥ 80 px tall, with a check mark `✓` on the current value. For long lists (400+ time zones), build the rows **once, when the page is first opened**, and keep them.
- `SettingsGroup(title)`: a heading label plus a vertical box of rows with a rounded `@surface` background.

### Step 3 — The shell (`shell.py`)
```python
class SettingsScreen(Gtk.Box):
    def __init__(self, app, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["screen", "settings"])
        # header: back button + title
        # body: sidebar (Gtk.Box of Gtk.ToggleButton grouped) | content (Gtk.Stack NONE transition)
        self._sections: dict[str, Section] = {}
        self._selected: str | None = None
        self._page_stacks: dict[str, list[Gtk.Widget]] = {}     # per section sub-pages (D3)

    def on_show(self, section: str | None = None, **_):
        self._rebuild_sidebar_if_needed()            # registry may have 'available' changes
        self.select(section or self._selected or self._first_id())
        cur = self._sections.get(self._selected)
        if cur and hasattr(cur, "on_show"): cur.on_show()

    def on_hide(self):
        cur = self._sections.get(self._selected)
        if cur and hasattr(cur, "on_hide"): cur.on_hide()
        if getattr(self.window, "keyboard", None): self.window.keyboard.hide()

    def select(self, section_id: str): ...  # on_hide old, build lazily (try/except → placeholder), stack switch, on_show new
```
Put the whole content area of a section in a `Gtk.ScrolledWindow` (vertical scrolling only), wrapping a `Gtk.Box` with padding. `push_page(widget, title)` adds a sub-page with a header row "`← <title of the previous page>`" into the same content stack, and `pop_page()` goes back. Escape pops a sub-page first, and only then leaves Settings (the section's `on_key` → the shell).

**The Settings button**: `Gtk.Button(label="⚙")`, css `nav-button header-icon`, appended to `month_view.header.end_slot` last (the far right). Click → `navigator.show("settings")`. Key `s` in `MonthView.on_key`.

**The inactivity return**: `window.inactivity.add_idle_callback(600, self._idle)` → if `navigator.current == "settings"` and the blocking overlay isn't visible → `navigator.reset("calendar")` (or `show("calendar")`).

### Step 4 — The About section (`about.py`)
Rows: `InfoRow("Version", __version__)`, `InfoRow("Build", build_stamp)`, `InfoRow("IP address", "…")`, `InfoRow("Uptime", ...)`, `InfoRow("System", PRETTY_NAME)`, `InfoRow("Data folder", str(paths.state_dir()))`. `on_show`: start `run_in_thread(_collect)` for the IP and uptime (read `/proc/uptime`), and fill them in via `on_done`. Show "…" until then.

Register it: `register_section(SectionSpec("about", "About", 90, AboutSection))`.

### Step 5 — CSS
```css
.settings .sidebar       { min-width: 380px; background: #0d1216; padding: 16px; }
.sidebar-item            { min-height: 88px; font-size: 30px; border-radius: 14px; margin: 4px 0; background: none; }
.sidebar-item:checked    { background: @surface; color: @text; }
.settings-content        { padding: 32px 48px; }
.settings-group          { background: @surface; border-radius: 16px; margin-bottom: 32px; }
.settings-group-title    { font-size: 24px; color: @text_dim; margin: 0 0 12px 8px; }
.settings-row            { min-height: 88px; padding: 12px 24px; border-bottom: 1px solid alpha(@text, 0.06); }
.row-title               { font-size: 28px; }
.row-desc                { font-size: 20px; color: @text_dim; }
switch                   { min-width: 110px; min-height: 56px; }
switch slider            { min-width: 52px; min-height: 52px; }
.choice-button           { min-width: 110px; min-height: 72px; font-size: 24px; }
.choice-button:checked   { background: @accent; color: @bg; }
.modal-backdrop          { background-color: alpha(black, 0.6); }
.modal-panel             { background: @surface; border-radius: 24px; padding: 48px; min-width: 900px; }
.modal-title             { font-size: 40px; }
.modal-body              { font-size: 26px; color: @text_dim; }
.modal-button            { min-width: 200px; min-height: 88px; font-size: 28px; border-radius: 16px; }
.modal-button.destructive{ background: @danger; color: white; }
.toast                   { background: #2b3642; border-radius: 999px; padding: 18px 36px; font-size: 26px; }
```

### Step 6 — Tests
Pure logic, no display:
- The registry: ordering, duplicate ids rejected, `available` filtering.
- The stepper debounce logic: split the timing decisions into a tiny pure class (`Debouncer` with an injectable clock and scheduler) and test it.

GTK (`CALPI_GTK_TESTS=1`), with `--exit-after` hooks:
- Open Settings → the log shows `screen=settings` and `settings: section about shown`.
- A deliberately failing test section (`CALPI_TEST_BAD_SECTION=1`) → the placeholder, and no crash.
- The 100× open/close leak check (the `count_widgets` helper from US-06).

Manual in Broadway: every row type in a **dev demo section** (register it only with `CALPI_DEV_ROWS=1`): switch, choice, stepper, list picker with 400 items and search, confirm dialog, toast, blocking overlay. Test with the mouse and the keyboard.

### Step 7 — The Pi
Deploy. Open Settings with the mouse and time it. Take a screenshot of Settings → About, and of the demo section (a temporary `CALPI_DEV_ROWS=1` drop-in; **remove it afterwards**). Check the switch size and legibility. `CALPI_CHECK_TARGETS=1`: no violations. Scroll the 400-item list picker: it must feel smooth enough (no multi-second stalls). If it doesn't, look into lighter rows (a plain `Gtk.Label` inside `Gtk.ListBoxRow`, no nested boxes).

---

## Files

| File | Change |
|---|---|
| `calpi/widgets/overlays.py` | New |
| `calpi/widgets/settings/__init__.py`, `shell.py`, `rows.py`, `about.py` | New |
| `calpi/widgets/settings/dev_rows.py` | New (dev demo, flag-gated) |
| `calpi/app.py` | Settings screen, overlays, `app.toast`, header button, Escape order |
| `calpi/input.py` | `KeyRouter`: the overlay-first Escape order |
| `calpi/widgets/month_view.py` | `s` key |
| `calpi/style.css` | Settings, rows, and overlay styles |
| `tests/test_settings_registry.py`, `tests/test_debouncer.py` | New |

---

## Pitfalls

- **Building every section when Settings opens.** Build lazily (acceptance criterion 4).
- **Sections reaching into the shell** instead of using `ctx`. That breaks wizard reuse (D5).
- **Popovers and dropdowns** for choices. Use full-page pickers.
- **Settings feedback loops** (row → set → subscribe → row → set…). Compare before setting.
- **Destructive confirm buttons focused by default.** Cancel gets the focus.
- **A toast that blocks taps.** `can_target=False`.
- **Blocking the main loop in About** (a subprocess). Use `run_in_thread`.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] The demo section checked in Broadway and on the Pi (then the flag removed).
- [ ] Open time and screenshots from the Pi recorded.
- [ ] The section-reuse contract (D5) written in the `shell.py` docstring.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `register_section(SectionSpec(id, title, order, factory, available))`, the module list in `settings/__init__.py` | US-23, US-24, US-25, US-26, US-27, US-28, US-29, US-30, US-31, US-33 |
| `Section` protocol (`widget`, `on_show`, `on_hide`, `on_key`, `dispose`), `SectionContext` (`app`, `window`, `mode`, `push_page`, `pop_page`, `navigate_back`) | same, plus US-32 (wizard mode) |
| Rows: `SettingsGroup`, `SwitchRow`, `ChoiceRow`, `ListPickerRow`/`ListPickerPage`, `StepperRow`, `ButtonRow`, `InfoRow` | all settings sections, US-32 |
| `ConfirmDialog.ask(...)`, `app.toast(text)`, `BlockingOverlay.show/hide` | US-23, US-24, US-25, US-26, US-32, US-38 |
| `navigator.show("settings", section="network")`: open a specific section | US-31, US-38 ("Fix" buttons), US-32 |
| The section order numbers (D1) | all sections |
| Settings returns to the calendar after 10 minutes (not while a blocking overlay is shown) | US-23 (while connecting) |
