# US-05 — Settings store

| | |
|---|---|
| **Epic** | 1. Foundation |
| **Priority** | P0 |
| **Blocked by** | US-02 App skeleton |
| **Blocks** | US-13 Secure credential storage, US-16 Scheduled background sync, US-22 Settings shell |
| **Phase** | 1. Foundation |

## Story

> As a user, I want my settings saved on the device so they survive restarts and power cuts.

## Context

Everything the owner configures lives here: time zone, week start, time format, sync interval, brightness, the dim schedule, the list of calendar accounts, whether setup is finished, and so on. Nearly every later story adds a key.

Three properties matter more than anything else:
1. **It survives power cuts.** The Pi can lose power in the middle of a write, and a half-written settings file must never be left behind. That means atomic writes (write a temp file, `fsync`, rename, `fsync` the directory), a backup copy, and a safe fallback to defaults.
2. **It's typed and validated.** A bad value on disk (from an old version, a bug, or corruption) must never crash the app. It falls back to the key's default and logs a warning.
3. **It's observable.** When a setting changes, the parts of the UI that depend on it update straight away (for example, changing the week start redraws the grid). So there are change callbacks per key.

The store is pure Python with **no gi imports**, so the sync process (US-16) can read it and it can be unit-tested anywhere.

This story also creates `calpi/data/atomic.py`, which **US-13 (credentials) reuses**. That's why US-13 is blocked by this story.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-02** App skeleton | `calpi/paths.py` (`state_dir()`), the `calpi/data/` package, pytest, `CalpiApp` (where the store is created once) | `/usr/bin/python3 -c "from calpi import paths; print(paths.state_dir())"` works. `/usr/bin/python3 -m pytest` passes. |

### Soft dependencies
- **US-03** for the power-cut test on the Pi (acceptance criterion 8). Without it, do the simulated tests in the devcontainer and leave the hardware check to US-12, saying so in the notes.

### External blockers
None.

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| You're not sure whether a setting belongs here or in the event store | Rule: **user preferences and account records** go here. **Calendars, events, and sync status** go in the event store (US-04). Calendar display overrides (rename/recolour/hide) go in the event store's `calendars` table (US-26). |
| You want to use TOML because the skill mentions `/etc/calpi/config.toml` | The skill's `config.toml` is for **read-only, deployment-level** configuration. It isn't used in P0. This store is **read-write, runtime** state, so JSON (stdlib `json`) is simpler and round-trips cleanly. The decision is made (D1). |

---

## Scope

### In scope
- `calpi/data/atomic.py`: `atomic_write_bytes()`, `atomic_write_json()`.
- `calpi/data/settings_store.py`: `SettingsStore` with the key registry, defaults, validation, observers, backup and recovery, and a schema version with migrations.
- The first keys: `schema_version`, `setup_completed` (the other keys arrive with their stories).
- Wiring: one store instance created in `CalpiApp`, available as `app.settings`.
- Tests, including simulated power cuts.

### Out of scope
- Any settings UI (US-22 onwards).
- Secrets (US-13). **Passwords never go in `settings.json`.**
- Calendar overrides (US-26, event store).

---

## Acceptance criteria

1. Settings are stored in `<state_dir>/settings.json` as UTF-8 JSON, pretty-printed (`indent=2`, sorted keys), so it's easy to read over SSH.
2. **Every** write is atomic: write `settings.json.tmp` → `flush` → `os.fsync(file)` → `os.replace(settings.json → settings.json.bak)` (if it exists) → `os.replace(tmp → settings.json)` → `os.fsync(directory)`. A test shows that killing the write at **each** step leaves a loadable state.
3. Loading order: `settings.json` → if it's missing or unparseable, `settings.json.bak` → if that fails too, defaults. An unparseable file is renamed `settings.json.corrupt-<unix-ts>` (keeping at most 3 of those), and an ERROR is logged. The app **never** fails to start because of settings.
4. `get(key)` returns the stored value, or the key's default. Asking for an unregistered key raises `KeyError` (it's a programming error).
5. `set(key, value)` validates. An invalid value raises `ValueError` and doesn't change anything. A valid value that's **equal to the current value doesn't write to disk** and doesn't notify.
6. `update({...})` sets several keys with **one** write, and notifies each changed key once.
7. Observers: `subscribe(key, callback) -> token`, `unsubscribe(token)`. A callback gets `(key, new_value)` after a successful write. An exception in one callback is logged and doesn't stop the others.
8. On the Pi (needs US-03): change a setting, cut the power within a second (or run `echo b | sudo tee /proc/sysrq-trigger` for an immediate reboot without syncing), boot, and the setting is either the old value or the new value. It's never corrupt, and never the defaults (unless both files were bad).
9. Values read from disk with the wrong type or out of range are **replaced by the default in memory** and logged as a WARNING. The file is corrected on the next write.
10. **Unknown keys** in the file (for example from a newer version) are **kept** when saving, and logged once at INFO.
11. `schema_version` exists. A migration function list upgrades older files (tested with a fake v0 → v1 migration).
12. `get()` of a list or dict returns a **copy**. Changing the returned object doesn't change the store.
13. The store is thread-safe for reads and writes (an internal `threading.Lock`), but **observers are only called on the thread that called `set`**. Convention: only call `set` from the main thread.

