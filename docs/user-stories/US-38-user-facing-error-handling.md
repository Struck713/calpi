# US-38 — User-facing error handling

| | |
|---|---|
| **Epic** | 4. Touch and Polish |
| **Priority** | P1 |
| **Blocked by** | US-18 Sync status tracking |
| **Blocks** | — |
| **Phase** | 4. Touch and Polish |

## Story

> As a user, I want problems such as a wrong password, no network or an expired account to show as clear messages with a suggested fix.

## Context

By now the app detects plenty of problems: `ErrorCode`s from sync (US-14/15), per-account and per-calendar status with consecutive failures (US-18), offline state (US-17), startup notices (US-12/13: the database was reset, credentials are unreadable, safe mode), clock trust (US-17), power and temperature (US-31). But the **wording** is spread around (`SIGNIN_MESSAGES` in US-25, `manual_result_text` in US-19, Wi-Fi messages in US-23, the minimal `messages.py` from US-31), and there's no consistent rule for **where** and **when** a problem is shown.

This story makes error handling consistent across the app:
1. **One message catalogue** (`calpi/data/messages.py`): for every problem code, a title, a plain-language explanation, a **suggested fix**, and a **fix action** (which Settings section a "Fix" button opens), in versions for each place a message can appear.
2. **Clear rules for where problems appear**:
   - the **calendar header** (the sync indicator gets an `error` state for problems the owner needs to act on, and tapping it opens Status),
   - **one banner** under the header for problems that need attention (for example "iCloud needs you to sign in again", with a **Fix** button). It can be dismissed until the problem changes,
   - **inline messages in forms** (sign-in, Wi-Fi),
   - **toasts** for the results of actions,
   - the **Status screen** (US-31) for everything, in detail.
3. **When to stay quiet**: short outages don't raise alarms (US-17's quiet retries), nothing appears during the setup wizard, and the calendar itself is never covered by a dialog.
4. **Telling situations apart**: "wrong password" when signing in versus "iCloud **stopped** accepting a password that used to work" (revoked or expired, typically after the Apple ID password changes). The fix is the same, the explanation isn't.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-18** Sync status tracking | `app.sync_status` (per-account `consecutive_failures`, `last_success_at`, `last_error_code`), `app.status_callbacks` | `python3 -m calpi.sync.cli status` on the Pi shows the accounts. `grep -n "consecutive_failures" calpi/data/sync_status.py` |

(Through US-18 → US-16 → US-15/US-14 you also have `ErrorCode`, the engine's result callbacks, and the sync indicator.)

### Soft dependencies (each one adds a place to integrate with; work with what exists)

| Soft blocker | Integration |
|---|---|
| **US-31** Status screen, `status_summary.summarize`, the minimal `messages.py` | Take over and extend `messages.py`. The header and banner use the same verdict logic. |
| **US-25** `SIGNIN_MESSAGES` | Replace it with catalogue lookups (`context="form"`). |
| **US-23** Wi-Fi inline messages | Replace them with catalogue lookups. |
| **US-19** `manual_result_text` | Replace it with the catalogue (`context="toast"`). |
| **US-17** `sync_text.compute_state`, `SyncIndicator` | Add the `error` state. |
| **US-12/13** `app.startup_notices`, `app.safe_mode` | The banner shows them. |
| **US-22** overlays, `navigator.show("settings", section=...)` | Fix buttons, toasts. |
| **US-32** wizard | Suppress the banner and header errors while the wizard is showing. |

If a soft dependency isn't done, **don't** build its part here. Leave the catalogue entries ready and list the integration as pending.

### External blockers
- **Review of the wording with the owner**: the texts are the product here. Generate a review sheet (step 6) and have the owner read it.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| Strings are hard-coded in many widgets | Search for them (`grep -rn '"Couldn' calpi/widgets`, and quote marks in `set_text(` calls for error text) and move each one into the catalogue. Labels and headings can stay in the widgets. **Problem explanations can't.** |
| Too many banners at once | There's **one** banner slot. Show the highest-priority problem (the same priority as US-31's verdict), and the Status screen lists the rest. |

---

## Scope

