# US-32 — First-time setup wizard

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P0 |
| **Blocked by** | US-23 Wi-Fi scan and connect, US-25 Account management, US-27 Sync settings, US-28 Regional preferences |
| **Blocks** | — (it completes the P0 set) |
| **Phase** | 3. Setup and Settings |

## Story

> As a new user, I want a guided setup on first boot that covers Wi-Fi, preferences, account sign-in, calendar selection and refresh timing, with every step skippable. The dimming step is added once US-30 is done.

## Context

This is the last P0 story. When it's done, a new owner can take a freshly flashed device out of the box, power it on, and get it fully working **from its own screen**. The plan's first-time setup:
1. Connect to a Wi-Fi network.
2. Set the time zone and basic preferences.
3. Sign in to a calendar account (iCloud first) and choose which calendars to show.
4. Choose how often to refresh (and whether to dim overnight, once US-30 exists).

"Every step can be skipped and finished later from Settings. After setup, the device goes straight to the calendar on every boot."

Almost everything is **reuse**: the step bodies are the same components the Settings sections use, built for this from the start (US-22 D5):

| Step | Component | From |
|---|---|---|
| Wi-Fi | `WifiPicker(ctx, on_connected)` | US-23 |
| Preferences | `PreferencesPanel(ctx)` | US-28 |
| Account + calendars | `SignInFlow(ctx, on_finished)` (the calendar selection is part of the flow) | US-25 |
| Refresh | `IntervalChooser(ctx, on_changed)` | US-27 |
| Overnight (if US-30 is done) | `DimSchedulePanel(ctx)` | US-30 |

This story builds the **wizard frame** (the step sequence, progress, Back/Skip/Next, resuming after a power cut, and deciding when to show it) and a `SectionContext` for wizard mode.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-23** Wi-Fi scan and connect | `WifiPicker(ctx, on_connected)` that works with `ctx.mode == "wizard"` | `grep -n "class WifiPicker" calpi/widgets/settings/network.py`. Connect works on the Pi. |
| **US-25** Account management | `SignInFlow(ctx, on_finished, existing=None)`, sign-in + calendar selection, saving + a sync | `grep -n "class SignInFlow" calpi/widgets/settings/accounts.py`. Adding an account works on the Pi. |
| **US-27** Sync settings | `IntervalChooser(ctx, on_changed)` | `grep -n "class IntervalChooser" calpi/widgets/settings/sync.py` |
| **US-28** Regional preferences | `PreferencesPanel(ctx)` (zone picker, week start, time format) | `grep -n "class PreferencesPanel" calpi/widgets/settings/preferences.py` |

All four imply US-22 (`SectionContext`, rows, overlays), US-21 (the keyboard), US-05 (settings), and US-16 (sync).

### Soft dependencies
- **US-30** Overnight: if `DimSchedulePanel` exists, include the Overnight step. If it doesn't, leave it out (US-30 adds it later: see its step 7).
- **US-33** iCloud guide: `SignInFlow` shows the guide link when the guide exists. Nothing to do here.
- **US-12** safe mode: in safe mode, **don't** start the wizard automatically (show the calendar plus the safe-mode notice). The owner can still start it from About.

### External blockers

| Blocker | What to do |
|---|---|
| **A "fresh device" to test on** | Test by using an **empty state directory**: stop the service, move `/var/lib/calpi` aside (`sudo mv /var/lib/calpi /var/lib/calpi.bak`), and start again. **Put it back afterwards** (or keep the new state if the owner is happy with it). Also forget the Wi-Fi network to test the Wi-Fi step for real, **only with Ethernet or the scheduled restore** (US-23 step 7). **Ask the owner first**: this temporarily removes their account and settings from the device. |
| **The owner's Wi-Fi and iCloud credentials** | They type them on the device. |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| The components assume `push_page` exists | The wizard's `SectionContext` must implement `push_page`/`pop_page` with its own page stack inside the step body (D3). |
| The account step while offline | `SignInFlow` shows the network error. The wizard adds a note on that step: "Needs an internet connection. You can skip this and add an account later in Settings → Accounts." |
| An existing (developer) device suddenly shows the wizard after this story is deployed | Migration rule (D1): if `setup_completed` is false **but accounts already exist**, mark it completed silently at startup. |
| The inactivity return (US-08/US-22) leaves the wizard | The wizard never auto-returns (D6). Make sure the US-08 return only acts on `calendar`/`day`, and US-22's on `settings`. |

