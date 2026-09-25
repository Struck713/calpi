# US-13 — Secure credential storage

| | |
|---|---|
| **Epic** | 2. Calendar Syncing |
| **Priority** | P0 |
| **Blocked by** | US-05 Settings store |
| **Blocks** | US-14 iCloud account connection |
| **Phase** | 2. Syncing |

## Story

> As a user, I want my account sign-in details stored securely on the device, never in plain text.

## Context

To read iCloud calendars, the device needs the Apple ID and an **app-specific password** (US-14). The password gives read access to the owner's calendars, and on iCloud also to contacts and more, until it's revoked. It has to be stored so that:
- it is **never in plain text** on the SD card, in settings, in logs, in crash dumps, or in the process list;
- **copying or stealing the SD card** isn't enough to use it on another machine;
- the app (running as the unprivileged `kiosk` user, with **no login password** and **no desktop keyring**) can still read it at every boot **without anyone typing anything**.

Those goals pull against each other. Be honest about what's possible on a Pi 3B:
- There's **no TPM or secure element**, and no user password to unlock a keyring. A desktop keyring (libsecret/GNOME Keyring) would have to be unlocked with a password at every boot, which a kiosk can't do. So **libsecret is ruled out**.
- **What we can do**: encrypt with AES-256-GCM, using a key derived from (a) a random key file stored separately with strict permissions, and (b) **the Pi's hardware serial number**, which comes from the SoC and is **not stored on the SD card**. The result: an attacker with *only the SD card* (a lost or copied card, a backup image) can't decrypt the secrets without also knowing the serial of this particular Pi. An attacker with *root on the running device* can read everything. That's accepted and documented, because nothing can prevent it on this hardware.
- Secrets never appear in `settings.json`, logs, `repr()`, exception messages, or command-line arguments.

The store is **pure Python (no gi)**, because the sync process (US-16) reads it too. It reuses `calpi/data/atomic.py` from **US-05**, which is why this story is blocked by US-05.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-05** Settings store | `calpi/data/atomic.py` (`atomic_write_bytes` with `mode=`), the patterns for crash-safe files, `paths.state_dir()` (from US-02) | `grep -n "def atomic_write_bytes" calpi/data/atomic.py`. `/usr/bin/python3 -m pytest tests/test_atomic.py` passes. |

### External blockers

