# US-18 — Sync status tracking

| | |
|---|---|
| **Epic** | 2. Calendar Syncing |
| **Priority** | P1 |
| **Blocked by** | US-16 Scheduled background sync |
| **Blocks** | US-31 Status screen, US-38 User-facing error handling |
| **Phase** | 2. Syncing (P1) |

## Story

> As a user, I want the app to record when each calendar last synced and why a sync failed, if it did.

## Context

US-16 produces a result after each run, but it only lives in memory (`engine.last_result`) and disappears at restart. To answer "when did my Family calendar last update?" or "why isn't my Work calendar updating?", the device needs a **persistent, per-account and per-calendar record** of the last attempt, the last success, the last error (as an `ErrorCode` + technical detail), and how many times in a row it has failed.

This story is **data only**: tables, the code that writes them (in the sync process), and read helpers (for the UI process). **Presenting** it is US-31 (the Status screen) and US-38 (plain-language messages with fixes). Keep this story strictly to recording and reading. Don't write user-facing text here.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-16** Scheduled background sync | The worker (`calpi/sync/worker.py`) with per-account and per-calendar results (`AccountResult`/`CalendarResult` from US-15), `engine.result_callbacks`, the result JSON v1 | `/usr/bin/python3 -m pytest tests/test_worker.py tests/test_sync_engine.py` passes. On the Pi, the journal shows `sync: ... changed=...` lines. |