---

## Scope

### In scope
- `calpi/widgets/wizard/`: `SetupWizard` (the screen `"wizard"`), the step registry, `WizardContext`, the step pages (Welcome, Wi-Fi, Preferences, Account, Refresh, [Overnight], Done).
- The "show at startup" decision, and the migration for existing installs.
- Resuming at the saved step after a restart or power cut (`K_WIZARD_STEP`).
- "Run setup again" in Settings → About.
- Tests for the flow logic (pure) and the GTK wiring.

### Out of scope
- New settings: the wizard only uses existing components.
- Factory reset (wiping all data): not requested. "Run setup again" keeps the existing data.

---

## Acceptance criteria

1. **When it's shown**: at startup, if `setup_completed` is false (and not in safe mode), the app shows the `wizard` screen instead of the calendar. When it's finished or skipped to the end, `setup_completed = True`, and later boots go straight to the calendar.
2. **Migration**: if `setup_completed` is false but at least one account exists (a device set up before the wizard existed), set `setup_completed = True` at startup and show the calendar.
3. **Steps in order**: Welcome → Wi-Fi → Preferences → Calendar account → Refresh → (Overnight, if US-30) → Done. The header shows the step title and "Step N of M" (Welcome and Done don't count).
4. **Every step** has **Back** (except Welcome), **Skip** (except Welcome and Done), and **Next** / **Finish** buttons, ≥ 200 × 88 px, in a fixed footer. The footer stays visible above the on-screen keyboard: when the keyboard is shown, the footer moves up, or the step content is arranged so the footer isn't covered. **Decision**: hide the footer while the keyboard is visible, because the keyboard's Done key drives the form (the footer comes back when the keyboard hides).
5. **Welcome**: "Welcome to calpi" + one sentence + **Start**.
6. **Wi-Fi**: `WifiPicker`. If the device is **already online** (Ethernet, or Wi-Fi from flashing), the step shows "Connected to <SSID/Ethernet>" at the top, and Next is the main action. A successful connect moves on automatically after 1 s.
7. **Preferences**: `PreferencesPanel`. The defaults are already the right choices (the system zone, Monday, 24h), so Next works without changing anything.
8. **Calendar account**: an "Add iCloud account" button starts `SignInFlow` inside the step. When it's finished (account saved, calendars selected), the step shows "Added <Apple ID> · N calendars" plus "Add another account" and Next. If it's offline, the D-note is shown.
9. **Refresh**: `IntervalChooser` (default 15 minutes, labelled "recommended").
10. **Overnight** (only if US-30): `DimSchedulePanel`.
11. **Done**: "You're all set" + a summary (Wi-Fi: connected/skipped, Account: added/skipped, Refresh: every 15 minutes) + **Show calendar** → `setup_completed = True`, `wizard_step = None`, `navigator.reset("calendar")`. If an account was added, a sync is already running (US-25).
12. **Resuming**: the current step id is saved in `K_WIZARD_STEP` on every step change. After a restart or power cut, the wizard resumes at that step. (The in-progress form content isn't restored: that's acceptable.)
13. **Run setup again**: Settings → About has **Run setup again** → confirm → `setup_completed = False`, `wizard_step = None` → show the wizard now. Existing accounts and settings are kept, and the steps show their current values.
14. **No automatic exit**: the wizard ignores the inactivity returns. The Escape key acts as Back (and does nothing on Welcome).
15. The whole flow works with the mouse (and the physical keyboard) in Broadway **and** on the Pi. Every target ≥ 72 px (`CALPI_CHECK_TARGETS=1`).

---

## Design decisions (already made)

- **D1. The startup decision** (`calpi/data/setup_state.py`, pure): `decide_start_screen(settings_snapshot, accounts_count, safe_mode) -> ("wizard" | "calendar", migrations: dict)`. The migration sets `setup_completed=True` when accounts exist.
- **D2. The step registry**: a list of `StepSpec(id, title, factory, counted=True, skippable=True, available=lambda app: True)`. The Overnight step's `available` checks that `DimSchedulePanel` can be imported (`importlib.util.find_spec("calpi.dimming")`, or a feature flag on the app).
- **D3. `WizardContext`** implements the `SectionContext` protocol (US-22): `app`, `window`, `mode="wizard"`, `push_page(widget, title)` / `pop_page()` (a page stack *inside* the current step body; while a sub-page is open, the wizard footer's Back button pops the sub-page first), and `navigate_back()` (= the wizard's Back).
- **D4. Skip** only moves to the next step. It doesn't change any setting. Steps have **no** "skip everything" (it's easy enough to press Skip several times, and the Done summary shows what was skipped).
- **D5. Persistence**: `K_WIZARD_STEP` (str | None) is written on each step change. `K_SETUP_COMPLETED` (from US-05) is written at the end.
- **D6. Inactivity**: no return while `navigator.current == "wizard"`. The wizard registers no idle callback.
- **D7. The step result flags** (for the Done summary) are kept in memory only: `{"wifi": "connected"|"skipped"|"already", "account": "added"|"skipped", ...}`. After a resume, steps that weren't visited in this session show "set earlier" if their data exists (for example, an account exists → "added").

