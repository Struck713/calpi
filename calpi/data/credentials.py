"""Encrypted credential store. No gi imports (the sync process uses it too).

Threat model (details in docs/security.md):
  * Protected: reading a copied/lost SD card or disk image on another machine; accidental exposure
    via settings.json, logs, repr() or command lines.
  * NOT protected: an attacker with root or physical access to the running Pi (the key file and the
    hardware serial are both readable there). No TPM/secure element/login password exists on a Pi 3B.
  * Key = HKDF-SHA256(ikm=<state>/keys/credentials.key, salt=sha256(hardware serial)).
    File = b"CPC1" + nonce(12) + AES-256-GCM(json {"v":1,"secrets":{id: secret}}).
  * Python strings cannot be wiped from memory; secrets live in RAM while in use.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from calpi import paths
from calpi.data.atomic import atomic_write_bytes

log = logging.getLogger("calpi.credentials")

MAGIC = b"CPC1"
_INFO = b"calpi-credentials-v1"


class SecretRedactor(logging.Filter):
    """Replaces registered secret values in log messages (and formatted tracebacks) with ***."""

    def __init__(self) -> None:
        super().__init__()
        self._values: set[str] = set()

    def register(self, v: str) -> None:
        if len(v) >= 6:                       # don't redact trivially short strings
            self._values.add(v)

    def redact(self, text: str) -> str:
        for v in list(self._values):
            if v in text:
                text = text.replace(v, "***")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._values:
            return True
        msg = record.getMessage()
        red = self.redact(msg)
        if red != msg:
            record.msg, record.args = red, ()
        return True


_REDACTOR = SecretRedactor()


class RedactingFormatter(logging.Formatter):
    """Also redacts tracebacks, which handlers format after filters have run."""

    def format(self, record: logging.LogRecord) -> str:
        return _REDACTOR.redact(super().format(record))


def install_log_redaction() -> None:
    for h in logging.getLogger().handlers:
        if _REDACTOR not in h.filters:
            h.addFilter(_REDACTOR)


class Secret:
    __slots__ = ("_v",)
    __hash__ = None  # type: ignore[assignment]

    def __init__(self, value: str):
        if not isinstance(value, str) or not value:
            raise ValueError("secret must be a non-empty str")
        self._v = value
        _REDACTOR.register(value)

    def reveal(self) -> str:
        return self._v

    def __repr__(self) -> str:
        return "Secret('***')"

    __str__ = __repr__

    def __eq__(self, other) -> bool:
        return isinstance(other, Secret) and other._v == self._v

    def __reduce__(self):
        raise TypeError("Secret cannot be pickled")


_warned_no_serial = False


def hardware_serial() -> tuple[str, str]:
    """(serial, source). Never raises."""
    global _warned_no_serial
    try:
        raw = (Path("/sys/firmware/devicetree/base/serial-number").read_bytes()
               .rstrip(b"\x00").decode().strip())
        if raw:
            return raw.lower()[-16:], "devicetree"
    except (OSError, UnicodeDecodeError):
        pass
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("serial"):
                v = line.split(":", 1)[1].strip().lower()
                if v and set(v) != {"0"}:
                    return v[-16:], "cpuinfo"
    except (OSError, UnicodeDecodeError):
        pass
    if not _warned_no_serial:
        _warned_no_serial = True
        log.warning("credentials: no hardware serial; secrets are bound to machine-id only (dev?)")
    try:
        return Path("/etc/machine-id").read_text().strip(), "machine-id"
    except OSError:
        return "no-serial", "none"


def derive_key(keyfile_bytes: bytes, serial: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32,
                salt=hashlib.sha256(serial.encode()).digest(),
                info=_INFO).derive(keyfile_bytes)


class _Unreadable(Exception):
    pass


class CredentialStore:
    def __init__(self, directory: Path | None = None, serial_fn=hardware_serial):
        self._dir = Path(directory) if directory else paths.state_dir()
        self._file = self._dir / "credentials.bin"
        self._keyfile = self._dir / "keys" / "credentials.key"
        self._serial_fn = serial_fn
        self._lock = threading.RLock()
        self._cache: dict[str, str] | None = None
        self._sig: tuple | None = None
        self._status = "unknown"           # "empty" | "ok" | "unreadable"
        self._logged_unreadable = False

    # -- public API ---------------------------------------------------------------------------
    def status(self) -> str:
        with self._lock:
            self._load()
            return self._status

    def ids(self) -> list[str]:
        with self._lock:
            return sorted(self._load())

    def get(self, account_id: str) -> Secret | None:
        with self._lock:
            v = self._load().get(account_id)
        return Secret(v) if v is not None else None

    def set(self, account_id: str, secret: Secret) -> None:
        if not isinstance(secret, Secret):
            raise TypeError("secret must be a Secret")
        with self._lock:
            data = dict(self._load())
            if self._status == "unreadable":
                self._move_aside()
                data = {}
            data[account_id] = secret.reveal()
            self._save(data)

    def delete(self, account_id: str) -> None:
        with self._lock:
            data = dict(self._load())
            if self._status == "unreadable" or account_id not in data:
                return
            del data[account_id]
            self._save(data)

    # -- internals ----------------------------------------------------------------------------
    def _file_sig(self):
        try:
            st = self._file.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _key(self, create: bool) -> bytes:
        if not self._keyfile.exists():
            if not create:
                raise _Unreadable("key file missing")
            self._keyfile.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self._keyfile.parent, 0o700)
            if not self._keyfile.exists():
                atomic_write_bytes(self._keyfile, os.urandom(32), mode=0o600)
        raw = self._keyfile.read_bytes()
        if len(raw) != 32:
            raise _Unreadable("key file has wrong length")
        return derive_key(raw, self._serial_fn()[0])

    def _mark_unreadable(self) -> dict:
        self._status = "unreadable"
        if not self._logged_unreadable:
            self._logged_unreadable = True
            log.error("credentials: cannot decrypt (moved SD card or hardware change?); "
                      "accounts need signing in again")
        return {}

    def _load(self) -> dict[str, str]:
        sig = self._file_sig()
        if self._cache is not None and sig == self._sig:
            return self._cache
        self._sig = sig
        if sig is None:
            self._status = "empty"
            self._cache = {}
            return self._cache
        try:
            blob = self._file.read_bytes()
            if len(blob) < len(MAGIC) + 12 + 16 or blob[:4] != MAGIC:
                raise _Unreadable("bad header")
            key = self._key(create=False)
            plain = AESGCM(key).decrypt(blob[4:16], blob[16:], MAGIC)
            obj = json.loads(plain)
            if obj.get("v") != 1 or not isinstance(obj.get("secrets"), dict):
                raise _Unreadable("unknown version")
            secrets = {str(k): str(v) for k, v in obj["secrets"].items()}
        except Exception:
            self._cache = self._mark_unreadable()
            return self._cache
        self._status = "ok"
        self._cache = secrets
        return secrets

    def _save(self, data: dict[str, str]) -> None:
        key = self._key(create=True)
        nonce = os.urandom(12)
        plain = json.dumps({"v": 1, "secrets": data}).encode()
        ct = AESGCM(key).encrypt(nonce, plain, MAGIC)
        atomic_write_bytes(self._file, MAGIC + nonce + ct, mode=0o600)
        self._cache = dict(data)
        self._sig = self._file_sig()
        self._status = "ok"
        self._logged_unreadable = False

    def _move_aside(self) -> None:
        dest = self._file.with_name(f"credentials.bin.unreadable-{int(time.time())}")
        try:
            os.replace(self._file, dest)
            log.warning("credentials: moved unreadable store to %s", dest.name)
        except OSError:
            pass
