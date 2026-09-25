# US-15 — Event fetching and parsing

| | |
|---|---|
| **Epic** | 2. Calendar Syncing |
| **Priority** | P0 |
| **Blocked by** | US-04 Local event store, US-14 iCloud account connection |
| **Blocks** | US-16 Scheduled background sync, US-20 Additional providers |
| **Phase** | 2. Syncing |

## Story

> As a user, I want events for the visible date range downloaded and understood correctly, including recurring events, exceptions and time zones.

## Context

This is where real calendar data enters calpi. For each calendar of an account, it:
1. asks the server for every event that overlaps a **date window** (a CalDAV `REPORT calendar-query` with a `time-range`),
2. parses the iCalendar data (RFC 5545) and **expands recurrences** into individual occurrences within the window (RRULE, RDATE, EXDATE, and overridden instances marked with RECURRENCE-ID, including moved and cancelled ones),
3. converts every occurrence into the store's representation (US-04: aware UTC for timed events, floating dates for all-day ones),
4. atomically replaces that calendar's occurrences in the event store.

Getting recurrence and time zones right is **the** correctness risk of the whole project: a weekly 09:00 meeting must stay at 09:00 local time across DST, an all-day birthday must never shift by a day, and a single moved or cancelled instance must show correctly. **Don't write recurrence expansion yourself.** Use `icalendar` and `recurring-ical-events`, which exist for exactly this and are well tested. Our job is to feed them correctly, map their output correctly, and **prove it with fixtures**.

This runs in the **sync process** (US-16), never in the UI process. That's why the heavy libraries are fine here. Until US-16 exists, it's driven by the developer CLI (`calpi.sync.cli fetch`).

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-04** Local event store | `Event`/`Calendar` models (with validation), `EventStore.upsert_calendar`, `replace_calendar_events`, `delete_calendar`, `db.write_txn`, `db.MIGRATIONS`, `calendars.ctag/sync_token/window_start/window_end` columns | `/usr/bin/python3 -m pytest tests/test_event_store.py` passes. `sqlite3 <db> ".schema calendars"` shows `ctag`, `window_start` |
| **US-14** iCloud account connection | `HttpClient`, `caldav.NS`/`parse_multistatus`, `icloud.discover`, `Account`/`RemoteCalendar`, `SyncError`/`ErrorCode`, `accounts.list_accounts`, the CLI, **a real account saved on the Pi** | `/usr/bin/python3 -m pytest tests/test_icloud.py` passes. `scripts/pi ssh 'cd /opt/calpi && sudo -u kiosk env STATE_DIRECTORY=/var/lib/calpi /usr/bin/python3 -m calpi.sync.cli list-accounts'` shows the owner's account. |

### Soft dependencies
- **US-05**: the window size keys (`K_SYNC_WINDOW_BACK/FORWARD`) are registered in settings. The sync reads them (the default is -2/+12 months).
- **US-06**: `timeutil.display_tz()` decides how floating times are read and where the window boundaries are. It's already in place, because US-07 → US-06.
- **US-07**: to **see** the result on screen. Not required for the tests.

### External blockers

| Blocker | What to do |
|---|---|
| **`python3-icalendar` and `python3-recurring-ical-events` on the Pi's OS release** (plus their dependencies `python3-dateutil`, `python3-x-wr-timezone`) | Check: `ssh calpi 'apt-cache policy python3-icalendar python3-recurring-ical-events python3-x-wr-timezone'`, and the same in the devcontainer. Need icalendar ≥ 5 and recurring-ical-events ≥ 2. **If they're missing or too old, use the vendoring fallback in D2.** Record the versions in `docs/platform-versions.md`. |
| **The owner's real calendars** should contain the tricky cases for the final check | Ask the owner to create, in a test calendar: a weekly event with one instance moved and one deleted; an all-day multi-day event; an event in another time zone; a daily event with no end. Or accept that the real-data check covers only what they have, and rely on the fixtures. |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| `recurring_ical_events` gives occurrences without `RECURRENCE-ID` | Behaviour depends on the version. Compute the occurrence identity yourself (D5) and test it against the installed version. |
| Timezone objects come back as `pytz` instead of `zoneinfo` | icalendar < 6 uses pytz. Normalise: `dt.astimezone(timezone.utc)` works for both. **Never** call `.replace(tzinfo=...)` on pytz-aware values. |
| Windows time zone names (`W. Europe Standard Time`) with no VTIMEZONE | Rare from iCloud, common from Exchange invitations. Recent icalendar versions map Windows names. If one can't be resolved, treat the time as floating in the display zone, log DEBUG, and count it in the stats. |
| iCloud returns huge responses for calendars with years of history | The time-range filter limits it to resources that have an instance in the window, but a long-running recurring series is still sent once. That's fine: our 20 MB cap (US-14) should never be reached. If it is, report it. |
| Parsing is slow on the Pi | It's in the sync process, so it doesn't affect the UI. Measure (acceptance criterion 9). Only optimise if the full sync takes more than 60 s. |