---

## Implementation plan

### Step 1 — Pure pieces (`calpi/data/setup_state.py`)
```python
def decide_start_screen(setup_completed: bool, accounts: int, safe_mode: bool) -> tuple[str, dict]:
    if safe_mode: return "calendar", {}
    if not setup_completed and accounts > 0: return "calendar", {"setup_completed": True}
    return ("wizard" if not setup_completed else "calendar"), {}

def next_step(steps: list[str], current: str) -> str | None: ...
def prev_step(steps: list[str], current: str) -> str | None: ...
def resume_step(steps: list[str], saved: str | None) -> str:        # saved not in steps (e.g. the Overnight step removed) -> "welcome"
def progress(steps_counted: list[str], current: str) -> tuple[int, int] | None: ...
```
Register `K_WIZARD_STEP` in settings. Tests: every branch, resume with an unknown step, progress numbers with and without Overnight.

### Step 2 — `WizardContext` and the frame (`calpi/widgets/wizard/wizard.py`)
```
SetupWizard (Gtk.Box vertical, css "screen wizard")
├─ header: title label (48px) + progress label ("Step 2 of 5")
├─ body: Gtk.Stack (NONE) — one child per step instance (built lazily when first reached); each step body has its own inner page stack (D3)
└─ footer: [Back]            [Skip] [Next]
```
```python
class SetupWizard(Gtk.Box):
    def __init__(self, app, window):
        self.steps = [s for s in STEPS if s.available(app)]
        self._built: dict[str, Step] = {}
        self.ctx = WizardContext(app, window, self)
    def on_show(self, **_):
        self.go(resume_step([s.id for s in self.steps], self.app.settings.get(K_WIZARD_STEP)))
    def go(self, step_id): ... build lazily; on_hide old / on_show new; set header, progress, footer buttons; settings.set(K_WIZARD_STEP, step_id)
    def next(self): ...; def back(self): ...; def skip(self): ...
    def finish(self):
        self.app.settings.update({K_SETUP_COMPLETED: True, K_WIZARD_STEP: None})
        self.window.navigator.reset("calendar")
    def on_key(self, name, state):
        if name == "Escape": self.back(); return True
        return False
```
The footer hides while the keyboard is shown: the dock (US-21) calls `on_keyboard_visible(bool)` on the current screen, if it exists (US-21 D6). Implement that here.

### Step 3 — The steps (`calpi/widgets/wizard/steps.py`)
Each step is a small class with `widget`, optional `on_show`/`on_hide`, and `next_label` (e.g. "Start", "Next", "Show calendar"):
- `WelcomeStep`: a big title, a sentence ("Let's connect calpi to Wi-Fi and your calendars. You can skip any step and change everything later in Settings."), and the footer's Next labelled **Start**.
- `WifiStep`: `WifiPicker(ctx, on_connected=lambda ssid: (self.result("connected"), GLib.timeout_add_seconds(1, ...next)))`. On show: check `app.network.state` (US-17) or `nmcli device` in a worker. If it's already online, show the "Connected to …" banner.
- `PreferencesStep`: `PreferencesPanel(ctx)`.
- `AccountStep`: an intro, the offline note if `app.network.state` isn't ONLINE, the "Add iCloud account" button → `SignInFlow(ctx, on_finished=self._added).start()`. `_added(acc)` → shows the summary line + "Add another account". The result is "added".
- `RefreshStep`: `IntervalChooser(ctx)` + a sentence.
- `OvernightStep` (conditional): `DimSchedulePanel(ctx)`.
- `DoneStep`: the summary rows (from D7) and the footer's Finish labelled **Show calendar**.