### In scope
- `calpi/data/messages.py`: the full catalogue (it's the owner of the interface US-31 defined). Contexts `header`, `banner`, `form`, `toast`, `status`. Provider name substitution.
- Classifying "expired/revoked" versus "wrong password" (`AUTH_FAILED` with a previous success → `AUTH_REVOKED`).
- `calpi/widgets/problem_banner.py`: the one-slot banner under the calendar header, with a Fix button and Dismiss.
- The sync indicator's `error` state.
- Replacing the scattered texts (US-19/23/25/31).
- The display rules (D3): grace periods, suppression, dismissal.
- Tests: catalogue completeness, length limits, no jargon, rules.
- A wording review sheet for the owner.

### Out of scope
- New detection logic beyond `AUTH_REVOKED` (the other detection belongs to its own stories).
- Translation.
- Push notifications or remote alerts (out of scope project-wide).

---

## Acceptance criteria

1. **The catalogue** covers every `ErrorCode`, plus `AUTH_REVOKED`, `CLOCK_UNSYNCED`, `NO_ACCOUNTS`, `SAFE_MODE`, `DB_RESET`, `CREDENTIALS_UNREADABLE`, `POWER_UNDERVOLTAGE`, `POWER_THROTTLED_PAST`, `TEMP_HIGH`, `DISK_LOW`, `WIFI_WRONG_PASSWORD`, `WIFI_NOT_REACHABLE`, `WIFI_UNSUPPORTED`, `WIFI_FAILED`, `OFFLINE`. Each code has: `severity` (`info`/`warning`/`error`), a `title` per context, a `detail` (a plain sentence), an optional `fix_label` + `fix_target` (a settings section id or a special action such as `"update_password"`). A test checks every code has every context it needs.
2. **Length limits**: `header` ≤ 32 characters, `banner` title ≤ 60 and detail ≤ 160, `toast` ≤ 60 (tested). No technical jargon in any user text: a test checks for the words `HTTP`, `PROPFIND`, `DNS`, `TLS`, `SSL`, `401`, `403`, `500`, `exception`, `errno`, `NetworkManager`, `CalDAV` (allowed only in the `status` context's small "technical details" line).
3. **Wrong password vs revoked**: when signing in (US-25), a 401 → `AUTH_FAILED` ("Apple didn't accept this Apple ID and app-specific password…"). For a **saved account that synced successfully before**, a 401 → shown as `AUTH_REVOKED`: "iCloud stopped accepting calpi's password. This happens when you change your Apple ID password or revoke the app-specific password. Create a new app-specific password and enter it here." Fix: **Update password** (opens US-25's update flow for that account).
4. **The header**: the sync indicator shows the `error` state (red text) with the header message when there's an **actionable** problem (severity `error`: auth failed or revoked, credentials unreadable, safe mode, power under-voltage now, clock wrong while offline for more than 15 minutes). Tapping it opens Settings → Status (US-31).
5. **The banner** (under the calendar header, one slot): shows the highest-priority active problem of severity `warning` or `error`, **after its grace period** (D3), with the title, the detail, and a **Fix** button (if there's a fix target) plus a **Dismiss** (✕, ≥ 72 px). Dismissing hides it until the problem's **signature** changes (for example a different code or account) or 24 hours pass. It never covers the grid: the grid shrinks by the banner's height. **Decision: overlay the banner on the top week row's upper area**? **No**: to keep the fixed layout (US-06 D1), the banner **replaces the weekday-name row** while it's visible (the same 48 px), with its detail on one line, ellipsized. Tapping the banner text opens Status for the full explanation.
6. **Forms**: US-25's sign-in and US-23's Wi-Fi messages come from the catalogue (`context="form"`). The behaviour is unchanged.
7. **Toasts**: US-19's manual refresh result comes from the catalogue (`context="toast"`).
8. **Status screen** (US-31): every problem line uses `context="status"` (title + detail + fix), plus a small technical line (`code`, and a short detail from US-18's `last_error_detail`).
9. **Quiet rules** (D3): transient network problems never show a banner before **30 minutes** of continuous failure (the header's subtle "Offline" from US-17 covers them). Nothing is shown in the header or banner while the setup wizard is on screen. **No** modal dialogs about background problems, ever.
10. **Startup notices**: `DB_RESET` → an info banner "Calendar data was reset after a problem and is downloading again" (it disappears by itself after the next successful sync). `CREDENTIALS_UNREADABLE` → an error banner "calpi can't read its saved sign-in details (the memory card may have moved to another device). Sign in again." with Fix → Accounts.
11. **Provider names**: messages say "iCloud", or the provider's display name for other providers (US-20), never a hard-coded "iCloud" for a CalDAV account.
12. **The review sheet**: `python3 -m calpi.data.messages --review > scratch-messages.md` prints every message in every context. The owner has reviewed it, and the changes are applied.

---

## Design decisions (already made)

- **D1. Catalogue structure** (`messages.py`, no gi):
  ```python
  @dataclass(frozen=True)
  class Entry:
      severity: str                          # info | warning | error
      header: str | None                     # short, for the header indicator
      banner_title: str | None
      detail: str                            # plain sentence; may use {provider}, {account}, {ssid}
      form: str | None                       # inline form message
      toast: str | None
      fix_label: str | None = None
      fix_target: str | None = None          # "accounts" | "network" | "status" | "update_password" | ...
      grace_s: int = 0                       # D3
  CATALOGUE: dict[str, Entry] = {...}
  def describe(code, *, context, provider="iCloud", account="", ssid="") -> Message: ...
  ```
  `Message(title, detail, fix_label, fix_target, severity)` is the D2 interface from US-31. Keep it compatible.
- **D2. Deriving `AUTH_REVOKED`**: `classify_account_problem(account_status) -> code`: if `last_error_code == "AUTH_FAILED"` **and** `last_success_at` is not None → `AUTH_REVOKED`, else the stored code. It's pure and lives in `messages.py` or `status_summary.py`.
- **D3. Display rules** (`calpi/data/problem_rules.py`, pure):
  - Collect the active problems from: the account statuses (US-18), `app.startup_notices`, `app.safe_mode`, the device info (US-31), clock trust + offline (US-17).
  - Each problem has a `since` time. It's shown in the banner only if `now - since ≥ entry.grace_s`. Grace: `OFFLINE`/`NETWORK_DOWN`/`DNS_FAILED`/`TIMEOUT` = 1800 s; `SERVER_ERROR`/`RATE_LIMITED` = 3600 s; `AUTH_*`, `CREDENTIALS_UNREADABLE`, `SAFE_MODE`, `POWER_UNDERVOLTAGE` = 0; `CLOCK_UNSYNCED` = 900 s; `DB_RESET` = 0 (info).
  - The priority is the same order as US-31's verdict (D1 there). **Reuse `status_summary`'s order list**, don't copy it.
  - The signature for dismissal = `(code, account_id or "")`. Dismissals are stored in memory plus the settings key `K_DISMISSED_PROBLEMS` (`{signature: dismissed_at}`), pruned after 24 h.
  - Suppressed while `navigator.current == "wizard"`.
- **D4. The banner replaces the weekday row** while it's visible (acceptance criterion 5). It keeps the grid's geometry, and the weekday names come back when the banner is dismissed or the problem goes away. The weekday names matter less than a problem that needs fixing, and the day cells still show the dates.

---

## Implementation plan

### Step 1 — The catalogue
Write `CATALOGUE` for every code in acceptance criterion 1. Wording guidelines (put them in the module docstring):
- Say **what** is wrong in everyday words, **what the device is still doing** ("Showing events from 14:05"), and **what to do**.
- Use no blame and no exclamation marks. Keep it short. Use `{provider}`.
- Examples:
  - `NETWORK_DOWN`: header "Offline", banner "calpi is offline", detail "It can't reach the internet, so it's showing the events it saved at {last_update}. It'll update by itself when the connection is back.", fix "Network settings" → `network`.
  - `AUTH_REVOKED`: header "Sign-in problem", banner "{provider} needs you to sign in again", detail "{provider} stopped accepting calpi's password for {account}. This happens when you change your Apple ID password or revoke the app-specific password. Create a new app-specific password and enter it.", fix "Update password" → `update_password`.
  - `POWER_UNDERVOLTAGE`: header "Power problem", banner "The power supply is too weak", detail "This can make calpi slow or unreliable. Use the official Raspberry Pi power supply (5.1 V, 2.5 A).", no fix.
  - `CLOCK_WRONG`: banner "calpi's clock is wrong", detail "It can't connect securely until the clock is set. Make sure it's connected to the internet. The clock sets itself.", fix → `network`.
- `{last_update}` comes from the caller (`formatting.relative_datetime`, US-27).

The `--review` CLI: prints a Markdown table per code with every context filled in with sample values.

### Step 2 — Rules (`problem_rules.py`)
```python
@dataclass(frozen=True)
class Problem: code: str; since: datetime; account_id: str | None = None
def collect(inputs: StatusInputs, now) -> list[Problem]: ...           # reuse US-31's StatusInputs
def visible_banner(problems, now, dismissed, in_wizard) -> Problem | None: ...
def header_problem(problems, now, in_wizard) -> Problem | None: ...     # severity error only
```
`since` for account problems: the first failure time. US-18 has `last_error_at` and `consecutive_failures`. The start of the failing streak isn't stored. Add `failing_since` to `account_sync_status` (a small migration: set it when `consecutive_failures` goes 0 → 1, clear it on success). **This is a small change to US-18's tables, owned by this story.** Update `record_account` and its tests.

### Step 3 — The banner widget (`calpi/widgets/problem_banner.py`)
```
ProblemBanner (Gtk.Box horizontal, css "problem-banner <severity>", height = weekday row)
├─ Label title (bold) + " · " + Label detail (ellipsize END)    ← tap opens Status
├─ [Fix label] button (≥ 160×72)
└─ [✕] button (72×72)
```
`MonthView` swaps the weekday row and the banner (`set_visible` on both: the same slot, and no layout change for the grid). Refresh on `app.status_callbacks`, network or clock-trust changes, `startup_notices` changes, and every minute (the grace periods pass with time).

Fix actions: a section target → `navigator.show("settings", section=...)`. `update_password` → `navigator.show("settings", section="accounts")`, then open the account detail and start `SignInFlow(existing=account)` (add a `open_update_password(account_id)` entry point in US-25's section).

### Step 4 — The header error state
Extend `sync_text.compute_state` (US-17) with an `error` input (the `header_problem` result). `error` has the highest priority after `running`. Its text comes from `describe(code, context="header")`. The indicator is already clickable → Status (US-31).

### Step 5 — Replace the scattered texts
- US-25: `SIGNIN_MESSAGES[code]` → `describe(code, context="form", provider=...)`.
- US-23: the Wi-Fi reason codes → `describe("WIFI_WRONG_PASSWORD", context="form", ssid=...)` and so on.
- US-19: `manual_result_text(result)` → the most relevant code from the result → `describe(code, context="toast")`.
- US-31: already uses `describe`. Make sure it uses `classify_account_problem` for `AUTH_REVOKED`.
Delete the old dicts and functions. Keep the tests green (update the expected strings).

### Step 6 — Tests and the review
- `tests/test_messages.py`: completeness (every code × required contexts), length limits, the jargon list, placeholder substitution (no leftover `{...}`), and `classify_account_problem`.
- `tests/test_problem_rules.py`: grace periods (offline for 29 minutes → no banner, 31 minutes → banner), priority (auth over offline), dismissal by signature and its 24-hour expiry, wizard suppression, `DB_RESET` clearing after success.
- The US-18 migration test for `failing_since`.
- `python3 -m calpi.data.messages --review > scratch-messages.md`. Send the owner the content (it's plain text, safe to share) and apply their edits.

### Step 7 — Pi check (simulate problems safely)
- **Revoked password**: the owner revokes the current app-specific password at account.apple.com (then creates a new one for the fix) → within one sync: the header shows "Sign-in problem", the banner shows "iCloud needs you to sign in again" → Fix → Update password → the owner enters the new password → the banner disappears after the next sync. Screenshots.
- **Offline for more than 30 minutes** (US-17 method with a scheduled restore): at 5 minutes, only "Offline" in the header. At 31 minutes, the banner. When it comes back, everything clears.
- **Credentials unreadable**: simulate on a **copy** of the state (not the real one): run the app with `--state-dir` on a copy whose `keys/credentials.key` has been replaced → the error banner with Fix → Accounts. Don't touch the real key.
- **Dismiss**: dismiss the offline banner → it stays away while the same problem continues.

---

## Files

| File | Change |
|---|---|
| `calpi/data/messages.py` | The full catalogue + `--review` |
| `calpi/data/problem_rules.py` | New |
| `calpi/data/sync_status.py` + migration | `failing_since` |
| `calpi/data/settings_store.py` | `K_DISMISSED_PROBLEMS` |
| `calpi/widgets/problem_banner.py` | New |
| `calpi/widgets/month_view.py` | Banner/weekday-row slot |
| `calpi/data/sync_text.py`, `widgets/sync_indicator.py` | Error state |
| `calpi/widgets/settings/accounts.py`, `network.py`, `status.py`, `refresh_button.py` / `sync_text.py` | Use the catalogue |
| `tests/test_messages.py`, `tests/test_problem_rules.py` | New |

---

## Pitfalls

- **Alarming users over blips.** Respect the grace periods.
- **Several banners or dialogs.** One slot, highest priority first.
- **Hard-coded "iCloud"** for other providers.
- **Jargon in the main text.**
- **Changing the grid's geometry** for the banner (D4).
- **Dismissal that hides a new, different problem.** Use signatures.
- **Touching the real credential key** to test. Use a copy.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] The owner reviewed the wording, and the edits are applied.
- [ ] Revoked-password and long-offline scenarios checked on the Pi, with screenshots.
- [ ] The old scattered message dicts and functions removed.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `messages.describe(code, context=..., provider=..., **vars)` (the single source of user-facing problem text) | every future feature (US-20, US-41 weather errors, ...) |
| `problem_rules.collect/visible_banner/header_problem` | US-31 (consistency), US-41 |
| New problems = a new catalogue entry + a producer. Never inline strings | all stories |