---

## Scope

### In scope
- `calpi/sync/ical_parse.py`: iCalendar bytes → `list[Event]` for a window, plus parse statistics.
- `calpi/sync/fetch.py`: `sync_account(...)`, which does the calendar-list refresh (1 PROPFIND), a ctag check per calendar, the REPORT, parsing, and the store writes. It also removes calendars deleted on the server.
- The window calculation (default plus the requested extra range).
- The calendar id scheme (`<account_id>:<sha1(href)[:16]>`).
- Small additions to `EventStore`: `set_sync_state(calendar_id, ctag, sync_token, window)`, `calendars_for_account(account_id)`.
- Settings keys for the window size.
- CLI: `python3 -m calpi.sync.cli fetch --account ID [--dry-run] [--from YYYY-MM --to YYYY-MM]`.
- **A large fixture suite** for parsing.

### Out of scope
- Scheduling, the process wrapper, and UI refresh (US-16); retry and backoff (US-17); recording status per calendar (US-18, although `sync_account` **returns** per-calendar results that US-18 stores); incremental `sync-collection` (RFC 6578: a possible later optimisation. The ctag check is enough for now).

---

## Acceptance criteria

1. `sync_account(account, secret, store, window, force=False) -> AccountResult` refreshes the calendar list with one `PROPFIND Depth:1` on the stored `calendar_home_url` (falling back to full `discover()` on a 404 or a redirect to a different home). It then upserts every event calendar into the store (id per D4), and **deletes store calendars of this account that no longer exist on the server**, but only after a successful PROPFIND.
2. For each calendar: if the server `ctag` equals the stored `ctag` **and** the stored window covers the requested window, it's **skipped** (`status="unchanged"`, no REPORT). Otherwise it's fetched with a `REPORT calendar-query` (`Depth: 1`, VEVENT `time-range` = the window in UTC), parsed, and written with `replace_calendar_events` + `set_sync_state` in **one transaction**. `force=True` ignores the ctag.
3. **Correctness**: every fixture case in step 7 produces exactly the expected occurrences (summary, all-day flag, start and end, recurrence id, status), checked by exact comparison in tests.
4. Cancelled events (`STATUS:CANCELLED`, on a single event or on an overridden instance) produce **no** occurrence. EXDATE removes instances. RDATE adds them. An overridden instance (RECURRENCE-ID) replaces the generated one, **even if it was moved into the window from outside it, or out of the window**.
5. Time zones: a TZID with a known zone → correct UTC. A custom VTIMEZONE block → used. Floating times (no TZID, no `Z`) → interpreted in the **display time zone**. An unknown TZID → treated as floating, counted in `stats.unknown_tz`.
6. All-day: `DTSTART;VALUE=DATE` gives `all_day=True` with dates and an exclusive end. A missing DTEND → 1 day. An all-day event with DTEND ≤ DTSTART → 1 day (and a DEBUG line logged).
7. A timed event with DURATION → end = start + duration. No DTEND and no DURATION → a zero-length event.
8. **Robustness**: a resource that fails to parse is skipped (counted in `stats.parse_errors`, the UID logged at WARNING when it can be found), and the rest of the calendar is still stored. If **every** resource fails, the calendar result is `PARSE_ERROR`, and the store is **not** changed for that calendar. Occurrences are capped at **5,000 per calendar per window**, with a WARNING when the cap is hit.
9. **Performance on the Pi 3B**: a full sync of the owner's real account (with `force=True`) finishes in under **60 s** and uses under **150 MB** peak RSS (`/usr/bin/time -v` → "Maximum resident set size"). An unchanged sync (every ctag the same) takes under **5 s**.
10. The window: `compute_window(today, tz, back=2, forward=12, extra=None)` returns `[first day of (month - back), first day of (month + forward + 1))` as local midnights in the display zone, converted to UTC, and extended to include the `extra` date range if one is given. Tested.
11. On the Pi, after `cli fetch --account <id>`, the grid (US-07) shows the owner's real events. They match the Apple Calendar app for the current and next month (the owner checks, **including the recurring and all-day events**).
12. `AccountResult` contains, per calendar: `calendar_id`, `name`, `status` (`ok`/`unchanged`/`error`), `events` (the count), `error` (an `ErrorCode` or None), `detail`, `duration_ms`, and `stats`. There's also an account-level `error` (for example `AUTH_FAILED` at the PROPFIND, where every calendar is untouched).

