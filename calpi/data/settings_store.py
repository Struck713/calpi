"""Typed, validated, observable settings persisted as JSON. No gi imports.

Only the UI process writes; the sync process reads the file at start-up.
Call `set` from the main thread only (observers run on the calling thread).

Planned keys (each story registers its own with register(Key(...)) below and a K_* constant):
  wizard_step (US-32), inactivity_return_seconds (US-08), accounts (US-14),
  sync_interval_minutes (US-16), sync_window_months_back/_forward (US-15),
  timezone / week_start / time_format (US-28), brightness (US-29), dim_schedule (US-30),
  default_view (US-39/40), weather (US-41), dismissed_problems (US-38), touch_device_names (US-34).
"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from calpi import paths
from calpi.data.atomic import atomic_write_json

log = logging.getLogger("calpi.settings")

_MISSING = object()


@dataclass(frozen=True)
class Key:
    name: str
    type: Any                      # type or tuple of types (may include type(None))
    default: Any
    validate: Callable[[Any], bool] | None = None


K_SCHEMA_VERSION = "schema_version"
K_SETUP_COMPLETED = "setup_completed"
K_INACTIVITY_RETURN_SECONDS = "inactivity_return_seconds"

REGISTRY: dict[str, Key] = {}


def register(key: Key) -> Key:
    if key.name in REGISTRY:
        raise ValueError(f"duplicate key {key.name}")
    REGISTRY[key.name] = key
    return key


register(Key(K_SCHEMA_VERSION, int, 1))
register(Key(K_SETUP_COMPLETED, bool, False))
register(Key(K_INACTIVITY_RETURN_SECONDS, int, 120, lambda v: 30 <= v <= 3600))
K_ACCOUNTS = "accounts"
_ACCOUNT_KEYS = {"id", "provider", "username", "display_name", "server_url",
                 "principal_url", "calendar_home_url", "created_at"}


def _valid_accounts(v) -> bool:
    return all(isinstance(a, dict) and _ACCOUNT_KEYS <= set(a) for a in v)


register(Key(K_ACCOUNTS, list, [], _valid_accounts))    # US-14: account records, no secrets
# Later stories append here.


def _type_ok(value: Any, typ: Any) -> bool:
    types = typ if isinstance(typ, tuple) else (typ,)
    if isinstance(value, bool):
        return bool in types
    if value is None:
        return type(None) in types
    return isinstance(value, types)


def _valid(k: Key, value: Any) -> bool:
    if not _type_ok(value, k.type):
        return False
    if k.validate is None:
        return True
    try:
        return bool(k.validate(value))
    except Exception:
        return False


CURRENT_SCHEMA = 1


def _migrate_0_to_1(d: dict) -> dict:
    return d      # files without schema_version are v0; nothing to change yet


MIGRATIONS: dict[int, Callable[[dict], dict]] = {0: _migrate_0_to_1}


def migrate(d: dict) -> dict:
    sv = d.get("schema_version")
    v = sv if isinstance(sv, int) and not isinstance(sv, bool) else 0
    if v > CURRENT_SCHEMA:
        log.warning("settings file schema_version %s is newer than %s; loading as is", v, CURRENT_SCHEMA)
        return d
    while v < CURRENT_SCHEMA:
        d = MIGRATIONS[v](dict(d))
        v += 1
        d["schema_version"] = v
    return d


class SettingsStore:
    FILE = "settings.json"
    KEEP_CORRUPT = 3

    def __init__(self, directory: Path | str | None = None):
        self._dir = Path(directory) if directory else paths.state_dir()
        self._path = self._dir / self.FILE
        self._lock = threading.RLock()
        self._values: dict[str, Any] = {}
        self._unknown: dict[str, Any] = {}
        self._observers: dict[int, tuple[str, Callable]] = {}
        self._next_token = 1
        self._file_version = CURRENT_SCHEMA
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    # ---- loading -------------------------------------------------------
    def _read_dict(self, path: Path) -> dict | None:
        """Parsed dict, or None if missing/corrupt (corrupt files are renamed aside)."""
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            log.exception("cannot read %s", path)
            return None
        try:
            obj = json.loads(raw.decode("utf-8"))
            if not isinstance(obj, dict):
                raise ValueError("top level is not an object")
            return obj
        except (ValueError, UnicodeDecodeError) as e:
            log.error("settings file %s is corrupt (%s)", path, e)
            try:
                os.replace(path, path.with_name(f"{path.name}.corrupt-{int(time.time())}"))
            except OSError:
                log.exception("cannot move corrupt file aside")
            return None

    def _load(self) -> None:
        raw = self._read_dict(self._path)
        if raw is None:
            raw = self._read_dict(self._path.with_name(self.FILE + ".bak"))
            if raw is not None:
                log.warning("restored settings from backup")
        if raw is None:
            raw = {}
        raw = migrate(raw)
        sv = raw.get(K_SCHEMA_VERSION)
        self._file_version = max(CURRENT_SCHEMA, sv) if isinstance(sv, int) and not isinstance(sv, bool) else CURRENT_SCHEMA
        for name, value in raw.items():
            k = REGISTRY.get(name)
            if k is None:
                self._unknown[name] = value
            elif name == K_SCHEMA_VERSION:
                continue
            elif _valid(k, value):
                self._values[name] = value
            else:
                log.warning("invalid stored value for %s: %r; using default", name, value)
        if self._unknown:
            log.info("keeping unknown settings keys: %s", sorted(self._unknown))
        self._prune_corrupt()

    def _prune_corrupt(self) -> None:
        try:
            files = sorted(self._dir.glob(self.FILE + ".corrupt-*"),
                           key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
            for p in files[self.KEEP_CORRUPT:]:
                p.unlink()
        except OSError:
            log.exception("cannot prune corrupt settings files")

    # ---- saving --------------------------------------------------------
    def _save(self) -> None:
        data = {**self._unknown, **self._values, K_SCHEMA_VERSION: self._file_version}
        try:
            atomic_write_json(self._path, data, keep_backup=True)
        except OSError:
            log.error("cannot save settings to %s", self._path, exc_info=True)
            raise

    # ---- API -----------------------------------------------------------
    def get(self, key: str):
        k = REGISTRY[key]
        with self._lock:
            if key == K_SCHEMA_VERSION:
                return CURRENT_SCHEMA
            return copy.deepcopy(self._values.get(key, k.default))

    def set(self, key: str, value) -> bool:
        return bool(self.update({key: value}))

    def update(self, changes: dict[str, Any]) -> list[str]:
        for key, value in changes.items():
            k = REGISTRY[key]            # KeyError for unknown keys
            if not _valid(k, value):
                raise ValueError(f"invalid value for {key}: {value!r}")
        with self._lock:
            changed = [key for key, v in changes.items() if self.get(key) != v]
            if not changed:
                return []
            old = {key: self._values.get(key, _MISSING) for key in changed}
            for key in changed:
                self._values[key] = copy.deepcopy(changes[key])
            try:
                self._save()
            except OSError:
                for key, o in old.items():
                    if o is _MISSING:
                        self._values.pop(key, None)
                    else:
                        self._values[key] = o
                raise
        for key in changed:
            self._notify(key, changes[key])
        return changed

    def reset(self, key: str) -> bool:
        return self.set(key, REGISTRY[key].default)

    def subscribe(self, key: str, cb: Callable[[str, Any], None]) -> int:
        if key not in REGISTRY:
            raise KeyError(key)
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._observers[token] = (key, cb)
        return token

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._observers.pop(token, None)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {name: self.get(name) for name in REGISTRY}

    def _notify(self, key: str, value: Any) -> None:
        with self._lock:
            observers = list(self._observers.values())
        for name, cb in observers:
            if name != key:
                continue
            try:
                cb(key, copy.deepcopy(value))
            except Exception:
                log.exception("settings observer for %s failed", key)
