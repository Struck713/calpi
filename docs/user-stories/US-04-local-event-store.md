# US-04 — Local event store

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P0 |
| **Blocked by** | US-02 App skeleton |
| **Blocks** | US-07 Events in the grid, US-15 Event fetching and parsing |
| **Phase** | 1. Foundation |

## Story

> As a user, I want events saved on the device so the calendar appears right away at boot and stays visible offline. Includes a sample-data loader for development.

## Context

The event store is the **hand-off point between syncing and displaying**. The sync process (US-15/16) writes calendars and events into it. The UI (US-07, US-09, US-39, US-40) reads from it. Neither side ever talks to the other directly about events. That separation is what makes the display instant at boot (it reads what's already on disk) and keeps it working offline (the last good data stays until a newer sync replaces it).

It also holds the **calendar list** (name, colour, visibility), because every event belongs to a calendar and the grid needs the calendar's colour to draw it. User changes to calendars (rename, recolour, hide: US-26) are stored in **separate columns that sync never overwrites**.

Phase 1 of the plan has to show a working calendar **before** any syncing exists. That's what the **sample-data loader** is for: realistic calendars and events, generated relative to today, covering every tricky display case.

Read the [README](README.md) sections "State on the device" and "Threading and process rules" before you start.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-02** App skeleton | `calpi/paths.py` (`state_dir()`), the `calpi/data/` package, pytest setup, the `--state-dir` flag, `scripts/smoke.sh` | `/usr/bin/python3 -c "from calpi import paths; print(paths.state_dir())"` prints a path. `/usr/bin/python3 -m pytest` passes. `scripts/smoke.sh` → `SMOKE OK`. |

### Soft dependencies
- **US-03** Deploy workflow: needed to load sample data on the Pi and check the startup read there (acceptance criterion 9). If it isn't done, check in the devcontainer and leave the Pi check for later, **saying so in the notes**.
- **US-12** (later) adds an integrity check at startup that uses `EventStore.integrity_ok()` from this story.

### External blockers
- **SQLite version**: the Python `sqlite3` module links to the system library. The schema uses only features from SQLite 3.24+ (UPSERT with `ON CONFLICT ... DO UPDATE`). Bookworm and Trixie are both well above that. Check with `/usr/bin/python3 -c "import sqlite3; print(sqlite3.sqlite_version)"` in the devcontainer and on the Pi, and record it in `docs/platform-versions.md`.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| `sqlite3.OperationalError: database is locked` in tests | Two connections are writing at the same time without `busy_timeout`, or a connection was left with an open transaction. Always go through `db.connect()` (which sets `busy_timeout`), and use `with conn:` blocks for writes. |
| You're not sure how all-day events should be stored | It's decided below (D4). Don't reopen it: US-07, US-09, and US-15 all depend on it. |
| Recurrence isn't handled here | That's deliberate. The store holds **occurrences**, which are already expanded. US-15 does the expansion. The sample data writes pre-expanded occurrences. |

---

## Scope

### In scope
- `calpi/data/models.py`: the `Calendar` and `Event` dataclasses.
- `calpi/data/db.py`: the connection factory, pragmas, and schema migrations.
- `calpi/data/event_store.py`: the `EventStore` API (below).
- `calpi/data/sample_data.py`: a deterministic generator and a CLI loader. The app gets a `--sample-data` flag.
- `scripts/pi sample-data`: loads sample data on the Pi.
- Unit tests.

### Out of scope
- Showing anything (US-06/07).
- Fetching or parsing (US-15), and account records (those go in settings: US-14).
- Sync status columns (US-18 adds them with a migration).
- Any UI for choosing calendars (US-25/26).

---

## Acceptance criteria

1. The database file is `<state_dir>/calpi.sqlite3`. Every connection opened through `db.connect()` has `journal_mode=wal`, `synchronous=NORMAL` (1), `foreign_keys=ON`, and `busy_timeout=5000`.
2. The schema is created on first open, and **migrations are versioned** (`meta.schema_version`). Opening an existing database at the current version doesn't change it. A test shows that a v1 database is migrated when a v2 migration is added (a fake migration in the test).
3. `EventStore.events_for_days(first_day, end_day, tz)` returns every **visible** (non-hidden-calendar) occurrence that overlaps the local days `[first_day, end_day)` in time zone `tz`, sorted as described in D6. It includes:
   - timed events overlapping the range (including ones that start before and end inside, and ones spanning the whole range),
   - all-day events overlapping the date range (including multi-day ones),
   - with `end` exclusive (an event ending exactly at the range start is **not** included).
4. `replace_calendar_events(calendar_id, events)` swaps **all** occurrences of that calendar in **one transaction**. A reader on another connection sees either the old set or the new set, never a mix (a test shows this with two connections).
5. `upsert_calendar()` updates only `remote_*` fields and the sync fields. It **never** changes `user_name`, `user_color`, `hidden`, or `sort_order` on an existing row.
6. Deleting a calendar deletes its events (`ON DELETE CASCADE`).
7. `revision()` increases after every write transaction (upsert, replace, delete, override change). The UI uses it to skip unnecessary reloads.
8. `python3 -m calpi.data.sample_data --load [--clear] [--state-dir DIR]` fills the store with the sample set (D8). Running `--load` twice gives the **same** result (no duplicates). `run.py --sample-data` loads the samples at startup **only if the store has no calendars at all**.
9. On the Pi, with sample data loaded, reading one month of events at startup takes **under 20 ms** (log the time at DEBUG level). In the devcontainer, a test with **5,000 events** spread over 2 years returns one month in under 20 ms.
10. `integrity_ok()` runs `PRAGMA quick_check` and returns True or False. It's used by US-12.
11. No module in `calpi/data/` imports `gi` (a test checks this, see Testing).

---

## Design decisions (already made)

- **D1. SQLite with WAL.** WAL lets the UI process read while the sync process writes, and `synchronous=NORMAL` in WAL mode is safe against corruption on power loss. (The most recent transaction might be rolled back, which is fine because the next sync redoes it.) Don't use `synchronous=OFF`.
- **D2. One connection per thread and per process**, always opened with `db.connect(path)`. Connections are **not** shared between threads (`check_same_thread` stays at its default of True, so mistakes fail loudly).
- **D3. The store holds occurrences.** A recurring event is stored as one row per instance inside the synced window. Occurrence identity is `(calendar_id, uid, recurrence_id)`, where `recurrence_id` is `''` for a non-recurring event and otherwise the ISO text of the instance's *original* start.
- **D4. Time representation:**
  - **Timed events**: `start_utc` and `end_utc` are INTEGER Unix seconds (UTC). `all_day = 0`. `start_date`/`end_date` are NULL.
  - **All-day events**: `start_date` and `end_date` are TEXT `YYYY-MM-DD`, with **`end_date` exclusive** (as in iCalendar: a one-day event on 5 March has `start_date=2026-03-05`, `end_date=2026-03-06`). `all_day = 1`. `start_utc`/`end_utc` are NULL.
  - All-day events are **floating**: they belong to a date, not a moment, so they appear on the same dates whatever the display time zone.
  - In Python, `Event.start` and `Event.end` are aware UTC `datetime`s for timed events and `date`s for all-day events.
  - `tzid` stores the event's original time zone name (for example `Europe/Paris`), if there was one. It's for display only (US-09 can say "10:00 Paris time") and is optional.
- **D5. Calendar identity**: `calendars.id` is a stable local string. For synced calendars it's `f"{account_id}:{sha1(remote_href)[:16]}"` (US-15 builds it). For sample calendars it's `sample:<name>`. Colours are stored as `#RRGGBB` (lowercase).
- **D6. Sort order** returned by `events_for_days`: all-day events first (longer spans first, then calendar `sort_order`, then summary), then timed events by `start_utc`, then longer duration first, then calendar `sort_order`, then summary (case-insensitive). The UI can rely on this order.
- **D7. The UI process may write only** through `set_calendar_overrides()` (US-26) and the sample loader in dev mode. Everything else is written by the sync process.
- **D8. Sample data is generated relative to "today"** (passed in, so tests are deterministic) and covers these cases: several timed events today; an all-day event today; a 3-day all-day event that crosses a week boundary; a 2-day **timed** event (Friday 18:00 → Sunday 12:00); an event crossing midnight (22:30 → 01:00); a day with **9** events (to test overflow); an event that crosses the month boundary; a very long title (80+ characters); a weekly recurring event, stored as pre-expanded occurrences for ±3 months; a hidden calendar with events (which must not appear); and events in the previous and next months. Three visible calendars: `Family` `#4f9dff`, `Work` `#3ecf8e`, `School` `#ffb020`, plus the hidden `Archive` `#9aa4ae`.
- **D9. A `revision` counter in `meta`**, incremented inside every write transaction. It's simpler and more explicit than `PRAGMA data_version` (which works per connection).

---

## Implementation plan

### Step 1 — `calpi/data/models.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime

DEFAULT_CALENDAR_COLOR = "#9aa4ae"

@dataclass(frozen=True, slots=True)
class Calendar:
    id: str
    remote_name: str
    account_id: str | None = None
    remote_href: str | None = None
    remote_color: str | None = None
    user_name: str | None = None
    user_color: str | None = None
    hidden: bool = False
    sort_order: int = 0

    @property
    def name(self) -> str:
        return self.user_name or self.remote_name

    @property
    def color(self) -> str:
        return self.user_color or self.remote_color or DEFAULT_CALENDAR_COLOR

@dataclass(frozen=True, slots=True)
class Event:
    calendar_id: str
    uid: str
    summary: str
    all_day: bool
    start: datetime | date      # aware UTC datetime if timed, date if all-day
    end: datetime | date        # exclusive
    recurrence_id: str = ""
    location: str = ""
    description: str = ""
    status: str = "CONFIRMED"   # CONFIRMED | TENTATIVE (CANCELLED is never stored)
    tzid: str | None = None

    def __post_init__(self):
        if self.all_day:
            if isinstance(self.start, datetime) or isinstance(self.end, datetime):
                raise ValueError("all-day events use date, not datetime")
        else:
            for v in (self.start, self.end):
                if not isinstance(v, datetime) or v.tzinfo is None:
                    raise ValueError("timed events need aware datetimes")
        if self.end < self.start:
            raise ValueError("end before start")
```
Watch out: `datetime` is a subclass of `date`, so check for `datetime` first. The validation in `__post_init__` catches mistakes early, in US-15 too.

A zero-length timed event (start == end) is allowed. iCalendar allows it (for example a DTSTART with no DTEND). Treat it as overlapping any range that contains its start.

### Step 2 — `calpi/data/db.py`

```python
import logging, sqlite3
from pathlib import Path
from calpi import paths

log = logging.getLogger("calpi.db")
DB_NAME = "calpi.sqlite3"

def default_path() -> Path:
    return paths.state_dir() / DB_NAME

def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or default_path()), timeout=5.0, isolation_level=None)  # autocommit; we manage txns
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    migrate(conn)
    return conn