---

## Design decisions (already made)

- **D1. Libraries**: `icalendar` (parsing) + `recurring_ical_events` (expansion), from apt. They're imported **only** in `calpi/sync/ical_parse.py`, which is never imported by UI modules. (Check: `test_ui_imports.py` imports `calpi.app` in a subprocess, with `gi` stubbed or with Broadway, and asserts that `icalendar` isn't in `sys.modules`. At minimum, `grep -rn "ical_parse\|icalendar" calpi/widgets calpi/app.py` must find nothing.)
- **D2. The fallback if apt doesn't have them or they're too old**: vendor the **pure-Python** packages `recurring_ical_events` (and `x_wr_timezone`, if needed) into `calpi/_vendor/`, with their LICENSE files and a `calpi/_vendor/README.md` recording the version and source URL. `icalendar` itself is also pure Python and can be vendored the same way. Use a small import shim in `ical_parse.py`: try the system package first, then `calpi._vendor`. **Don't** use a venv on the Pi (US-03's deploy layout doesn't support one).
- **D3. The window** is computed in the display zone from `timeutil.today()` in the **sync process** (it reads the time zone setting from `settings.json` and calls `timeutil.set_display_tz`). Settings keys `K_SYNC_WINDOW_BACK = "sync_window_months_back"` (default 2, range 0–12) and `K_SYNC_WINDOW_FORWARD = "sync_window_months_forward"` (default 12, range 1–36). An `extra` range comes from the UI's visible range when the user browses outside the window (US-16 passes it).
- **D4. The calendar id** = `f"{account.id}:{hashlib.sha1(href.encode()).hexdigest()[:16]}"`, with `href` normalised to an absolute URL with a trailing slash. It's stable across syncs, so the user's overrides (US-26) survive.
- **D5. Occurrence identity** (`Event.recurrence_id`):
  - the component has `RECURRENCE-ID` → the ISO text of its UTC value (or the date for all-day),
  - otherwise, if the master component has `RRULE` or `RDATE` → the ISO text of the occurrence's **start** (in UTC, or the date),
  - otherwise `""`.
  Duplicates are handled by the store (the last one wins, US-04).
- **D6. Mapping an occurrence to an `Event`**:
  - `start = DTSTART`. If it's a `date` (not a `datetime`) → all-day. If it's a naive `datetime` → floating → `.replace(tzinfo=display_tz)`. If it's aware → `.astimezone(timezone.utc)`.
  - `end = DTEND` if present, else `start + DURATION` if present, else all-day → start + 1 day, timed → start.
  - Mixed types (a DATE start with a DATETIME end) → treat it as all-day, using `end.date()`, and log DEBUG.
  - `summary`: stripped, max 500 characters. `location`: max 300. `description`: max 4,000 (US-09 cuts further for display). `status`: `TENTATIVE` → "TENTATIVE", `CANCELLED` → dropped, anything else → "CONFIRMED".
  - `tzid`: the TZID parameter of DTSTART, if any (display only).
- **D7. Per-calendar transaction**: `replace_calendar_events` + `set_sync_state` happen inside **one** `write_txn`. Add `EventStore.apply_calendar_sync(calendar_id, events, ctag, sync_token, window)` that does both, so a reader never sees new events with an old ctag or the other way round.
- **D8. The REPORT body** asks for `d:getetag` and `c:calendar-data`. Each `response` in the 207 has one resource (one UID, possibly with overrides). Parse each resource separately, so an error in one doesn't lose the others.
- **D9. The server's `calendar-data`** may be XML-escaped text (ElementTree unescapes it) or wrapped in CDATA (also handled). Encode to UTF-8 bytes before `Calendar.from_ical`.

---

## Implementation plan