---

## Design decisions (already made)

- **D1. JSON file**, not SQLite, not TOML. It's small, easy to read, and the stdlib handles it.
- **D2. A key registry**: each key is registered once with a type, a default, and an optional validator. **Stories add keys to `calpi/data/settings_store.py` in the `DEFAULTS` registry**, never with ad-hoc strings elsewhere. Constants for key names (`K_TIMEZONE = "timezone"`, and so on) live in the same module.
- **D3. Only the UI process writes.** The sync process reads `settings.json` fresh at the start of each run (a new process each time). If a new writer is ever needed, it goes through the UI process.
- **D4. No gi imports.** Observers are plain callables. Anything that needs to hop threads uses `calpi.tasks.call_on_main` at the call site.
- **D5. Writes happen right away (synchronous)**, and they're small (a few KB). **UI controls that change quickly (sliders) must only commit when released, or after a 500 ms debounce.** That rule is enforced in the UI stories (US-29), not here.
- **D6. The backup is the previous good version** (see acceptance criterion 2). It's written for free by the rename sequence, with no extra writes.
- **D7. `fsync` the directory** after the rename, so the rename itself survives power loss on ext4.

---

## Implementation plan

### Step 1 — `calpi/data/atomic.py`

```python
"""Crash-safe file writes. No gi imports."""
from __future__ import annotations
import json, os
from pathlib import Path

def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600, keep_backup: bool = False) -> None:
    """Write `data` to `path` so that after a power cut either the old or the new content exists.

    keep_backup=True moves the previous file to `<path>.bak` first (the backup = last good version).
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        try: tmp.unlink()
        except FileNotFoundError: pass
        raise
    if keep_backup and path.exists():
        os.replace(path, path.with_name(path.name + ".bak"))
    os.replace(tmp, path)
    _fsync_dir(path.parent)

def atomic_write_json(path: Path, obj, **kw) -> None:
    data = (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    atomic_write_bytes(path, data, **kw)
```
Points to check:
- `mode=0o600`: settings don't hold secrets, but the account list holds email addresses. Keep it private.
- **If power is lost between the two `os.replace` calls**, `settings.json` is missing and `.bak` holds the previous version. The loader handles that (acceptance criterion 3).
- A leftover `settings.json.tmp` from an earlier crash is simply overwritten (`O_TRUNC`).

### Step 2 — The key registry

```python
from dataclasses import dataclass
from typing import Any, Callable

@dataclass(frozen=True)
class Key:
    name: str
    type: type | tuple[type, ...]
    default: Any
    validate: Callable[[Any], bool] | None = None

K_SCHEMA_VERSION = "schema_version"
K_SETUP_COMPLETED = "setup_completed"

REGISTRY: dict[str, Key] = {}
def register(key: Key) -> Key:
    if key.name in REGISTRY: raise ValueError(f"duplicate key {key.name}")
    REGISTRY[key.name] = key
    return key

register(Key(K_SCHEMA_VERSION, int, 1))
register(Key(K_SETUP_COMPLETED, bool, False))
# Later stories append here, e.g. (US-08):
# register(Key(K_INACTIVITY_RETURN_SECONDS, int, 120, lambda v: 30 <= v <= 3600))
```
Type checking: `isinstance(v, bool)` must be checked **before** `int`, because `bool` is a subclass of `int`. `True` must not be accepted for an int key. Write a helper `_type_ok(value, type)` that handles this and `None` (for keys whose type includes `type(None)`).

Put a comment block at the top of the registry listing the planned keys from the README table, so later stories know where to add theirs.

### Step 3 — `SettingsStore`

