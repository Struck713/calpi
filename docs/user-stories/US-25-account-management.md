# US-25 — Account management

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P0 |
| **Blocked by** | US-14 iCloud account connection, US-21 On-screen keyboard, US-22 Settings shell |
| **Blocks** | US-26 Calendar customization, US-32 First-time setup wizard, US-33 iCloud setup guide |
| **Phase** | 3. Setup and Settings |

## Story

> As a user, I want to add and remove calendar accounts from Settings.

## Context

Until now, accounts were added with the developer CLI over SSH (US-14). This story puts account management **on the device**: an **Accounts** section in Settings where the owner can:
- **add** an iCloud account: enter the Apple ID and the app-specific password with the on-screen keyboard, sign in, and choose which of the discovered calendars to show;
- **see** each account and whether it's syncing properly;
- **update the password** when the old one stops working (app-specific passwords are revoked when the Apple ID password changes);
- **remove** an account, which deletes its secret, its record, its calendars, and their events from the device.

It ties together US-13 (credentials), US-14 (discovery and account records), US-04 (the calendars table), US-16 (triggering a sync), US-18 (status, if it's there), US-21 (keyboard), and US-22 (the section framework and dialogs). **The same sign-in flow is reused by the setup wizard (US-32).**

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-14** iCloud account connection | `icloud.discover(username, secret)`, `accounts.add_or_update_account/list_accounts/find_account`, `Account`, `RemoteCalendar`, `SyncError`/`ErrorCode`, `K_ACCOUNTS`; plus US-13's `CredentialStore`/`Secret` | `/usr/bin/python3 -m pytest tests/test_icloud.py tests/test_accounts.py tests/test_credentials.py` passes |
| **US-21** On-screen keyboard | `window.keyboard.attach(..., "email" / "password", done_label, on_done)`, `make_password_field()` | `grep -n "def make_password_field" calpi/widgets/keyboard.py` |
| **US-22** Settings shell | `register_section`, `SectionContext` (`push_page`/`pop_page`, `mode`), rows, `ConfirmDialog`, `BlockingOverlay`, `app.toast` | `grep -n "def register_section" calpi/widgets/settings/shell.py` |

### Soft dependencies

| Soft blocker | Why | If it isn't done |
|---|---|---|
| **US-04 / US-15** event store + `calendar_id_for` | Writing discovered calendars and the visibility choice into the store; deleting an account's calendars | On the critical path, so they're done. The README notes this gap in the formal graph. |
| **US-16** `app.sync.request_sync` | A sync right after adding | Required in practice (it's on the path before US-25 in the plan). |
| **US-18** `app.sync_status`, `sync_status.forget_account` | Per-account status lines; cleanup on removal | Show "Added" and no status. Skip `forget_account`, and put a TODO in the hand-off notes. |
| **US-20** providers | A provider chooser | iCloud only. Keep the chooser code path ready for more (D1). |
| **US-33** iCloud guide | The "How do I get an app-specific password?" link | Hide the link until US-33 exists (check whether the guide screen is registered). |

### External blockers

| Blocker | What to do |
|---|---|
| **The owner's Apple ID and a fresh app-specific password** | The owner types them **on the device** (mouse + OSK, or the physical keyboard). Never in chat. For the "update password" test, the owner generates a second app-specific password and revokes the first one afterwards (or keeps both). |
| **A wrong-password test** | The owner types a deliberately wrong password. Apple can rate-limit repeated failures, so **keep failed attempts to a few**. |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| A sync runs while an account is being removed, and puts its calendars back | The worker read the account list at *its* start. After removal, **reconcile** (D5): delete calendars whose `account_id` isn't in settings, both after the running sync finishes and at startup. |
| The discovery takes 5–15 s on a slow network | `BlockingOverlay` "Signing in…" with Cancel (the cancel just ignores the late result: you can't interrupt the worker thread's socket, but the timeout is 20 s per request). |
| Sample data (US-04) still shows next to the real calendars | Remove the sample calendars when the **first real account** is added (D6). |

---

## Scope

### In scope
- The **Accounts** section (`"accounts"`, order 20): the account list, per-account detail pages, and "Add account".
- The add flow: (provider chooser) → sign-in form → discovery → calendar selection → save → sync.
- The update-password flow (re-auth with the username pre-filled).
- The remove flow with confirmation, and full cleanup.
- Reconciling orphaned calendars (at startup and after a sync).
- Input normalisation for Apple IDs and app-specific passwords.
- A reusable `SignInFlow` component for the wizard (US-32).

### Out of scope
- Renaming, recolouring, and per-calendar visibility **after** setup (US-26 builds the Calendars section. The selection at sign-in time is here).
- Other providers' forms (US-20).
- The guide content (US-33).

---

## Acceptance criteria

1. **The Accounts section** lists every account: provider name ("iCloud"), the display name or Apple ID, and a status line: "Updated 14:05" / "Sign-in problem. Tap to fix" / "Not synced yet" (from US-18 if it's available). Plus an **Add account** button (≥ 88 px tall, full width). With no accounts: "No calendar accounts yet" plus the button.
2. **The sign-in form** (sub-page): the Apple ID field (OSK purpose `email`, done label "Next" moves to the password field), the app-specific password field (a `make_password_field` toggle, purpose `password`, done label "Sign in"), a **Sign in** button, a short explanation ("Use an app-specific password, not your Apple ID password.") and the guide link (if US-33 is there). The fields sit in the top ~540 px.
3. **Validation before the network**: the Apple ID must look like an email (`^[^@\s]+@[^@\s]+\.[^@\s]+$`). The password is normalised (D4) and must match `^[a-z]{4}-[a-z]{4}-[a-z]{4}-[a-z]{4}$` **or** be at least 8 characters (in case Apple changes the format: warn, but allow). Errors show inline.
4. **Signing in**: `BlockingOverlay` "Signing in to iCloud…" with Cancel. `icloud.discover` runs in `run_in_thread`. On success → the **calendar selection** page: each discovered calendar with its colour dot, name, and a large checkbox or switch (**all on by default**), plus a "Done" button.
5. **Errors** (inline on the form, the password text selected, and nothing saved):
   - `AUTH_FAILED` → "Apple didn't accept this Apple ID and app-specific password. Check both. App-specific passwords look like abcd-efgh-ijkl-mnop."
   - `NETWORK_DOWN`/`DNS_FAILED` → "calpi isn't connected to the internet. Check Wi-Fi in Settings → Network." (with a button that goes there)
   - `TIMEOUT`/`SERVER_ERROR`/`RATE_LIMITED` → "iCloud isn't responding right now. Try again in a few minutes."
   - `CLOCK_WRONG`/`TLS_ERROR` → "calpi's clock or security settings are wrong, so it can't connect securely. Make sure it's online so the clock can set itself, then try again."
   - no calendars found → "Signed in, but this account has no calendars."
   - anything else → "Couldn't sign in (<code>)."
   (US-38 will move these texts into the shared message catalogue. Keep them in one dict here: `SIGNIN_MESSAGES`.)
6. **Saving** (on "Done", on the main thread): `accounts.add_or_update_account(...)` (secret → credentials, record → settings), then for every discovered calendar `store.upsert_calendar(...)` with id `calendar_id_for(account.id, href)`, and `set_calendar_overrides(hidden=not selected)`. Then (first real account only) `store.delete_sample_data()`, then `app.sync.request_sync("account-added")`. The toast "iCloud account added". Back on the Accounts list, the new account appears.
7. **Adding an Apple ID that's already there** updates it: the same account id, the new password, a fresh discovery, and the existing calendar overrides are **kept** (upsert doesn't touch user columns, US-04).
8. **The account detail page** (tap an account): the provider, the Apple ID, the display name, the number of calendars (and how many are hidden), the last sync, and the last error (plain text, from US-18). Buttons: **Update password**, **Remove account** (destructive).
9. **Update password**: the sign-in form with the Apple ID pre-filled and **read-only** → the same discovery → on success, the new secret is stored, the calendar selection is **skipped** (the existing choices are kept, and new calendars are added as visible), then a sync.
10. **Remove account**: confirm "Remove <Apple ID>? Its calendars and events will be removed from calpi. Your iCloud data isn't affected." → on the main thread, in order: remove the record from settings → `credentials.delete(id)` → `store.delete_calendars_for_account(id)` (the events cascade) → `sync_status.forget_account` (if US-18) → `app.on_data_changed()` → the toast "Account removed". If a sync is running, reconcile again after it finishes (D5).
11. **Reconciliation**: at app startup, and after every sync result, any calendar whose `account_id` isn't `None`/sample and isn't in the settings account list is deleted (and logged at INFO).
12. **Secrets**: the password is wrapped in `Secret` as soon as it's read from the entry. The entry is cleared (`set_text("")`) as soon as the flow finishes or is cancelled. Nothing is logged except the account id and the error code.
13. `SignInFlow(ctx, on_finished)` works inside the wizard (`ctx.mode == "wizard"`): the same pages, no Settings-only links, and "Skip" handled by the wizard.

---

## Design decisions (already made)

- **D1. Provider chooser**: if only one provider is registered (no US-20), skip the chooser and go straight to the iCloud form. Otherwise show large provider buttons. Keep a `PROVIDER_FORMS = {"icloud": IcloudSignInForm, ...}` mapping.
- **D2. Where things run**: discovery (network) in `run_in_thread`. Everything that writes settings, credentials, or the store runs **on the main thread** in `on_done` (the US-05 convention). The store writes here are small (a handful of rows), so running them on the main thread is fine.
- **D3. The UI process writes to the event store** only in these rare cases: account add/remove (calendars), plus US-26's overrides. That's an **explicit, documented exception** to "the sync process writes events". It's safe thanks to `busy_timeout` and short transactions.
- **D4. Normalising the app-specific password**: strip whitespace (including inner spaces), and if what's left, lowercased, matches `^[a-z]{16}$` or `^[a-z]{4}(-?[a-z]{4}){3}$`, reformat it as `xxxx-xxxx-xxxx-xxxx` and **lowercase** it. Otherwise keep it as typed. (Apple generates lowercase letters with hyphens. Lowercasing catches accidental Shift. Reformatting catches missing hyphens.) Normalising the Apple ID: strip, and lowercase the domain part only.
- **D5. Reconciliation** (`accounts.reconcile_calendars(settings, store) -> int`, no gi): deletes the calendars of accounts that are no longer configured. It's called at startup (after the store opens) and in a `sync.result_callbacks` subscriber.
- **D6. Sample data** is removed when the first account is successfully added (`store.delete_sample_data()`), and it's never re-added automatically (`--sample-data` only loads into an empty store: US-04).
- **D7. Checkboxes**: use `SwitchRow`-style rows without a settings key (the value is kept in the page state), each with the calendar's colour dot (the CSS class from `CalendarColors` if it's available, or an inline class generated for the page).

---

## Implementation plan

### Step 1 — Pure helpers (`calpi/data/accounts.py`, no gi)
- `normalize_apple_id(s) -> str`, `normalize_app_password(s) -> str`, `validate_apple_id(s) -> str | None`, `validate_app_password(s) -> tuple[str | None, bool]` (error, warn_only).
- `remove_account(settings, credentials, store, account_id, forget_status=None) -> None`: the D10-ordered steps. Each step is in try/except with logging, so a failure part-way still leaves reconciliation able to finish the job.
- `reconcile_calendars(settings, store) -> int` (D5).
- `apply_calendar_selection(store, account_id, remotes: list[RemoteCalendar], selected_hrefs: set[str]) -> None`.

Tests: normalisation cases (`"ABCD EFGH IJKL MNOP"` → `abcd-efgh-ijkl-mnop`, `abcdefghijklmnop` → hyphenated, a random 20-character password is kept as it is), validation, removal order with fakes (and a failure injected at the credentials step → the rest continues), reconciliation (orphaned calendars removed, sample calendars kept, calendars of current accounts kept).

### Step 2 — `SignInFlow` (`calpi/widgets/settings/accounts.py`)
A small state machine of sub-pages pushed through `ctx.push_page`:
```
[ProviderChooser]? → SignInForm → (BlockingOverlay: discovering) → CalendarSelection → finish
                         ↑ errors come back here
```
```python
class SignInFlow:
    def __init__(self, ctx, *, on_finished, existing: Account | None = None):
        self.ctx, self.on_finished, self.existing = ctx, on_finished, existing
        self._cancelled = False
    def start(self): self.ctx.push_page(self._form(), "Add iCloud account" if not self.existing else "Update password")

    def _submit(self):
        user = normalize_apple_id(self.user_entry.get_text())
        pw = normalize_app_password(self.pw_entry.get_text())
        err = validate_apple_id(user) or validate_app_password(pw)[0]
        if err: self._show_error(err); return
        secret = Secret(pw)
        self._cancelled = False
        self.ctx.window.blocking.show("Signing in to iCloud…", on_cancel=self._cancel)
        run_in_thread(lambda: icloud.discover(user, secret),
                      on_done=lambda d: self._discovered(user, secret, d),
                      on_error=self._failed, name="signin")

    def _discovered(self, user, secret, disc):
        if self._cancelled: return
        self.ctx.window.blocking.hide()
        if not disc.calendars: self._show_error(SIGNIN_MESSAGES["no_calendars"]); return
        if self.existing: self._save(user, secret, disc, selected=None); return
        self.ctx.push_page(self._selection_page(user, secret, disc), "Choose calendars")

    def _save(self, user, secret, disc, selected: set[str] | None):
        app = self.ctx.app
        try:
            acc = accounts.add_or_update_account(app.settings, app.credentials, "icloud", user, secret, disc)
            accounts.apply_calendar_selection(app.store, acc.id, disc.calendars,
                                              selected if selected is not None else {c.href for c in disc.calendars})
            if len(accounts.list_accounts(app.settings)) == 1: app.store.delete_sample_data()
        except Exception:
            log.exception("saving account failed"); self._show_error("Couldn't save the account."); return
        finally:
            self._clear_entries()
        app.on_data_changed(); app.sync.request_sync("account-added"); app.toast("iCloud account added")
        self.on_finished(acc)
```
With `selected=None` for updates, **only newly discovered calendars** should be added as visible, and existing ones keep their `hidden` flag. Implement `apply_calendar_selection(..., selected=None)` to mean "upsert everything, don't touch the flags of existing rows, and leave new rows visible". Test it.

`_failed(e)`: hide the overlay. If it's a `SyncError`, show `SIGNIN_MESSAGES[e.code]` (fallback: "Couldn't sign in (<code>)"). For network errors, add a "Network settings" button that calls `navigator.show("settings", section="network")` (settings mode only). Select the password text.

`_cancel()`: set `_cancelled = True`, hide the overlay, stay on the form.

The form layout: `SettingsGroup` with the two fields, the error label, the Sign in button, the explanation text, and the guide link (a `ButtonRow`-style link, if the `icloud_guide` screen is registered with the navigator).

### Step 3 — The Accounts section
```python
class AccountsSection:
    def __init__(self, ctx):
        self.ctx = ctx
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.list_group = SettingsGroup("Accounts")
        self.add_btn = Gtk.Button(label="Add account", css_classes=["wide-button"])
        ...
        self._h = ctx.app.status_callbacks.add(lambda s: self._refresh()) if hasattr(ctx.app, "status_callbacks") else None
    def on_show(self): self._refresh()
    def _refresh(self): ...          # rebuild the list if the (id, name, status text) tuple changed
    def _open_detail(self, acc): self.ctx.push_page(self._detail_page(acc), acc.display_name)
    def _remove(self, acc):
        self.ctx.window.confirm.ask(f"Remove {acc.username}?", "...", "Remove", lambda: self._do_remove(acc), destructive=True)
    def _do_remove(self, acc):
        accounts.remove_account(app.settings, app.credentials, app.store, acc.id,
                                forget_status=(lambda: sync_status.forget_account(app.store.conn, acc.id)) if HAS_US18 else None)
        if app.sync.is_running: app.sync.after_current(lambda: accounts.reconcile_calendars(app.settings, app.store))
        app.on_data_changed(); app.toast("Account removed"); self.ctx.pop_page(); self._refresh()
```
`app.sync.after_current(cb)`: a small addition to `SyncEngine` that runs `cb` once, after the current run's result is handled. (Or simply rely on the reconciliation in `result_callbacks` from D5. **Prefer the general reconciliation subscriber**, and drop `after_current`.)

Status text per account (with US-18): `consecutive_failures > 0` and `last_error_code == AUTH_FAILED` → "Sign-in problem. Tap to fix". Other errors → "Last update failed". `last_success_at` → "Updated HH:MM" (or the date). Nothing → "Not synced yet".

### Step 4 — Startup reconciliation
In `CalpiApp._on_activate`, after the store and settings exist: `n = accounts.reconcile_calendars(self.settings, self.store)`. If `n`, log it. Register the `sync.result_callbacks` subscriber that runs it after each sync (cheap: one query).

### Step 5 — Tests
- Step 1's pure tests.
- The GTK flow with a **fake discover** (monkeypatch `icloud.discover` to return a fixture `Discovery` or raise `SyncError`): form → error on a bad email; form → `AUTH_FAILED` message; form → selection page → Done → settings has the account, the credentials have the secret, the store has the calendars with the right hidden flags, and the sample data is gone. The update flow keeps the flags. The remove flow cleans up everything.
- Entries cleared after finishing and cancelling.

### Step 6 — Pi check (with the owner)
1. If the account was added with the CLI earlier (US-14): **remove it through the new UI** first (this also tests removal). Check: `cli list-accounts` → none. `sqlite3 ... "select count(*) from calendars where account_id is not null"` → 0. `credentials.ids()` → empty.
2. **Add the account through the UI**: the owner types the Apple ID and app-specific password with the mouse/OSK. Select all but one calendar. Done → a sync starts ("Updating…") → events appear, and the unselected calendar's events don't.
3. A wrong password (the owner types an invalid one, **once**) → the AUTH message.
4. Update password: the owner generates a new app-specific password and uses Update password → still syncing. The owner can then revoke the old one at account.apple.com.
5. Take screenshots of the list, the form (with the OSK), the selection page, and the detail page. `CALPI_CHECK_TARGETS=1` (a temporary drop-in; remove it afterwards).
6. Ask the owner to check that the logs don't contain the password (`!` command with grep, as in US-23).

---

## Files

| File | Change |
|---|---|
| `calpi/data/accounts.py` | Normalise/validate, `remove_account`, `reconcile_calendars`, `apply_calendar_selection` |
| `calpi/widgets/settings/accounts.py` | New: `AccountsSection`, `SignInFlow`, the pages, `SIGNIN_MESSAGES` |
| `calpi/widgets/settings/__init__.py` | Imports `accounts` |
| `calpi/app.py` | Startup reconciliation, the reconcile subscriber |
| `calpi/style.css` | `.wide-button`, account rows |
| `tests/test_accounts.py` (extend), `tests/test_account_flow.py` | New cases |

---

## Pitfalls

- **Writing settings or credentials from the worker thread.** Only on the main thread (D2).
- **Keeping the password in the entry** after the flow. Clear it.
- **Leaving orphaned calendars** after a removal during a sync. Reconcile (D5).
- **Resetting the user's calendar choices on a password update.**
- **Hammering Apple with repeated wrong passwords** in tests.
- **Deleting the sample data when the add *failed*.** Only after a successful save.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] The full add → sync → update password → remove cycle done on the Pi with the owner.
- [ ] No password in the logs (the owner checked).
- [ ] The account is added through the UI and left in place for later stories.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `SignInFlow(ctx, on_finished, existing=None)` | US-32 (wizard), US-38 ("Fix" → update password) |
| The Accounts section id `"accounts"` (order 20); `navigator.show("settings", section="accounts")` | US-31, US-38 |
| `accounts.remove_account`, `reconcile_calendars`, `apply_calendar_selection` | US-20, US-26 |
| `SIGNIN_MESSAGES` (to be replaced by the US-38 catalogue) | US-38 |
| Hook point for the guide link (`navigator.get("icloud_guide")`) | US-33 |