### Step 1 — Check or install the libraries
```bash
sudo apt-get install -y python3-icalendar python3-recurring-ical-events     # devcontainer
/usr/bin/python3 -c "import icalendar, recurring_ical_events as r; print(icalendar.__version__, getattr(r,'__version__','?'))"
scripts/pi ssh 'apt-cache policy python3-icalendar python3-recurring-ical-events python3-x-wr-timezone'
```
Add them to `deps/apt-runtime.txt`. If the Pi lacks them or has old versions → D2 (vendoring). **Match the versions in the devcontainer and on the Pi as closely as you can**, because expansion details differ between versions. Tests run against the devcontainer version, so write down any known differences.

### Step 2 — `ical_parse.py`
```python
@dataclass
class ParseStats:
    resources: int = 0
    occurrences: int = 0
    parse_errors: int = 0
    cancelled: int = 0
    unknown_tz: int = 0
    capped: bool = False

def parse_resources(blobs: Iterable[bytes], calendar_id: str,
                    window: tuple[datetime, datetime], display_tz: ZoneInfo,
                    cap: int = 5000) -> tuple[list[Event], ParseStats]:
    stats = ParseStats(); out: list[Event] = []
    for blob in blobs:
        stats.resources += 1
        try:
            cal = icalendar.Calendar.from_ical(blob)
            masters = {c.get("UID"): c for c in cal.walk("VEVENT") if "RECURRENCE-ID" not in c}
            for occ in recurring_ical_events.of(cal).between(window[0], window[1]):
                ev = _to_event(occ, masters, calendar_id, display_tz, stats)
                if ev is not None:
                    out.append(ev); stats.occurrences += 1
                    if stats.occurrences >= cap:
                        stats.capped = True; return out, stats
        except Exception as e:
            stats.parse_errors += 1
            log.warning("unparseable resource in %s (uid=%s): %s", calendar_id, _peek_uid(blob), e)
    return out, stats
```
- `recurring_ical_events.of(cal).between(start, end)`: pass **aware UTC datetimes**. Check how the installed version treats floating events against an aware window. Some versions compare floating times as if they were in the window's zone. If they differ, add a fixture that reveals it, and handle it (for example by passing naive local window bounds when the calendar has floating events). **The test decides.**
- `_peek_uid(blob)`: a regex on `^UID:(.*)$` (multiline), with a length limit, for logging only.
- `_to_event()` implements D5 and D6. Return `None` for cancelled occurrences (and count them).
- **Floating times**: `icalendar` returns a naive `datetime`. Attach `display_tz` **with `.replace(tzinfo=...)`**. For `zoneinfo` that's correct (unlike pytz). Handle the DST gap and overlap as `zoneinfo` does (`fold=0`).
- **All-day windows**: an all-day occurrence overlaps the window if its dates overlap the window's local dates. `recurring_ical_events` handles that. Check with the fixtures.

### Step 3 — Additions to `EventStore`
```python
def calendars_for_account(self, account_id: str) -> list[Calendar]: ...
def sync_state(self, calendar_id: str) -> tuple[str | None, str | None, int | None, int | None]: ...  # ctag, token, window_start, window_end
def apply_calendar_sync(self, calendar_id, events, ctag, sync_token, window) -> int:
    with write_txn(self.conn):
        n = self._replace_events_no_txn(calendar_id, events)
        self.conn.execute("UPDATE calendars SET ctag=?, sync_token=?, window_start=?, window_end=? WHERE id=?", ...)
    return n
```
Refactor `replace_calendar_events` so that it and `apply_calendar_sync` share a `_replace_events_no_txn` helper. Keep US-04's tests passing.

### Step 4 — `fetch.py`
```python
@dataclass
class CalendarResult: calendar_id: str; name: str; status: str; events: int = 0
                      error: ErrorCode | None = None; detail: str = ""; duration_ms: int = 0
                      stats: ParseStats | None = None
@dataclass
class AccountResult: account_id: str; error: ErrorCode | None; detail: str; calendars: list[CalendarResult]

def compute_window(today, tz, back, forward, extra=None) -> tuple[datetime, datetime]: ...

def sync_account(account, secret, store, window, *, force=False, client=None) -> AccountResult:
    client = client or HttpClient(allowed_auth_hosts=provider_hosts(account.provider))
    auth = (account.username, secret)
    try:
        remotes = list_calendars(client, account, auth)      # 1 PROPFIND Depth 1 on home; rediscover on 404
    except SyncError as e:
        return AccountResult(account.id, e.code, e.detail, [])
    seen = set()
    results = []
    for rc in remotes:
        cid = calendar_id_for(account.id, rc.href); seen.add(cid)
        store.upsert_calendar(Calendar(id=cid, account_id=account.id, remote_href=rc.href,
                                       remote_name=rc.name, remote_color=rc.color, sort_order=rc.order or 0))
        results.append(_sync_one(client, auth, store, cid, rc, window, force))
    for cal in store.calendars_for_account(account.id):
        if cal.id not in seen:
            log.info("calendar removed on server: %s", cal.remote_name); store.delete_calendar(cal.id)
    return AccountResult(account.id, None, "", results)
```
**Careful**: `upsert_calendar` must not reset `sort_order` for existing rows (US-04 D5 says sort order is user-owned). Seed it on insert only: pass it, and have the upsert's `ON CONFLICT` leave `sort_order` alone. Check this against US-04's implementation.