```
**Transactions**: with `isolation_level=None` (autocommit), wrap writes in explicit `BEGIN IMMEDIATE` … `COMMIT`, using a small context manager:
```python
from contextlib import contextmanager
@contextmanager
def write_txn(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'revision'")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
```
`BEGIN IMMEDIATE` takes the write lock at the start, which avoids deadlocks when both processes upgrade from reader to writer.

**Migrations**: a list of functions, one per version:
```python
def _v1(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    INSERT OR IGNORE INTO meta(key, value) VALUES ('revision', '0');
    CREATE TABLE calendars(
        id            TEXT PRIMARY KEY,
        account_id    TEXT,
        remote_href   TEXT,
        remote_name   TEXT NOT NULL,
        remote_color  TEXT,
        user_name     TEXT,
        user_color    TEXT,
        hidden        INTEGER NOT NULL DEFAULT 0,
        sort_order    INTEGER NOT NULL DEFAULT 0,
        ctag          TEXT,
        sync_token    TEXT,
        window_start  INTEGER,     -- unix seconds of the synced window (US-15)
        window_end    INTEGER
    );
    CREATE INDEX calendars_account ON calendars(account_id);
    CREATE TABLE events(
        id            INTEGER PRIMARY KEY,
        calendar_id   TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
        uid           TEXT NOT NULL,
        recurrence_id TEXT NOT NULL DEFAULT '',
        summary       TEXT NOT NULL DEFAULT '',
        location      TEXT NOT NULL DEFAULT '',
        description   TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'CONFIRMED',
        all_day       INTEGER NOT NULL,
        start_utc     INTEGER,
        end_utc       INTEGER,
        start_date    TEXT,
        end_date      TEXT,
        tzid          TEXT,
        UNIQUE(calendar_id, uid, recurrence_id),
        CHECK ((all_day = 0 AND start_utc IS NOT NULL AND end_utc IS NOT NULL)
            OR (all_day = 1 AND start_date IS NOT NULL AND end_date IS NOT NULL))
    );
    CREATE INDEX events_timed  ON events(start_utc, end_utc) WHERE all_day = 0;
    CREATE INDEX events_allday ON events(start_date, end_date) WHERE all_day = 1;
    CREATE INDEX events_cal    ON events(calendar_id);
    """)

MIGRATIONS = [_v1]   # index 0 -> schema version 1

def migrate(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    current = int(row[0]) if row else 0
    for version in range(current + 1, len(MIGRATIONS) + 1):
        log.info("migrating database to schema v%d", version)
        conn.execute("BEGIN IMMEDIATE")
        try:
            MIGRATIONS[version - 1](conn)
            conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(version),))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK"); raise
```
Careful: `executescript` issues its own `COMMIT` first, which ends the `BEGIN IMMEDIATE`. So write migrations as separate `conn.execute(...)` statements, **or** split the script and run each statement with `execute`. Pick one and test that a failing migration really rolls back. (The simplest fix: a helper `_exec_many(conn, sql)` that splits on `;` and skips empty parts. That's fine here, because none of our SQL has semicolons inside string literals.)

Both processes (the UI and sync) can call `migrate()` at the same time. `BEGIN IMMEDIATE` serialises them. Re-read the version **after** getting the lock, so the second process doesn't run the same migration again: move the `SELECT` inside the transaction, per version.

### Step 3 — `calpi/data/event_store.py`

```python
class EventStore:
    def __init__(self, path: Path | None = None):
        self.conn = db.connect(path)

    # --- calendars ---
    def list_calendars(self, include_hidden: bool = True) -> list[Calendar]: ...
    def get_calendar(self, calendar_id: str) -> Calendar | None: ...
    def upsert_calendar(self, cal: Calendar) -> None:
        """Insert, or update remote_* only. Never touches user_* / hidden / sort_order of existing rows."""
        # INSERT ... ON CONFLICT(id) DO UPDATE SET remote_name=excluded.remote_name, remote_color=excluded.remote_color,
        #    remote_href=excluded.remote_href, account_id=excluded.account_id
    def set_calendar_overrides(self, calendar_id: str, *, user_name=..., user_color=..., hidden=..., sort_order=...) -> None:
        """Only the keyword arguments actually passed are changed. Use a sentinel default (_UNSET)."""
    def delete_calendar(self, calendar_id: str) -> None: ...
    def delete_calendars_for_account(self, account_id: str) -> None: ...
    def delete_sample_data(self) -> None:  # DELETE FROM calendars WHERE id LIKE 'sample:%'
        ...

    # --- events ---
    def replace_calendar_events(self, calendar_id: str, events: Iterable[Event],
                                window: tuple[datetime, datetime] | None = None) -> int:
        """Atomically replace every occurrence of a calendar. Returns the number stored."""
    def events_for_days(self, first_day: date, end_day: date, tz: ZoneInfo,
                        include_hidden: bool = False) -> list[Event]: ...
    def count_events(self) -> int: ...

    # --- housekeeping ---
    def revision(self) -> int: ...
    def integrity_ok(self) -> bool:  # PRAGMA quick_check == 'ok'
        ...
    def close(self) -> None: ...
```

**`events_for_days` query** (make sure you understand this; it's the core of the display):
```python
range_start_utc = int(datetime.combine(first_day, time.min, tz).timestamp())
range_end_utc   = int(datetime.combine(end_day,   time.min, tz).timestamp())
sql = """
SELECT e.*, c.sort_order AS cal_sort FROM events e JOIN calendars c ON c.id = e.calendar_id
WHERE (:include_hidden OR c.hidden = 0) AND (
      (e.all_day = 0 AND e.start_utc < :end_utc AND (e.end_utc > :start_utc OR (e.end_utc = e.start_utc AND e.start_utc >= :start_utc)))
   OR (e.all_day = 1 AND e.start_date < :end_date AND e.end_date > :start_date))
"""
```
- `datetime.combine(d, time.min, tz)` with a `zoneinfo.ZoneInfo` gives the right local midnight, even across DST changes. Don't add `timedelta(days=n)` to a local datetime to get "n days later": work with dates, then combine.
- Sort in Python (D6) after building `Event` objects. There are at most a few hundred rows per month. Sorting in SQL is harder to get right across both kinds of event.
- Row → `Event`: `datetime.fromtimestamp(row["start_utc"], tz=timezone.utc)` and `date.fromisoformat(row["start_date"])`.

**`replace_calendar_events`**:
```python
with write_txn(self.conn):
    self.conn.execute("DELETE FROM events WHERE calendar_id = ?", (calendar_id,))
    self.conn.executemany("INSERT INTO events(...) VALUES (...)", rows)
    if window: self.conn.execute("UPDATE calendars SET window_start=?, window_end=? WHERE id=?", ...)
```
If the input has duplicate `(uid, recurrence_id)` pairs (servers sometimes send them), **keep the last one**: build a dict keyed by identity before inserting, and log a DEBUG line with the count of duplicates dropped. Don't let the UNIQUE constraint abort the whole sync.

### Step 4 — `calpi/data/sample_data.py`

```python
def sample_calendars() -> list[Calendar]: ...
def sample_events(today: date, tz: ZoneInfo) -> list[Event]: ...   # covers every case in D8
def load(store: EventStore, today: date, tz: ZoneInfo, clear: bool = False) -> int:
    if clear: store.delete_sample_data()
    for c in sample_calendars(): store.upsert_calendar(c)
    by_cal = defaultdict(list)
    for e in sample_events(today, tz): by_cal[e.calendar_id].append(e)
    return sum(store.replace_calendar_events(cid, evs) for cid, evs in by_cal.items())

if __name__ == "__main__":
    # argparse: --load, --clear, --state-dir, --today YYYY-MM-DD (optional; default real today)
    ...
```
- **Generate timed events in local time, then convert to UTC**: `datetime.combine(day, time(9, 30), tz).astimezone(timezone.utc)`.
- The local time zone: US-06 adds `calpi.data.timeutil.display_tz()`. If US-06 isn't done yet, use a private helper `_system_tz()` that reads `/etc/timezone`, or resolves the `/etc/localtime` symlink to a zone name, falling back to `UTC`. Mark it with a comment `# TODO(US-06): use timeutil.display_tz()`. **The US-06 implementer must remove the TODO.**
- Recurring sample events: generate weekly occurrences with `recurrence_id = original_start.isoformat()` and the same `uid`.
- Use fixed UIDs (`sample-<n>@calpi`) so loading twice gives the same rows.

**App flag**: in `calpi/app.py` `parse_args`, add `--sample-data` (and read the environment variable `CALPI_SAMPLE_DATA=1` too, so a systemd drop-in can turn it on for the Pi during phase 1). In `_on_activate`, **before** building screens:
```python
if self.args.sample_data or os.environ.get("CALPI_SAMPLE_DATA") == "1":
    store = EventStore()
    if not store.list_calendars():
        n = sample_data.load(store, today, tz)
        log.info("loaded %d sample events", n)
```
Keep this quick. It only happens on an empty store.

### Step 5 — `scripts/pi sample-data` (small addition to US-03's script)

```bash
sample-data) shift
  remote "cd /opt/calpi && sudo -u kiosk env STATE_DIRECTORY=/var/lib/calpi /usr/bin/python3 -m calpi.data.sample_data --load $*"
  ;;
```
Then `scripts/pi restart` to see it. (Optional: a systemd drop-in with `Environment=CALPI_SAMPLE_DATA=1` for phase 1. **Remove it before the syncing phase.** Document this in the US-03 skill doc if you add it.)

If US-03 isn't done yet, skip this step and note it in the hand-off notes.

### Step 6 — Tests (`tests/test_event_store.py`, `tests/test_sample_data.py`, `tests/test_no_gi.py`)

Use `tmp_path` for the database path. Use `ZoneInfo("Europe/Berlin")` and `ZoneInfo("America/New_York")` so DST is covered.

Required cases:
1. The pragmas are set (`PRAGMA journal_mode` → `wal`, and so on).
2. A new database is at schema v1. Reopening doesn't change it. A test-only migration v2 (monkeypatch `MIGRATIONS`) runs once. A failing migration rolls back and leaves the version unchanged.
3. Overlap cases for timed events: before the range (excluded), ending exactly at the range start (excluded), starting exactly at the range end (excluded), straddling the start, straddling the end, covering the whole range, zero-length at the range start (included).
4. All-day: one day on the first day (included), one day on the day *before* the range (excluded), multi-day from before to inside (included), `end_date == first_day` (excluded).
5. **DST**: a month containing the DST change in Berlin (for example March 2026: 29 March). An event at 02:30 local time on the day after the change still falls on the right day. A 1-hour event 00:30–01:30 on the change day is on that day.
6. Hidden calendars are excluded by default and included with `include_hidden=True`.
7. `upsert_calendar` keeps user overrides. `set_calendar_overrides` changes only what's passed.
8. `replace_calendar_events` is atomic: open a second connection. In the first, begin a replace and **pause** inside the transaction (use a generator that raises partway). Check that the second connection still sees the old rows, and that after the exception the old rows are still there (it rolled back).
9. Duplicate identities in the input → the last one wins, no exception.
10. Cascade: deleting a calendar removes its events.
11. `revision()` increases with every write.
12. Performance: 5,000 events over 2 years; `events_for_days` for one month < 20 ms (measure with `time.perf_counter`; allow a generous margin in CI, and only **warn** above 20 ms, but fail above 200 ms).
13. Sample data: `load` twice → the same count. Every D8 case is present (check by `uid` or summary). The hidden calendar's events are excluded from `events_for_days`.
14. `test_no_gi.py`: import every module under `calpi.data` in a **subprocess** and assert `'gi' not in sys.modules`.

### Step 7 — Check on the Pi (needs US-03)

```bash
scripts/pi deploy
scripts/pi sample-data --clear
scripts/pi ssh 'sudo -u kiosk sqlite3 /var/lib/calpi/calpi.sqlite3 "select count(*) from events; pragma journal_mode;"'   # sqlite3 CLI may need: sudo apt install sqlite3
```
(Nothing is displayed until US-06/07 are done. This check is only about storage.) Time a month query on the Pi:
```bash
scripts/pi ssh 'cd /opt/calpi && sudo -u kiosk env STATE_DIRECTORY=/var/lib/calpi /usr/bin/python3 -c "
import time, datetime as d
from zoneinfo import ZoneInfo
from calpi.data.event_store import EventStore
s=EventStore(); t=time.perf_counter(); ev=s.events_for_days(d.date.today().replace(day=1), d.date.today().replace(day=28), ZoneInfo(\"UTC\"))
print(len(ev), round((time.perf_counter()-t)*1000,1), \"ms\")"'
```

---

## Files

| File | Change |
|---|---|
| `calpi/data/models.py`, `db.py`, `event_store.py`, `sample_data.py` | New |
| `calpi/app.py` | `--sample-data` flag / `CALPI_SAMPLE_DATA` |
| `scripts/pi` | `sample-data` subcommand |
| `tests/test_event_store.py`, `tests/test_sample_data.py`, `tests/test_no_gi.py` | New |

---

## Pitfalls

- **Treating all-day events as UTC midnights.** They're dates. Converting them to instants makes them shift by a day in some time zones.
- **Adding `timedelta(days=1)` to an aware local datetime around DST.** You get 23 or 25 hours of drift. Always combine a `date` with `time.min` and the zone.
- **`executescript` inside a transaction** silently commits. See step 2.
- **Sharing one connection between the UI thread and a worker thread.** Open a new one in each thread.
- **Storing colours in mixed case or without `#`.** Normalise to lowercase `#rrggbb` in `upsert_calendar`.
- **Forgetting `ORDER`/sorting**: the UI depends on D6.
- **Letting the sample loader run on every start.** Only load into an empty store.

---

## Definition of done

- [ ] All acceptance criteria met. The tests cover every listed case.
- [ ] `test_no_gi.py` passes.
- [ ] Sample data loaded on the Pi and the timing recorded (or explicitly deferred because US-03 isn't done).
- [ ] The SQLite version recorded in `docs/platform-versions.md`.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `Event`, `Calendar` dataclasses (fields, `name`/`color` properties, the all-day/timed representation) | US-07, US-09, US-15, US-26, US-39, US-40 |
| `EventStore.events_for_days(first_day, end_day, tz)` and its sort order (D6) | US-07, US-09, US-39, US-40 |
| `EventStore.replace_calendar_events`, `upsert_calendar`, `delete_calendars_for_account`, `delete_sample_data` | US-15, US-25 |
| `EventStore.set_calendar_overrides` | US-26 |
| `EventStore.revision()` | US-07 (skip reloads), US-16 |
| `EventStore.integrity_ok()` | US-12 |
| `db.connect()`, `db.write_txn()`, `db.MIGRATIONS` (append-only list) | US-18 (adds the sync status migration), anyone who adds tables |
| Calendar ids: `<account_id>:<sha1(href)[:16]>` and `sample:<name>` | US-15, US-25, US-26 |
| `--sample-data` / `CALPI_SAMPLE_DATA=1` | US-06, US-07, US-36 (test data) |