### Step 4 — The startup decision and migration (`calpi/app.py`)
After settings, credentials, and the store are loaded, and before choosing the first screen:
```python
screen, mig = setup_state.decide_start_screen(self.settings.get(K_SETUP_COMPLETED),
                                              len(accounts.list_accounts(self.settings)), self.safe_mode)
if mig: self.settings.update(mig); log.info("setup: marked complete (existing accounts)")
self.window.navigator.add("wizard", SetupWizard(self, self.window))
self.window.navigator.reset(screen)
log.info("setup: start screen=%s", screen)
```
**While the wizard is showing, the sync engine still runs normally** (there's nothing to sync without accounts, and after an account is added, it syncs straight away).

### Step 5 — "Run setup again" (About, US-22)
A `ButtonRow("Setup", "Run setup again", ...)` → `ConfirmDialog.ask("Run setup again?", "Your accounts and settings are kept. You can change them as you go.", "Start", ...)` → `settings.update({K_SETUP_COMPLETED: False, K_WIZARD_STEP: None})` → `navigator.reset("wizard")`.

### Step 6 — Tests
- Pure (step 1).
- GTK flow (Broadway, fakes for the components: monkeypatch `WifiPicker`/`SignInFlow` with small stubs that call their callbacks): a fresh state → the wizard shows. Skip through every step → Done → `setup_completed` true → the calendar. A restart with `wizard_step="refresh"` → resumes at Refresh. Existing accounts + not completed → the calendar (migration). Escape = Back. Footer hidden while the keyboard is shown.
- `smoke.sh` variant: an empty state directory → the log contains `setup: start screen=wizard`.

### Step 7 — End-to-end on the Pi (with the owner's agreement)
1. **Get the owner's OK**, then connect Ethernet (or schedule a Wi-Fi restore).
2. `sudo systemctl stop calpi-kiosk && sudo mv /var/lib/calpi /var/lib/calpi.bak && sudo systemctl start calpi-kiosk`.
3. (Optional, with Ethernet) forget the Wi-Fi profile to test the Wi-Fi step for real.
4. Go through the wizard with the mouse and OSK: Wi-Fi (the owner types the password), Preferences, Account (the owner types the Apple ID and app-specific password), select calendars, Refresh, (Overnight), Done → the calendar with real events within a minute.
5. Pull the power partway through the wizard once (with the owner's OK) → it resumes at the saved step.
6. Reboot → straight to the calendar.
7. Decide with the owner: keep the new state, or restore the old one (`sudo systemctl stop calpi-kiosk && sudo rm -rf /var/lib/calpi && sudo mv /var/lib/calpi.bak /var/lib/calpi && sudo systemctl start calpi-kiosk`). **Either way, remove whichever copy isn't used**, so there aren't two copies of the credentials lying around.
8. Take screenshots of each step.

---

## Files

| File | Change |
|---|---|
| `calpi/data/setup_state.py` | New |
| `calpi/data/settings_store.py` | `K_WIZARD_STEP` |
| `calpi/widgets/wizard/__init__.py`, `wizard.py`, `steps.py` | New |
| `calpi/widgets/settings/about.py` | "Run setup again" |
| `calpi/app.py` | The start-screen decision, registering the wizard |
| `calpi/style.css` | Wizard styles (header, footer, big buttons) |
| `tests/test_setup_state.py`, `tests/test_wizard_flow.py` | New |

---

## Pitfalls

- **Showing the wizard to existing installs.** Apply the migration (D1).
- **Components reaching for the Settings sidebar or toasts in wizard mode.** The contexts must behave (US-22 D5). Fix the components if they don't.
- **The footer covered by the keyboard.**
- **Leaving the wizard on inactivity.**
- **Two copies of `/var/lib/calpi`** left after testing (the old credentials in the backup).
- **Forgetting Wi-Fi without a fallback** during the test.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] The full fresh-device flow done on the Pi, including resume after a power cut. Screenshots taken.
- [ ] Test state cleaned up (a single state directory kept, as the owner decided).
- [ ] **The P0 set is complete**: update `docs/stories.md` or the hand-off notes to say so.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `STEPS` registry (`StepSpec`) | US-30 (Overnight step), US-20 (provider-aware account step, optional) |
| `WizardContext` (a `SectionContext` in wizard mode) | any component reused in the wizard |
| `K_WIZARD_STEP`, `K_SETUP_COMPLETED` semantics | US-38 (don't show error banners during the wizard), US-31 |
| `setup: start screen=` log line | smoke tests |