```python
class SettingsStore:
    FILE = "settings.json"
    def __init__(self, directory: Path | None = None):
        self._dir = Path(directory) if directory else paths.state_dir()
        self._path = self._dir / self.FILE
        self._lock = threading.RLock()
        self._values: dict[str, Any] = {}
        self._unknown: dict[str, Any] = {}
        self._observers: dict[int, tuple[str, Callable]] = {}
        self._next_token = 1
        self._load()

    # public API
    def get(self, key: str): ...
    def set(self, key: str, value) -> bool: ...          # returns True if it changed
    def update(self, changes: dict[str, Any]) -> list[str]: ...  # returns changed keys
    def reset(self, key: str) -> bool: ...                # back to default
    def subscribe(self, key: str, cb: Callable[[str, Any], None]) -> int: ...
    def unsubscribe(self, token: int) -> None: ...
    def snapshot(self) -> dict[str, Any]: ...             # deep copy of everything (for the Status screen / debugging)
    @property
    def path(self) -> Path: ...
```

**Loading (`_load`)**:
1. Try `settings.json`: read, `json.loads`, and require a dict at the top level. On `FileNotFoundError`, go to 2 silently. On any parse error, log ERROR, **rename it to `.corrupt-<ts>`**, and go to 2.
2. Try `settings.json.bak` the same way. If it's used, log WARNING "restored settings from backup".
3. Otherwise start from `{}`.
4. Run migrations (step 4) on the raw dict.
5. For each registered key: if it's present and valid, use it. If it's present and invalid, WARN and use the default. If it's missing, use the default (**don't** store defaults in `_values`: keep only what's explicitly set, so a change to a default in a later version takes effect. `get()` falls back to `REGISTRY[key].default`).
6. Keys that aren't registered go into `_unknown` (logged once at INFO), and are written back unchanged.
7. Remove old `.corrupt-*` files beyond the newest 3.

**Saving (`_save`)**: `data = {**self._unknown, **self._values, "schema_version": CURRENT}` → `atomic_write_json(self._path, data, keep_backup=True)`. On `OSError` (disk full, read-only filesystem), **log ERROR and re-raise**. The caller (a UI action) shows an error. The in-memory value is **rolled back** so memory and disk stay the same.

**`set`**:
```python
def set(self, key, value) -> bool:
    k = REGISTRY[key]                       # KeyError for unknown keys
    if not _type_ok(value, k.type) or (k.validate and not k.validate(value)):
        raise ValueError(f"invalid value for {key}: {value!r}")
    with self._lock:
        if self.get(key) == value:
            return False
        old = self._values.get(key, _MISSING)
        self._values[key] = copy.deepcopy(value)
        try:
            self._save()
        except OSError:
            if old is _MISSING: self._values.pop(key, None)
            else: self._values[key] = old
            raise
    self._notify(key, value)                # outside the lock
    return True
```
Notify **outside** the lock, so a callback that calls `get()` or `set()` doesn't deadlock. (It's an `RLock` anyway, but keep the rule.)

**`_notify`**: loop over a *copy* of the observers. Wrap each call in try/except and `log.exception`.

### Step 4 — Migrations

```python
CURRENT_SCHEMA = 1
def _migrate_0_to_1(d: dict) -> dict:
    # Files without schema_version are v0; nothing to change yet.
    return d
MIGRATIONS = {0: _migrate_0_to_1}   # from_version -> fn

def migrate(d: dict) -> dict:
    v = d.get("schema_version", 0) if isinstance(d.get("schema_version"), int) else 0
    while v < CURRENT_SCHEMA:
        d = MIGRATIONS[v](dict(d)); v += 1
        d["schema_version"] = v
    return d
```
A file from the **future** (`schema_version > CURRENT`) is loaded as it is, with a WARNING, and unknown keys are kept. Don't downgrade it.

### Step 5 — Wire it into the app

In `CalpiApp._on_activate` (before the screens are built):
```python
from calpi.data.settings_store import SettingsStore
self.settings = SettingsStore()
log.info("settings loaded from %s", self.settings.path)
```
Screens get to it through `self.get_root().get_application().settings`, or (cleaner) through their constructor arguments: pass `settings` into the screens that need it. **Prefer passing it in the constructor**; it makes the dependencies obvious.

### Step 6 — Tests (`tests/test_atomic.py`, `tests/test_settings_store.py`)