(Through US-16 you also have US-04's `db.MIGRATIONS` and `write_txn`, which are needed for the new tables.)

### Soft dependencies
- **US-17**: `retry.classify`/`is_offline` are handy for summaries. Not required.
- **US-25** (later) removes accounts. Provide `forget_account(account_id)`, and note in US-25's hand-off that it has to be called.

### External blockers
None.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| The migration conflicts with another story's migration | `db.MIGRATIONS` is an append-only list. Add yours at the end. If someone else added v2 first, yours is v3. **Never edit an existing migration.** |
| Writing status in the same transaction as events | Don't combine them. Status is written **after** each calendar's event transaction, in its own small transaction. A failure to write status must not roll back good events. |

---

## Scope

### In scope
- DB migration: `account_sync_status`, `calendar_sync_status`, `sync_runs` tables.
- `calpi/data/sync_status.py` (no gi): write functions (used by the worker), read functions (used by the UI), and data classes.
- The worker writes the status for every account and calendar it touches, plus one `sync_runs` row per run.
- The engine: after a result, the UI refreshes a cached `StatusSnapshot` and notifies `status_callbacks`.
- A CLI `status` subcommand for developers.
- Sanitising the error details (no secrets, a length cap).

### Out of scope
- Any UI or plain-language text (US-31, US-38).
- History charts or analytics.

---

## Acceptance criteria

1. After each sync run, for **every account** it tried: `last_attempt_at` updated. On success (no account-level error) `last_success_at` updated, `consecutive_failures = 0`, and the error cleared. On an account-level error, `last_error_code`, `last_error_detail`, `last_error_at` set, and `consecutive_failures += 1`.
2. For **every calendar** it tried: the same fields, plus `last_event_count` and `last_duration_ms`, and `last_status` (`ok` / `unchanged` / `error`). An `unchanged` result counts as a **success** (it updates `last_success_at`: the data is confirmed current).
3. When the account-level request fails (for example `AUTH_FAILED` at the PROPFIND), every **existing** calendar of that account gets `last_attempt_at` updated and the account's error copied to it with `inherited = 1`, so the Status screen can show "not updated because the account failed".
4. `sync_runs`: one row per run (started, finished, reason, status, duration_ms, accounts_ok, accounts_failed, changed). Only the newest **100** rows are kept (older ones deleted in the same transaction).
5. Everything persists across restarts and power cuts (SQLite WAL, US-04).
6. `sync_status.snapshot(conn) -> StatusSnapshot` returns every account status, every calendar status (joined with the calendar name and hidden flag), and the last 20 runs, in **under 10 ms** on the Pi for 10 calendars.
7. `last_error_detail` is at most 300 characters, never contains the account secret (checked with the US-13 redactor, and tested), and never contains full response bodies.
8. Deleting a calendar deletes its status row (a foreign key with `ON DELETE CASCADE`). `forget_account(account_id)` deletes the account status row.
9. In the UI process: `app.sync_status` (a `StatusSnapshot`) is refreshed after every sync result and at startup. `app.status_callbacks` subscribers are called after each refresh.
10. The CLI: `python3 -m calpi.sync.cli status` prints a readable table of accounts, calendars, last success, and last error.
11. The status writes add no more than **2 small transactions per calendar per run**. With unchanged calendars, the whole run writes fewer than about 20 KB (check with the SD write measurement from US-12 if convenient).

---

## Design decisions (already made)

- **D1. Tables** (migration appended to `db.MIGRATIONS`):
  ```sql
  CREATE TABLE account_sync_status(
      account_id           TEXT PRIMARY KEY,
      last_attempt_at      INTEGER,          -- unix seconds UTC
      last_success_at      INTEGER,
      last_error_code      TEXT,             -- ErrorCode value or NULL
      last_error_detail    TEXT,
      last_error_at        INTEGER,
      consecutive_failures INTEGER NOT NULL DEFAULT 0
  );
  CREATE TABLE calendar_sync_status(
      calendar_id          TEXT PRIMARY KEY REFERENCES calendars(id) ON DELETE CASCADE,
      last_attempt_at      INTEGER,
      last_success_at      INTEGER,
      last_status          TEXT,             -- ok | unchanged | error
      last_error_code      TEXT,
      last_error_detail    TEXT,
      last_error_at        INTEGER,
      inherited            INTEGER NOT NULL DEFAULT 0,
      consecutive_failures INTEGER NOT NULL DEFAULT 0,
      last_event_count     INTEGER,
      last_duration_ms     INTEGER,
      last_parse_errors    INTEGER NOT NULL DEFAULT 0
  );
  CREATE TABLE sync_runs(
      id INTEGER PRIMARY KEY,
      started_at INTEGER NOT NULL, finished_at INTEGER NOT NULL,
      reason TEXT, status TEXT, duration_ms INTEGER,
      accounts_ok INTEGER, accounts_failed INTEGER, changed INTEGER
  );
  ```
- **D2. Times are Unix seconds UTC** (INTEGER), converted to local time in the UI only.
- **D3. The writer is the sync process only.** The UI process only reads (plus `forget_account` from US-25 when an account is removed: that's a rare write, and fine).
- **D4. Detail sanitising**: `sanitize_detail(text)` collapses whitespace, strips anything that looks like an `Authorization:` header, applies the secret redactor (US-13), and cuts to 300 characters.
- **D5. `StatusSnapshot`** is a frozen dataclass tree (`AccountStatus`, `CalendarStatus`, `RunRecord`), so UI code can't change it by accident.

---

## Implementation plan

### Step 1 — The migration
Append the D1 SQL to `db.MIGRATIONS` as the next version. Test the upgrade from the previous version: open a database built at the previous schema (build it with the old migration list in the test), then the new list → the tables exist, and the data is untouched.

### Step 2 — `calpi/data/sync_status.py`
```python
@dataclass(frozen=True)
class AccountStatus: account_id: str; last_attempt_at: datetime | None; last_success_at: datetime | None
                     last_error_code: str | None; last_error_detail: str | None; last_error_at: datetime | None
                     consecutive_failures: int
@dataclass(frozen=True)
class CalendarStatus: calendar_id: str; account_id: str | None; name: str; hidden: bool; ...  # all D1 columns
@dataclass(frozen=True)
class RunRecord: ...
@dataclass(frozen=True)
class StatusSnapshot:
    accounts: tuple[AccountStatus, ...]
    calendars: tuple[CalendarStatus, ...]
    runs: tuple[RunRecord, ...]
    def account(self, account_id) -> AccountStatus | None: ...
    def calendars_of(self, account_id) -> tuple[CalendarStatus, ...]: ...
    def last_run(self) -> RunRecord | None: ...

def record_account(conn, account_id, *, at, error=None, detail="") -> None: ...
def record_calendar(conn, calendar_id, *, at, status, error=None, detail="", events=None,
                    duration_ms=None, parse_errors=0, inherited=False) -> None: ...
def record_run(conn, *, started_at, finished_at, reason, status, duration_ms, ok, failed, changed, keep=100) -> None: ...
def snapshot(conn, runs=20) -> StatusSnapshot: ...
def forget_account(conn, account_id) -> None: ...
def sanitize_detail(text: str) -> str: ...
```
`record_*` use an UPSERT:
```sql
INSERT INTO calendar_sync_status(calendar_id, last_attempt_at, last_success_at, last_status, ...)
VALUES (?, ?, ?, ?, ...)
ON CONFLICT(calendar_id) DO UPDATE SET
  last_attempt_at = excluded.last_attempt_at,
  last_success_at = COALESCE(excluded.last_success_at, calendar_sync_status.last_success_at),
  last_status = excluded.last_status,
  last_error_code = excluded.last_error_code,
  ...
  consecutive_failures = CASE WHEN excluded.last_error_code IS NULL THEN 0
                              ELSE calendar_sync_status.consecutive_failures + 1 END
```
Watch out: on success the new row has `last_success_at = at`. On failure, pass `NULL` so `COALESCE` keeps the old value. `last_error_*` are **cleared** on success (set to NULL), and **set** on failure. Keep the last error detail visible for history? **Decision: clear on success.** The Status screen shows the current state, and `sync_runs` gives the history.

Each `record_*` call runs in its own `write_txn` (D3 of US-04). **Note**: `write_txn` increments the store `revision`, and that would make the UI think events changed (`changed=true`) after every run. **Fix**: give `write_txn` a parameter `bump_revision=True`, and pass `False` for status writes. Update US-04's `write_txn`, keep its tests passing, and add a test that status writes don't change `revision()`.

### Step 3 — Worker integration (`calpi/sync/worker.py`)
Right after each `sync_account(...)` returns:
```python
now = int(time.time())
if acc_result.error:
    sync_status.record_account(conn, acc.id, at=now, error=acc_result.error, detail=acc_result.detail)
    for cal in store.calendars_for_account(acc.id):
        sync_status.record_calendar(conn, cal.id, at=now, status="error", error=acc_result.error,
                                    detail=acc_result.detail, inherited=True)
else:
    sync_status.record_account(conn, acc.id, at=now)
    for cr in acc_result.calendars:
        sync_status.record_calendar(conn, cr.calendar_id, at=now, status=cr.status,
                                    error=cr.error, detail=cr.detail, events=cr.events,
                                    duration_ms=cr.duration_ms, parse_errors=cr.stats.parse_errors if cr.stats else 0)
```
For accounts with no readable credentials (the US-16 D5 path), record `CREDENTIALS_UNREADABLE` the same way. At the end of the run: `record_run(...)`. Use the store's own connection (`store.conn`), so there's one connection per process.

Wrap every status write in `try/except sqlite3.Error` → log a WARNING and carry on. **A status write failure must never fail the sync.**

### Step 4 — Reading in the UI process
In `CalpiApp`:
```python
self.sync_status = sync_status.snapshot(self.store.conn)
self.status_callbacks = []
self.sync.result_callbacks.append(lambda r: self._refresh_status())

def _refresh_status(self):
    self.sync_status = sync_status.snapshot(self.store.conn)
    for cb in list(self.status_callbacks):
        try: cb(self.sync_status)
        except Exception: log.exception("status callback failed")
```
Reading on the main thread is fine: a few small indexed tables, well under 10 ms (acceptance criterion 6). Measure it once on the Pi and log it at DEBUG.

### Step 5 — CLI `status`
```
$ python3 -m calpi.sync.cli status
ACCOUNT icloud-1a2b3c4d  me@icloud.com   last ok 2026-09-25 14:05  failures 0
  Family        ok         213 events   last ok 14:05   (2.3 s)
  Work          unchanged   88 events   last ok 14:05
  Shared        error      TIMEOUT      last ok 2026-09-24 22:15   failures 3   "read timed out"
Last runs: 14:05 interval done 7.0 s | 13:50 interval done 1.2 s | ...
```
Show local times, using the display zone from settings.

### Step 6 — Tests (`tests/test_sync_status.py`, extend `tests/test_worker.py`)
- A success after a failure resets `consecutive_failures`, clears the error, and moves `last_success_at` on.
- Three failures → `consecutive_failures == 3`, `last_success_at` unchanged from the earlier success.
- `unchanged` counts as success.
- An account-level failure → every calendar row is `inherited`, with the account's code.
- `sync_runs` pruned to 100 (insert 120 and check).
- Cascade: delete the calendar → its status row is gone. `forget_account` works.
- `sanitize_detail`: redaction of a registered secret, the `Authorization: Basic ...` pattern, and the length cap.
- Status writes don't bump `revision()`.
- Worker integration: run the worker with a fake transport returning 503 for one calendar → the rows are as expected. Then a successful run → reset.
- `snapshot()` timing with 20 calendars and 100 runs < 10 ms in the devcontainer (assert < 50 ms to allow for CI variance).

### Step 7 — Pi check
Deploy. Let 2–3 syncs run. `scripts/pi ssh 'cd /opt/calpi && sudo -u kiosk env STATE_DIRECTORY=/var/lib/calpi /usr/bin/python3 -m calpi.sync.cli status'`. Then cause a failure (the offline method from US-17 step 7, or temporarily rename the account's credential id in a **copy** of the state directory. **Don't damage the real one.**) Check that the error is recorded and then cleared again after recovery.

---

## Files

| File | Change |
|---|---|
| `calpi/data/db.py` | Migration, `write_txn(bump_revision=...)` |
| `calpi/data/sync_status.py` | New |
| `calpi/sync/worker.py` | Writes the status |
| `calpi/sync/cli.py` | `status` subcommand |
| `calpi/app.py` | `sync_status`, `status_callbacks`, refresh |
| `tests/test_sync_status.py` | New, plus worker test additions |

---

## Pitfalls

- **Bumping the revision with status writes.** The UI would reload the grid after every sync for nothing, and US-16's `changed` flag would always be true.
- **Status writes inside the event transaction.**
- **Clearing `last_success_at` on failure.** Use `COALESCE`.
- **Raw server bodies in `last_error_detail`.** Only short technical summaries.
- **Writing user-facing text here.** That's US-38.

---

## Definition of done

- [ ] All acceptance criteria met. The tests pass, including the migration upgrade test.
- [ ] Recorded and recovered a real failure on the Pi (CLI output in the hand-off notes).

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `app.sync_status` (`StatusSnapshot`), `app.status_callbacks` | US-31, US-38, US-25 (per-account status in Settings) |
| `StatusSnapshot.account(id)`, `.calendars_of(id)`, `.last_run()` | US-31, US-38 |
| `sync_status.forget_account(conn, account_id)` | US-25 (on removal) |
| Error codes stored as `ErrorCode` values, with sanitised details | US-38 maps codes to messages |
| `db.write_txn(bump_revision=False)` for bookkeeping writes | anyone adding non-event tables |