`_sync_one`: the ctag check → REPORT → `parse_resources` → `apply_calendar_sync` → a `CalendarResult` with the timing. Catch `SyncError` per calendar (one calendar failing doesn't stop the others), and **catch everything else** as `UNKNOWN`, logged with the traceback.

REPORT body, built with `ET`:
```xml
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:getetag/><c:calendar-data/></d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="20260701T000000Z" end="20271001T000000Z"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>
```
The time format is `%Y%m%dT%H%M%SZ` in UTC.

`provider_hosts("icloud") → ("icloud.com",)`. Keep the provider switch in one small function. US-20 extends it.

### Step 5 — Settings keys
Register `K_SYNC_WINDOW_BACK` (int, 2, 0–12) and `K_SYNC_WINDOW_FORWARD` (int, 12, 1–36) in `settings_store.py`. They're hidden settings: no UI in P0.

### Step 6 — CLI `fetch`
```
python3 -m calpi.sync.cli fetch --account icloud-1a2b3c4d [--force] [--dry-run] [--from 2026-06 --to 2027-06]
```
It loads settings (for the time zone and window), credentials, and the store. `--dry-run` fetches and parses, prints per-calendar counts and the first 10 occurrences (summary, local start), and **doesn't** write. Without it, it writes and prints the `AccountResult`. `--clear-sample` calls `store.delete_sample_data()` first (so the dev grid shows only real data).

### Step 7 — The fixture suite (`tests/fixtures/ics/*.ics`, `tests/test_ical_parse.py`)

Write each fixture as a small, readable `.ics` file, with a comment block at the top (`X-CALPI-TEST:` lines, or a separate `expected.py` dictionary) describing the expected occurrences for a fixed window (for example 2026-03-01 → 2026-05-01, display zone `Europe/Berlin`). **Required cases:**

| # | Case | Expected |
|---|---|---|
| 1 | A simple timed event with a TZID | 1 occurrence, correct UTC |
| 2 | UTC `Z` times | the same |
| 3 | Floating time (no TZID) | interpreted in `Europe/Berlin` |
| 4 | All-day, 1 day (`VALUE=DATE`, DTEND the next day) | all_day, start = end - 1 day |
| 5 | All-day, 3 days | dates, exclusive end |
| 6 | All-day without DTEND | 1 day |
| 7 | Timed with DURATION | end = start + duration |
| 8 | Timed without DTEND or DURATION | zero length |
| 9 | Weekly RRULE, 09:00 Berlin, across the DST change (29 March 2026) | always 09:00 **local**, and the UTC offset changes |
| 10 | Weekly RRULE + EXDATE of one instance | that instance missing |
| 11 | RRULE + an override moving one instance to another day and time (RECURRENCE-ID) | the moved instance at its new time, the original slot empty |
| 12 | An override **moving an instance from outside the window into it** | present |
| 13 | An override **moving an instance from inside the window out of it** | absent |
| 14 | An override with `STATUS:CANCELLED` | absent, and `stats.cancelled` = 1 |
| 15 | An event with `STATUS:CANCELLED` | absent |
| 16 | `STATUS:TENTATIVE` | status TENTATIVE |
| 17 | A daily RRULE with no end, from 2020 | only the window's occurrences (61 for Mar–Apr), each with a recurrence id |
| 18 | RRULE with COUNT=5 | 5 |
| 19 | RRULE with UNTIL in UTC | the correct last instance |
| 20 | RDATE extra instances | included |
| 21 | A custom VTIMEZONE with a non-standard TZID name (for example `"Custom/Berlin"`) | uses the VTIMEZONE rules |
| 22 | An unknown TZID with no VTIMEZONE | floating, `unknown_tz` = 1 |
| 23 | A Windows TZID (`W. Europe Standard Time`) with no VTIMEZONE | mapped if the library supports it, else floating. The test documents the behaviour of the installed version |
| 24 | A monthly recurring all-day event | dates, never shifted |
| 25 | A timed event crossing midnight | start and end on different days |
| 26 | A malformed resource (broken lines) alongside a good one | the good one parsed, `parse_errors` = 1 |
| 27 | Two VEVENTs with different UIDs in one resource | both |
| 28 | A 900-character summary | truncated to 500 |
| 29 | An event entirely outside the window | absent |
| 30 | Mixed DATE start with a DATETIME end | treated as all-day |

Also `tests/test_fetch.py` with a fake transport:
- An unchanged ctag → no REPORT sent, status `unchanged`.
- A changed ctag → REPORT, then the store is updated, and the ctag is stored after success.
- The REPORT for one calendar fails with 503 → that calendar's `error=RATE_LIMITED`, the others still `ok`, and the store is unchanged for the failed one.
- A calendar removed on the server → deleted from the store. PROPFIND fails → **nothing deleted**.
- 401 at the PROPFIND → account-level `AUTH_FAILED`, and the store is untouched.
- The stored window smaller than the requested one (for example, the user browses 18 months ahead) → fetched even with an unchanged ctag.
- Transactionality: a failure between the replace and the set-state (monkeypatched) → rolled back.

### Step 8 — Real data on the Pi
```bash
scripts/pi deploy && scripts/pi deps
scripts/pi ssh 'cd /opt/calpi && sudo -u kiosk env STATE_DIRECTORY=/var/lib/calpi /usr/bin/time -v /usr/bin/python3 -m calpi.sync.cli fetch --account <id> --force --clear-sample' 2>&1 | tail -40
scripts/pi restart && scripts/pi screenshot
```
Record the time and the maximum RSS (acceptance criterion 9). Run it again without `--force` → expect `unchanged` and < 5 s. Compare the screenshot with the owner's phone calendar for this month and next, **together with the owner**. For each mismatch: capture the resource (the dev `--dump-dir` from US-14), anonymise it, **add it as a new fixture**, fix it, and repeat.

---

## Files

| File | Change |
|---|---|
| `calpi/sync/ical_parse.py`, `calpi/sync/fetch.py` | New |
| `calpi/sync/cli.py` | `fetch` subcommand |
| `calpi/data/event_store.py` | `calendars_for_account`, `sync_state`, `apply_calendar_sync` |
| `calpi/data/settings_store.py` | Window keys |
| `deps/apt-runtime.txt` | `python3-icalendar`, `python3-recurring-ical-events` (+ dependencies) |
| `calpi/_vendor/` | Only if D2 applies |
| `tests/fixtures/ics/*.ics`, `tests/test_ical_parse.py`, `tests/test_fetch.py` | New |

---

## Pitfalls

- **Doing expansion by hand.** Don't.
- **`.replace(tzinfo=...)` on pytz values**, or using fixed offsets. Normalise with `astimezone`.
- **Converting all-day dates to datetimes.** They stay dates.
- **Deleting calendars after a failed PROPFIND.** That would wipe the display on any network error.
- **Writing the ctag before the events**, or in a separate transaction (D7).
- **Importing `icalendar` from any UI module.** The UI process must stay light (US-36).
- **Trusting server strings**: truncate lengths (D6). Colours were already normalised in US-14.
- **Using the real "today" in tests.** Always pass `today` explicitly.

---

## Definition of done

- [ ] All 30 fixture cases and the fetch tests pass.
- [ ] Library versions recorded, apt or vendored.
- [ ] The owner's real calendars match on the Pi for two months, including recurring and all-day events.
- [ ] Timing and memory on the Pi recorded.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `fetch.sync_account(account, secret, store, window, force=False) -> AccountResult` (with `CalendarResult`s) | US-16 (called by the worker), US-18 (stores the results), US-20 |
| `fetch.compute_window(today, tz, back, forward, extra)` | US-16 |
| `calendar_id_for(account_id, href)` | US-25, US-26 |
| `EventStore.apply_calendar_sync`, `calendars_for_account`, `sync_state` | US-16, US-18, US-25 |
| `ical_parse.parse_resources(blobs, calendar_id, window, tz)` (a generic iCalendar parser) | US-20 (ICS subscriptions) |
| `K_SYNC_WINDOW_BACK/FORWARD` | US-16, US-27 (if exposed later) |
| `provider_hosts(provider)` | US-20 |