Atomic writes and simulated power cuts: monkeypatch `os.replace` or `os.fsync` to raise at each step (the first replace, the second replace, the directory fsync), and after each simulated crash make a **new** `SettingsStore` on the same directory:
- A crash before the first replace → the old value.
- A crash between the replaces → `settings.json` is missing, `.bak` holds the old value → the old value is loaded, with a warning logged.
- A crash after the second replace → the new value.
- A leftover `.tmp` doesn't confuse loading.

Recovery:
- `settings.json` contains `{not json` → the `.bak` is used, a `.corrupt-*` file is created, and ERROR is logged (`caplog`).
- Both are corrupt → defaults, no exception.
- Four corruptions in a row → only 3 `.corrupt-*` files are kept.
- The top level is a list → treated as corrupt.

Types and validation:
- `set(K_SETUP_COMPLETED, 1)` → `ValueError` (an int isn't a bool). Register a test key of type int, and `set(int_key, True)` → `ValueError`.
- Invalid value on disk → the default, with a warning. After any `set`, the file holds only valid values.
- Unknown keys are kept through a `set` of another key.

Observers:
- A callback runs once with `(key, value)`. Setting the same value again → no call, and no write (check the file's mtime, or monkeypatch `atomic_write_json` to count calls).
- A failing callback doesn't block a second callback.
- `unsubscribe` works.
- `update()` with 3 keys → 1 write, 3 notifications. With one of them invalid → `ValueError`, nothing changed.

Isolation of copies: `get()` of a dict, change it, `get()` again → unchanged.

Migration: write a file without `schema_version` → loaded, and saved with `schema_version: 1`.

### Step 7 — Check on the Pi (needs US-03)

1. Deploy. Add a temporary DEBUG hook (for example a `CALPI_DEBUG_SETTINGS=1` environment variable that makes the app flip a harmless test key every 2 seconds). **Or, simpler:** run a small script on the Pi as `kiosk` that loops `set(K_SETUP_COMPLETED, not current)` as fast as it can, and trigger `echo b | sudo tee /proc/sysrq-trigger` while it runs. (**Ask the owner before forcing a reboot.**)
2. After the reboot: the file loads (both values are acceptable), and there's no `.corrupt-*` file.
3. Repeat 3 times. Record the results. Remove any temporary hook.

If US-03 isn't done, leave this to US-12, which has a wider power-cut test, and say so.

---

## Files

| File | Change |
|---|---|
| `calpi/data/atomic.py` | New |
| `calpi/data/settings_store.py` | New |
| `calpi/app.py` | Creates `self.settings` |
| `tests/test_atomic.py`, `tests/test_settings_store.py` | New |

---

## Pitfalls

- **`bool` is an `int`.** Check for bool first.
- **Storing defaults in the file.** Then you can never change a default in a later release. Store only explicit values.
- **Notifying before the write succeeded.** Observers would react to a value that isn't on disk.
- **Forgetting the directory `fsync`.** On ext4 the rename might not survive a power cut without it.
- **Using `json.dump` straight to the final path.** That isn't atomic. Always go through `atomic_write_json`.
- **Putting secrets in settings.** Account passwords go in the credential store (US-13). The account records here hold only non-secret fields.
- **Letting observers update widgets from a worker thread.** Call `set` only on the main thread.

---

## Definition of done

- [ ] All acceptance criteria met. The simulated power-cut tests pass.
- [ ] No gi imports (`test_no_gi.py` from US-04 covers `calpi.data`. If US-04 isn't done yet, add the same subprocess check for this module).
- [ ] The app starts with a corrupt `settings.json` (a manual check in the devcontainer: write garbage to `.devstate/settings.json`, run `scripts/smoke.sh`, or dev-run with `CALPI_STATE_DIR=.devstate`).
- [ ] The Pi power-cut check done, or explicitly handed to US-12.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `SettingsStore.get/set/update/reset/subscribe/unsubscribe/snapshot` | US-08, US-16, US-22 onwards, US-28, US-29, US-30, US-32, US-39, US-41 |
| New keys are registered in `settings_store.py` with `register(Key(...))`, and the name constant `K_*` sits next to it | every story that adds a setting |
| `app.settings` (created in `CalpiApp._on_activate`), passed into screens through their constructors | all UI stories |
| `calpi.data.atomic.atomic_write_bytes/atomic_write_json` | US-13 (credentials), US-41 (weather cache) |
| `settings.json` is written only by the UI process. The sync process reads it at start-up | US-16 |
| Rapidly changing controls commit only on release or after a debounce (D5) | US-29, US-30 |