| Blocker | What to do |
|---|---|
| **The `cryptography` library from apt** (`python3-cryptography`) on the Pi and in the devcontainer | Check: `apt-cache policy python3-cryptography` (it's in Debian Bookworm and Trixie). Add it to `deps/apt-runtime.txt`, and install it with `scripts/pi deps` (US-03). **Don't write your own crypto**, and don't use a pure-Python AES. If the package really isn't available, stop and report it. |
| **The Pi's serial number is readable by `kiosk`** | Check: `ssh calpi 'sudo -u kiosk cat /sys/firmware/devicetree/base/serial-number; echo; grep Serial /proc/cpuinfo'`. Both should print a 16-hex-digit serial. Record which one works in `docs/platform-versions.md`. In the devcontainer there's no serial, so the fallback is used (D4). |

### Soft dependencies
- **US-03** for installing the package and checking on the Pi.
- **US-12** (the crash-loop and corruption handling ideas): a credentials file that can't be decrypted must never crash the app (acceptance criterion 7).

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| You're tempted to use libsecret, the kernel keyring, or systemd-creds | They're ruled out (see Context). systemd-creds needs root to encrypt new secrets, and accounts are added at runtime by the `kiosk` user. The kernel keyring (`keyctl`) doesn't survive a reboot. **The design is decided.** |
| The serial reads differently in different places (`/proc/cpuinfo` has a leading `0000`) | Normalise: lowercase, strip, and take the last 16 hex digits. Test both sources on the Pi and make sure they give the same value. |
| The devcontainer's `python3` can't import `cryptography` | Use `/usr/bin/python3` (the apt Python), as always. |

---

## Scope

### In scope
- `calpi/data/credentials.py`: `CredentialStore` (get/set/delete a secret per account id, list ids).
- Key file generation, key derivation (HKDF-SHA256 over key file + hardware serial), AES-256-GCM, the file format with a version.
- A `Secret` wrapper type that never shows its value in `repr`/`str`.
- A redacting logging filter (defence in depth).
- Handling files that can't be decrypted (a moved SD card, a changed serial, corruption).
- The threat model, written in the module docstring and in `docs/security.md`.

### Out of scope
- Account records (non-secret: provider, username, server URLs) go in **settings** (US-14).
- The UI for entering passwords (US-25 / US-21).
- Wi-Fi passwords: NetworkManager stores those itself (US-23).

---

## Acceptance criteria

1. `CredentialStore.set(account_id, secret)` stores the secret encrypted in `<state>/credentials.bin` (mode 0600). `get(account_id)` returns it. `delete(account_id)` removes it. `ids()` lists the stored account ids. Changes are atomic (through `atomic_write_bytes`).
2. The file contains **no plain text**: after storing the secret `"abcd-efgh-ijkl-mnop"`, `grep -c abcd <state>/credentials.bin` → 0, and the same for the account id if it's sensitive (the whole mapping is encrypted, not only the values).
3. The key file `<state>/keys/credentials.key` holds 32 random bytes (`os.urandom`), mode 0600, in a directory with mode 0700. It's created on first use, and **never** overwritten if it exists.
4. The encryption key is `HKDF-SHA256(ikm = keyfile_bytes, salt = sha256(hardware_serial), info = b"calpi-credentials-v1")`. **Copying the whole state directory to another Pi (or to the devcontainer) makes `get()` fail cleanly** (acceptance criterion 7), and a test shows it by changing the serial.
5. The file format is versioned: `b"CPC1" + nonce(12) + ciphertext_with_tag`. Every write uses a **new random nonce**. The plain text is JSON: `{"v": 1, "secrets": {account_id: secret}}`. Tampering with any byte makes decryption fail (the GCM tag), and it's reported as "unreadable", not as a crash.
6. `Secret` objects: `repr(Secret("x"))` → `Secret('***')`, and `str()` is the same. The value is only available through `.reveal()`. `CredentialStore.get()` returns a `Secret`.
7. **An unreadable store** (wrong key, corrupt, or unknown version): `get()` returns `None` for everything, `status()` returns `"unreadable"`, one ERROR is logged (`credentials: cannot decrypt (moved SD card or hardware change?); accounts need signing in again`), and **the app keeps running**. `set()` on an unreadable store **moves the old file to `credentials.bin.unreadable-<ts>`** and starts a fresh store (so the user can sign in again without SSH).
8. A logging filter installed at app startup (and in the sync process) replaces any registered secret value that appears in a log message with `***`. A test shows that logging an f-string containing the secret prints `***`.
9. Secrets are never passed as command-line arguments to any subprocess anywhere in the code base (a code review check: `grep -rn "reveal()" calpi/` → each use is reviewed and listed in the hand-off notes).
10. `docs/security.md` describes the threat model: what's protected, what isn't, and how to revoke (the Apple ID page).
11. Pure Python with no gi, and the `test_no_gi` check covers this module.

---

## Design decisions (already made)

- **D1. `cryptography`'s `AESGCM`** (AES-256-GCM) and `HKDF` from `cryptography.hazmat.primitives.kdf.hkdf`. No custom crypto.
- **D2. One encrypted file for all secrets**, rewritten on every change. There are only a few accounts, so it's tiny. Encrypting the whole mapping hides which account ids exist.
- **D3. Separate key file, in its own directory** (`<state>/keys/`, 0700). It isn't *more* secure on the same card, but it keeps the key out of backups of the main state and makes it easy to rotate or delete.
- **D4. Hardware binding**: the serial from `/sys/firmware/devicetree/base/serial-number` (NUL-terminated: strip `\x00`), falling back to the `Serial` line in `/proc/cpuinfo`. If neither exists (the devcontainer), use `/etc/machine-id` and log **one** WARNING (`credentials: no hardware serial; secrets are bound to machine-id only (dev?)`). The serial is **not secret** (anyone holding the Pi can read it). It's there to stop *SD-card-only* attacks, not attackers who have the device.
- **D5. `Secret`** is a small class with `__slots__ = ("_v",)`, `reveal()`, a masked `__repr__`/`__str__`, `__eq__` for tests, and **no `__hash__`** (so it can't be put into sets or logged as a key by accident). Python strings can't be wiped from memory, so accept that and say it in the docs.
- **D6. Redacting filter**: `SecretRedactor(logging.Filter)` holds a set of revealed values (added by `CredentialStore.get()`/`set()`), and replaces them in `record.getMessage()`. It's installed on the root logger's handlers. Cost: one substring check per registered secret per log record, which is negligible.
- **D7. Unreadable ≠ empty.** The app must tell "no credentials stored" (a fresh device) apart from "credentials exist but can't be read" (a moved card), because the messages to the user differ (US-38: "Sign in again" versus nothing).

---

## Implementation plan

### Step 1 — Dependencies

Add `python3-cryptography` to `deps/apt-runtime.txt`. Install it in the devcontainer (`sudo apt-get install -y python3-cryptography`), and check with `/usr/bin/python3 -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; print('ok')"`. On the Pi: `scripts/pi deps`.

### Step 2 — `Secret` and the redactor

```python
class Secret:
    __slots__ = ("_v",)
    __hash__ = None
    def __init__(self, value: str):
        if not isinstance(value, str) or not value:
            raise ValueError("secret must be a non-empty str")
        self._v = value
        _REDACTOR.register(value)
    def reveal(self) -> str: return self._v
    def __repr__(self): return "Secret('***')"
    __str__ = __repr__
    def __eq__(self, other): return isinstance(other, Secret) and other._v == self._v
    def __reduce__(self): raise TypeError("Secret cannot be pickled")

class SecretRedactor(logging.Filter):
    def __init__(self): super().__init__(); self._values: set[str] = set()
    def register(self, v: str):
        if len(v) >= 6: self._values.add(v)        # don't redact trivially short strings
    def filter(self, record: logging.LogRecord) -> bool:
        if not self._values: return True
        msg = record.getMessage()
        red = msg
        for v in self._values:
            if v in red: red = red.replace(v, "***")
        if red is not msg and red != msg:
            record.msg, record.args = red, ()
        return True

_REDACTOR = SecretRedactor()
def install_log_redaction() -> None:
    for h in logging.getLogger().handlers:
        h.addFilter(_REDACTOR)
```
Call `install_log_redaction()` right after `setup_logging()` in the app (`calpi/app.py main()`) and in the sync worker (US-16). Note: tracebacks (`exc_info`) are formatted by the handler **after** the filter runs. To cover them too, subclass `logging.Formatter` and apply the same replacement in `format()`. Install that formatter in `setup_logging()`. **Do both**, and test both.

### Step 3 — Hardware serial and key derivation

```python
def hardware_serial() -> tuple[str, str]:
    """(serial, source). Never raises."""
    try:
        raw = Path("/sys/firmware/devicetree/base/serial-number").read_bytes().rstrip(b"\x00").decode().strip()
        if raw: return raw.lower()[-16:], "devicetree"
    except OSError: pass
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("serial"):
                v = line.split(":", 1)[1].strip().lower()
                if v and set(v) != {"0"}: return v[-16:], "cpuinfo"
    except OSError: pass
    try:
        return Path("/etc/machine-id").read_text().strip(), "machine-id"
    except OSError:
        return "no-serial", "none"

def derive_key(keyfile_bytes: bytes, serial: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32,
                salt=hashlib.sha256(serial.encode()).digest(),
                info=b"calpi-credentials-v1").derive(keyfile_bytes)
```
Make `hardware_serial` injectable in `CredentialStore.__init__(serial_fn=hardware_serial)` for the tests.

### Step 4 — `CredentialStore`

```python
MAGIC = b"CPC1"

class CredentialStore:
    def __init__(self, directory: Path | None = None, serial_fn=hardware_serial):
        self._dir = Path(directory) if directory else paths.state_dir()
        self._file = self._dir / "credentials.bin"
        self._keyfile = self._dir / "keys" / "credentials.key"
        self._serial_fn = serial_fn
        self._lock = threading.Lock()
        self._cache: dict[str, str] | None = None
        self._status = "unknown"     # "empty" | "ok" | "unreadable"

    def status(self) -> str: self._load(); return self._status
    def ids(self) -> list[str]: return sorted(self._load().keys())
    def get(self, account_id: str) -> Secret | None:
        v = self._load().get(account_id)
        return Secret(v) if v is not None else None
    def set(self, account_id: str, secret: Secret) -> None: ...
    def delete(self, account_id: str) -> None: ...
```
Details:
- `_key()`: create `keys/` with 0700 if it's missing. If there's no key file, `atomic_write_bytes(keyfile, os.urandom(32), mode=0o600)`. Read it and check it's 32 bytes (**if it isn't, treat the store as unreadable, and never overwrite the key file automatically**). Derive the key with the serial.
- `_load()`: returns the cached dict. If the file is missing → `{}`, status `empty`. Otherwise check the MAGIC, split the nonce and ciphertext, `AESGCM(key).decrypt(nonce, ct, MAGIC)` (use the MAGIC as associated data), `json.loads`, check `v == 1`. On **any** failure → status `unreadable`, log ERROR once, return `{}`.
- `_save(d)`: `nonce = os.urandom(12)`, `ct = AESGCM(key).encrypt(nonce, json.dumps({"v":1,"secrets":d}).encode(), MAGIC)`, then `atomic_write_bytes(self._file, MAGIC + nonce + ct, mode=0o600)`. Update the cache and set the status to `ok`.
- `set()` when the status is `unreadable`: move the file aside (`credentials.bin.unreadable-<ts>`), log a WARNING, start again from `{}`. **Keep the key file.** If the reason was a changed serial, the same key file combined with the new serial works from now on.
- The **cache**: the sync process is short-lived, so caching in memory is fine. The UI process caches too. The UI is the only writer (US-25). The sync process only reads. **Re-read the file if its mtime changed** since the cache was filled (cheap, and it keeps a long-running UI process correct if the file was changed elsewhere, for example by a recovery tool).

### Step 5 — Hook it into startup

In `calpi/app.py`:
```python
from calpi.data.credentials import CredentialStore, install_log_redaction
install_log_redaction()       # right after setup_logging()
...
self.credentials = CredentialStore()
st = self.credentials.status()
log.info("credentials: %s (%d stored)", st, len(self.credentials.ids()) if st == "ok" else 0)
if st == "unreadable":
    self.startup_notices.append("credentials_unreadable")   # US-12 list; US-38 shows it
```
(If `startup_notices` doesn't exist yet because US-12 isn't done, create the list here.)

### Step 6 — `docs/security.md`

Write the threat model, in plain language:
- What's stored, and where.
- Protected against: reading the SD card or a disk image on another computer; accidental exposure through logs, settings, screenshots, or the process list.
- **Not** protected against: someone with root or physical access to the running device (they can read the serial and the key file). That's unavoidable without secure hardware.
- What to do if the device is lost: revoke the app-specific password at `account.apple.com` → Sign-In and Security → App-Specific Passwords.
- Moving the SD card to another Pi means signing in again.

### Step 7 — Tests (`tests/test_credentials.py`)

- Round trip set/get/delete/ids with `tmp_path` and a fixed `serial_fn`.
- No plain text: the bytes of the file don't contain the secret or the account id.
- File and key permissions are 0600, and the `keys/` directory is 0700.
- New nonce per write: two writes of the same content give different files.
- **A different serial** → `status() == "unreadable"`, `get()` → None, one ERROR logged, no exception. Then `set()` → the old file is moved aside, and the new store works with the new serial.
- Tampering: flip one byte in the ciphertext → unreadable. Wrong magic → unreadable. Truncated → unreadable.
- A key file with the wrong length → unreadable, and the key file is **not** overwritten.
- `Secret`: repr/str masked; `hash()` raises `TypeError`; pickling raises.
- Redaction: register a secret, log `f"password is {secret.reveal()}"` → the captured output has `***`. Log with `exc_info` of an exception whose message contains the secret → `***` in the formatted traceback too.
- `hardware_serial` parsing: monkeypatch the file reads to return the devicetree bytes with a trailing NUL, and a cpuinfo `Serial : 00000000abcdef12`, and check the normalised value is the same.

### Step 8 — Pi check (US-03)

```bash
scripts/pi deps && scripts/pi deploy
scripts/pi ssh 'cd /opt/calpi && sudo -u kiosk env STATE_DIRECTORY=/var/lib/calpi /usr/bin/python3 -c "
from calpi.data.credentials import CredentialStore, Secret, hardware_serial
print(hardware_serial()[1])
s=CredentialStore(); s.set(\"test\", Secret(\"not-a-real-password-123\")); print(s.get(\"test\"), s.status())
s.delete(\"test\")"'
scripts/pi ssh 'sudo ls -la /var/lib/calpi /var/lib/calpi/keys'
```
Expect the source `devicetree` or `cpuinfo`, `Secret('***') ok`, and 0600/0700 permissions. **Don't** leave test secrets behind: `delete` it, and check `ids()` is empty.

---

## Files

| File | Change |
|---|---|
| `calpi/data/credentials.py` | New |
| `calpi/logging_setup.py` | A redacting formatter |
| `calpi/app.py` | `install_log_redaction()`, `self.credentials`, the startup notice |
| `deps/apt-runtime.txt` | `python3-cryptography` |
| `docs/security.md` | New |
| `tests/test_credentials.py` | New |

---

## Pitfalls

- **Reusing a nonce** with AES-GCM breaks its security. Always use `os.urandom(12)` per write.
- **Overwriting the key file** when decryption fails. That destroys any chance of recovery.
- **Treating an unreadable store as empty**: the UI would say "no accounts" instead of "sign in again".
- **Logging `Secret.reveal()`**, or putting it in exceptions (`raise ValueError(f"bad password {pw}")`). The redactor is a safety net, not permission to do it.
- **Passing the secret as a subprocess argument** (it shows in `ps`). HTTP Basic auth (US-14) puts it in a request header in-process, which is fine.
- **A `Secret` in a dataclass `repr`**: fine, because it masks itself. **Never** use `dataclasses.asdict()` then `json.dumps` on account objects that hold a `Secret`. Keep secrets out of account dataclasses entirely (US-14 keeps them separate).

---

## Definition of done

- [ ] All acceptance criteria met, and every test in step 7 passes.
- [ ] `python3-cryptography` installed on the Pi, and the serial source recorded in `docs/platform-versions.md`.
- [ ] `docs/security.md` written.
- [ ] The list of `reveal()` call sites in the hand-off notes (at this point: only inside `credentials.py` and tests).

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `CredentialStore.get(account_id) -> Secret | None`, `set(account_id, Secret)`, `delete(account_id)`, `ids()`, `status()` (`empty`/`ok`/`unreadable`) | US-14, US-15, US-16 (the sync process reads), US-20, US-25 |
| `Secret` (only `.reveal()` gives the value, at the last moment, e.g. building the HTTP auth header) | US-14, US-20, US-21/25 (UI entry) |
| `install_log_redaction()` called in every process right after logging is set up | US-16 (sync worker) |
| `app.credentials` (one instance in the UI process) | US-25 |
| Startup notice code `credentials_unreadable` | US-31, US-38 |
