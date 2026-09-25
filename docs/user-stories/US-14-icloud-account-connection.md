# US-14 — iCloud account connection

| | |
|---|---|
| **Epic** | 2. Calendar Syncing |
| **Priority** | P0 |
| **Blocked by** | US-13 Secure credential storage |
| **Blocks** | US-15 Event fetching and parsing, US-25 Account management |
| **Phase** | 2. Syncing |

## Story

> As a user, I want to sign in to iCloud with my Apple ID and an app-specific password, and have the device find my calendars.

## Context

iCloud exposes calendars over **CalDAV** (RFC 4791, built on WebDAV, RFC 4918), with HTTP Basic authentication using the Apple ID email and an **app-specific password**. Apple only issues app-specific passwords to accounts with two-factor authentication. The main Apple ID password never touches the device. iCloud Calendar isn't covered by Advanced Data Protection's end-to-end encryption, so CalDAV works even when ADP is turned on.

This story builds the **network and protocol layer** and the **account record**:
1. `calpi/sync/http.py`: a small, strict HTTP client on `urllib` (timeouts, Basic auth, **manual redirect handling** for WebDAV methods, size limits, error mapping).
2. `calpi/sync/caldav.py`: generic PROPFIND/REPORT helpers and `207 Multi-Status` parsing.
3. `calpi/sync/icloud.py`: iCloud **discovery**, going from `https://caldav.icloud.com/` to the user's principal, then their calendar home (on a per-user `pNN-caldav.icloud.com` host), then the list of event calendars with names and colours.
4. `calpi/sync/errors.py`: the **`ErrorCode` taxonomy** that the whole sync pipeline, the status tracking (US-18), and the user messages (US-38) share.
5. The `Account` model, stored in settings (non-secret fields), with the password in the `CredentialStore` (US-13).
6. `calpi/sync/cli.py`: a **developer CLI** to discover and save an account from the command line. That's how real accounts get onto the device during Phase 2, **before** the Settings UI (US-25) exists.

Everything in `calpi/sync/` is **pure Python, with no gi**. It runs in the sync process (US-16) and in UI worker threads (US-25 uses `run_in_thread`).

**Why a small in-house client** instead of the `caldav` PyPI package: we need exactly four request shapes, strict timeouts, control over redirects and auth forwarding, error codes that map straight to user messages, and no extra dependencies on the Pi (the `caldav` package pulls in `requests`, `lxml`, and more). The decision is made.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-13** Secure credential storage | `CredentialStore.get/set/delete`, `Secret`, `install_log_redaction()` | `/usr/bin/python3 -m pytest tests/test_credentials.py` passes. `grep -n "class Secret" calpi/data/credentials.py` |

(US-13 depends on US-05, so `SettingsStore` and its key registry exist too, and they're used for the account records.)

### Soft dependencies
- **US-04** Event store: *not needed here.* Discovery returns `RemoteCalendar` objects and **doesn't** write them to the event store (US-15 and US-25 do). The README notes this gap.
- **US-03**: to run the CLI on the Pi (`scripts/pi ssh ...`).
- **US-12**: `CLOCK_WRONG` detection uses the NTP sync state. There's no code dependency.

### External blockers (important)

| Blocker | Why | What to do |
|---|---|---|
| **A real iCloud account with 2FA and an app-specific password** | Only real iCloud can confirm the discovery flow and the actual XML. | Ask the owner to create an app-specific password named "calpi" at **account.apple.com → Sign-In and Security → App-Specific Passwords**. **The owner must type it in themselves** (step 9): **never ask them to paste it into chat**, and never put it in files, command lines, or environment variables that get logged. |
| **Test calendars** | To check filtering and colours | Ask the owner to make sure the account has at least 2 event calendars with different colours, and (if they use it) the Reminders app, so we can check that reminder lists are **excluded**. |
| **Outbound HTTPS from the devcontainer and the Pi** to `caldav.icloud.com` and `*.icloud.com` | Discovery | If there's a proxy or firewall, report it. |
| **CA certificates** (`ca-certificates` package) and a correct clock | TLS verification | Pi OS has them. A wrong clock (no RTC, no NTP yet) makes certificate checks fail: that's the `CLOCK_WRONG` code (D6). |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| **HTTP 401** with a password you're sure is right | App-specific passwords are revoked when the Apple ID's main password changes, or when the owner revokes them. Also check the username is the **Apple ID email** (not a phone number or alias). Ask the owner to generate a new one. |
| `urllib` raises `HTTPError 301/302` for PROPFIND | Expected: `urllib` only follows redirects for GET/HEAD/POST. That's why `http.py` handles redirects by hand (D3). |
| The calendar home URL has an explicit port (`:443`) | Normal for iCloud. Keep URLs exactly as the server gave them (after `urljoin`). Don't "clean them up". |
| Apple changes behaviour (an extra redirect, a different host) | The discovery follows the standard: `current-user-principal` → `calendar-home-set`, and **never hard-codes** `pNN` hosts. If it still breaks, capture the (redacted) XML and report it. |
| iCloud returns `503`, or rate limits | Back off. Don't loop. Map it to `RATE_LIMITED`/`SERVER_ERROR`. |

---

## Scope

### In scope
- `calpi/sync/errors.py`, `http.py`, `caldav.py`, `icloud.py`, `cli.py`.
- `Account` and `RemoteCalendar` dataclasses (`calpi/data/models.py`).
- The account list in settings (`K_ACCOUNTS`) and helpers to add or update an account (secret → `CredentialStore`, record → settings).
- Recorded, **anonymised** XML fixtures and unit tests with a fake transport.
- Checking against the real iCloud account through the CLI.

### Out of scope
- Fetching events (US-15), scheduling (US-16), the UI (US-25), removing accounts (US-25; add a `remove_account()` helper only if it's trivial), and other providers (US-20, but design `caldav.py` generically so US-20 can reuse it).

---

## Acceptance criteria

1. `icloud.discover(username, secret) -> Discovery` makes **at most 3 round trips** (plus any redirects), and returns: the principal URL, the calendar home URL, the principal's display name (if given), and a list of `RemoteCalendar(href, name, color, ctag, sync_token, read_only)` containing **only calendars that support `VEVENT`**. Reminder lists (VTODO-only), the inbox, the outbox, notifications, and non-calendar collections are excluded.
2. Colours are normalised to lowercase `#rrggbb` (iCloud sends `#RRGGBBAA`: drop the alpha). A missing or invalid colour → `None`.
3. Failures raise `SyncError(code, detail)`, with `code` taken from `ErrorCode`:
   - 401 → `AUTH_FAILED`; 403 → `AUTH_FAILED` (with detail "forbidden"),
   - DNS failure → `DNS_FAILED`; no route, network down, or connection refused → `NETWORK_DOWN`,
   - a connect or read timeout (20 s) → `TIMEOUT`,
   - certificate problems → `TLS_ERROR`, or `CLOCK_WRONG` if the system clock looks wrong (D6),
   - 429 / 503 → `RATE_LIMITED` (with `retry_after` seconds when the header is present); other 5xx → `SERVER_ERROR`,
   - 404 on a discovery step → `NOT_FOUND`; XML that can't be parsed or is missing required properties → `PARSE_ERROR`.
4. **Redirects**: up to 5 are followed for PROPFIND/REPORT, keeping the method and body. **Credentials are only sent to `https` URLs whose host is `icloud.com` or ends with `.icloud.com`** (for the iCloud provider). A redirect to anything else fails with `SERVER_ERROR` ("unexpected redirect").
5. Responses bigger than **20 MB** are aborted (`SERVER_ERROR`, "response too large"). XML containing `<!DOCTYPE` is rejected (`PARSE_ERROR`).
6. `accounts.add_or_update_account(settings, credentials, provider, username, secret, discovery) -> Account`: stores the secret under the account id **first**, then the record in settings. If the settings write fails, the secret is removed again. Adding the same provider + username (case-insensitive) **updates** the existing account (a new password, fresh URLs) instead of creating a duplicate.
7. The CLI: `python3 -m calpi.sync.cli discover --username U` asks for the password with `getpass` (no echo), and prints the principal, home, and calendars (name, colour, href). `add-account --provider icloud --username U` does the same and saves the account. `list-accounts` prints the saved accounts (never the secrets). **The password is never taken from argv.** For automated local testing, `--password-env VAR` reads it from a named environment variable. That's documented as dev only.
8. With the owner's real account, `discover` on the Pi lists their event calendars correctly (the names and colours match the Calendar app), and excludes reminder lists. The owner confirms this.
9. The secret never appears in logs, exceptions, or the CLI output (tests with `caplog` and `capsys`).
10. All of `calpi/sync/` imports with no gi (the `test_no_gi` check is extended to `calpi.sync`).

---

## Design decisions (already made)

- **D1. `ErrorCode`** (a `str` `Enum`) in `calpi/sync/errors.py`: `AUTH_FAILED, NETWORK_DOWN, DNS_FAILED, TIMEOUT, TLS_ERROR, CLOCK_WRONG, SERVER_ERROR, RATE_LIMITED, NOT_FOUND, PARSE_ERROR, CREDENTIALS_UNREADABLE, DISK_FULL, UNKNOWN`. `SyncError(Exception)` has `code`, `detail` (technical, English, **never containing secrets**), `retry_after: int | None`, and `transient: bool` (a property: True for NETWORK_DOWN, DNS_FAILED, TIMEOUT, SERVER_ERROR, RATE_LIMITED).
- **D2. The HTTP client** (`calpi/sync/http.py`):
  - `HttpClient(timeout=20, max_bytes=20_000_000, user_agent="calpi/<version>", allowed_auth_hosts=(...))`.
  - `request(method, url, *, body: bytes | None, headers: dict, auth: tuple[str, Secret] | None) -> Response(status, headers, body, url)`.
  - Uses `urllib.request.build_opener` with a custom `HTTPRedirectHandler` that **doesn't** redirect (it returns the 3xx to our code), and a default `ssl.create_default_context()` (system CAs). Our loop handles redirects (D3).
  - Basic auth is sent **up front** (`Authorization: Basic base64(user:secret)`). It's built at the last moment from `secret.reveal()`, and never stored on the client.
  - Reads in chunks, up to `max_bytes`.
  - A **transport seam** for tests: `HttpClient(transport=callable)`, where the callable takes `(method, url, headers, body)` and returns `(status, headers, body)`. The production transport is the urllib opener.
- **D3. Redirects**: 301, 302, 303, 307, 308. Resolve `Location` with `urljoin`. Keep the method and body (WebDAV servers expect that, even for 301/302). Maximum 5 hops. Auth is only re-sent if the new URL passes `allowed_auth_hosts`, **and** is `https`.
- **D4. XML** with `xml.etree.ElementTree` (stdlib). Namespaces: `DAV:` (d), `urn:ietf:params:xml:ns:caldav` (c), `http://calendarserver.org/ns/` (cs), `http://apple.com/ns/ical/` (a). Reject `<!DOCTYPE` before parsing (D2's size check comes first). Only use `propstat` blocks whose `status` contains ` 200 `.
- **D5. `Account`** (frozen dataclass, **no secret in it**): `id` (`"icloud-" + secrets.token_hex(4)`), `provider` (`"icloud"`), `username`, `display_name` (from the principal's `displayname`, or the username), `server_url` (`https://caldav.icloud.com/`), `principal_url`, `calendar_home_url`, `created_at` (ISO UTC). Stored in settings as a list of dicts under `K_ACCOUNTS` (validator: a list of dicts that have the required keys).
- **D6. CLOCK_WRONG**: when the TLS error is certificate verification and **either** the message says "not yet valid" or "expired", **or** `timedatectl show -p NTPSynchronized --value` says `no`, **or** the system year is < 2025, map it to `CLOCK_WRONG`. (Checking NTP runs a subprocess. Only do it on this error path, in the sync process or worker thread, never on the UI thread.)
- **D7. Discovery flow** (iCloud):
  1. `PROPFIND https://caldav.icloud.com/` (Depth: 0) for `d:current-user-principal` (and `d:displayname`). If the root gives no principal, try `https://caldav.icloud.com/.well-known/caldav`.
  2. `PROPFIND <principal>` (Depth: 0) for `c:calendar-home-set` and `d:displayname`.
  3. `PROPFIND <home>` (Depth: 1) for `d:displayname`, `d:resourcetype`, `c:supported-calendar-component-set`, `a:calendar-color`, `a:calendar-order`, `cs:getctag`, `d:sync-token`, `d:current-user-privilege-set`.
  4. Keep the responses where `resourcetype` contains `c:calendar` **and** the supported components include `VEVENT` (if the component set is missing, assume VEVENT is supported: the RFC default is "all"). Skip the home collection itself (href == home), and `inbox`/`outbox`/`notification` collections (their resourcetype isn't `c:calendar` anyway, but check).
  5. Sort by `a:calendar-order` (if present), then by name.

---

## Implementation plan

### Step 1 — `errors.py`
Write the enum and exception as in D1. Add `classify_exception(exc) -> SyncError`, which maps `urllib.error.URLError` (look at `exc.reason`: `socket.gaierror` → DNS_FAILED; `ConnectionRefusedError`, `OSError(errno.ENETUNREACH / EHOSTUNREACH)` → NETWORK_DOWN; `socket.timeout`/`TimeoutError` → TIMEOUT; `ssl.SSLCertVerificationError` → TLS_ERROR/CLOCK_WRONG), plain `TimeoutError`, `ssl.SSLError`, and `http.client.RemoteDisconnected` (→ NETWORK_DOWN) into our codes. **Test each mapping with constructed exceptions.**

### Step 2 — `http.py`
Implement D2 and D3. Sketch:
```python
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None                                  # hand the 3xx back to us

def _urllib_transport(timeout, max_bytes):
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    def send(method, url, headers, body):
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:          # 3xx/4xx/5xx arrive here
            resp = e
        with resp:
            data = _read_limited(resp, max_bytes)
            return resp.status if hasattr(resp, "status") else resp.code, dict(resp.headers), data
    return send
```
In `HttpClient.request()`: loop over redirects, build the headers (`Content-Type: application/xml; charset=utf-8`, `Depth`, `User-Agent`, `Authorization` when allowed), call the transport inside `try` → `classify_exception`, and map status codes to `SyncError` (acceptance criterion 3). Return `Response` for 2xx (207 included).

`Retry-After` can be seconds or an HTTP date. Parse both (`email.utils.parsedate_to_datetime`), and cap it at 3600.

### Step 3 — `caldav.py` (generic)
```python
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "cs": "http://calendarserver.org/ns/", "a": "http://apple.com/ns/ical/"}

def propfind(client, url, props: list[str], depth: int, auth) -> list[DavResponse]:
    body = build_propfind(props)          # props like "d:displayname"
    r = client.request("PROPFIND", url, body=body, headers={"Depth": str(depth)}, auth=auth)
    return parse_multistatus(r.body, base_url=r.url)

@dataclass
class DavResponse:
    href: str                 # absolute URL (urljoin with base)
    props: dict[str, ET.Element]   # "d:displayname" -> element (only from 200 propstats)

def parse_multistatus(body: bytes, base_url: str) -> list[DavResponse]: ...
def text(resp: DavResponse, prop: str) -> str | None: ...
def href_in(resp: DavResponse, prop: str) -> str | None:     # e.g. current-user-principal/d:href
```
Build the XML request bodies with `ET` (not string formatting), with the namespace prefixes declared, UTF-8, and an XML declaration.

Normalise hrefs: `urljoin(base_url, href.strip())`. Keep the trailing slash as the server gives it. Compare collection URLs **with** trailing slashes normalised (`rstrip("/") + "/"`) only when checking "is this the home itself".

### Step 4 — `icloud.py`
```python
ICLOUD_ROOT = "https://caldav.icloud.com/"
ALLOWED = ("icloud.com",)   # host == or endswith ".icloud.com"

@dataclass(frozen=True)
class Discovery:
    principal_url: str
    calendar_home_url: str
    display_name: str | None
    calendars: list[RemoteCalendar]

def discover(username: str, secret: Secret, client: HttpClient | None = None) -> Discovery:
    client = client or HttpClient(allowed_auth_hosts=ALLOWED)
    auth = (username.strip(), secret)
    # step 1..5 of D7
```
`RemoteCalendar` lives in `calpi/data/models.py` (it's shared with US-15 and US-25): `href, name, color, ctag, sync_token, order, read_only`. `read_only` = the privilege set doesn't contain `d:write`/`d:write-content`/`d:all`. It's informational only (the device is read-only anyway).

Colour normalisation: `re.fullmatch(r"#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", s)` → `"#" + group1.lower()`.

### Step 5 — Account records (`calpi/data/accounts.py`, no gi)
```python
K_ACCOUNTS = "accounts"   # register in settings_store.py with validator _valid_accounts

def list_accounts(settings) -> list[Account]: ...
def get_account(settings, account_id) -> Account | None: ...
def find_account(settings, provider, username) -> Account | None:   # casefold match
def add_or_update_account(settings, credentials, provider, username, secret, discovery) -> Account:
    existing = find_account(settings, provider, username)
    acc = Account(id=existing.id if existing else f"{provider}-{secrets.token_hex(4)}", ...)
    credentials.set(acc.id, secret)
    try:
        others = [a for a in list_accounts(settings) if a.id != acc.id]
        settings.set(K_ACCOUNTS, [asdict_no_secret(a) for a in others + [acc]])
    except Exception:
        if not existing: credentials.delete(acc.id)
        raise
    return acc
```
**Where it runs**: in the UI process (US-25), `settings.set` must be called **on the main thread** (the US-05 convention). So split the UI flow: `discover()` in a worker thread → `on_done` on the main thread → `add_or_update_account(...)`. The CLI runs in its own process and uses its own `SettingsStore`. That's fine as long as **the kiosk app isn't writing at the same moment**. Document in the CLI help: "stop the kiosk (`sudo systemctl stop calpi-kiosk`) or restart it afterwards; the running app won't see CLI-added accounts until restarted". Keep it simple.

### Step 6 — `cli.py`
```
python3 -m calpi.sync.cli discover     --username me@icloud.com [--password-env VAR]
python3 -m calpi.sync.cli add-account  --provider icloud --username me@icloud.com [--password-env VAR]
python3 -m calpi.sync.cli list-accounts
python3 -m calpi.sync.cli remove-account --id icloud-1a2b3c4d
```
`argparse` subcommands. The password comes from `getpass.getpass("App-specific password: ")` (reads from the TTY), or `os.environ[VAR]` with `--password-env`. Call `install_log_redaction()`. Exit codes: 0 ok, 2 auth failed, 3 network problem, 1 anything else. Print `SyncError.code` and the detail.

### Step 7 — Fixtures and tests (`tests/fixtures/icloud/*.xml`, `tests/test_caldav.py`, `tests/test_icloud.py`, `tests/test_http.py`, `tests/test_accounts.py`)

Write fixtures **by hand** at first, from the RFCs and the example responses in this file. Then **replace or add** real ones captured in step 9, **anonymised** (replace the DSID numbers, emails, and calendar names).

Example principal response:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:">
  <response>
    <href>/</href>
    <propstat>
      <prop><current-user-principal><href>/123456789/principal/</href></current-user-principal></prop>
      <status>HTTP/1.1 200 OK</status>
    </propstat>
  </response>
</multistatus>
```
Example calendar list (Depth 1) must include: the home itself; two VEVENT calendars with `#FF2968FF` / `#1BADF8FF` colours; one VTODO-only list; one calendar missing the component set (treated as VEVENT); `inbox` and `outbox` (resourcetype `c:schedule-inbox`/`schedule-outbox`); and a propstat with `404` for `calendar-color` (must be ignored).

Tests (with a fake transport that returns fixtures by `(method, url)`):
- The discovery happy path: exactly 3 requests, the right URLs, the right `Depth` headers, auth sent, and the calendars filtered and sorted with normalised colours.
- A redirect from `caldav.icloud.com` to `p42-caldav.icloud.com` → followed with auth. A redirect to `http://` or `evil.example` → `SERVER_ERROR`, and **no auth sent** to it (check what the fake transport received).
- 401 → `AUTH_FAILED`. 503 with `Retry-After: 120` → `RATE_LIMITED`, `retry_after == 120`. Timeout → `TIMEOUT`. `gaierror` → `DNS_FAILED`.
- A DOCTYPE in the body → `PARSE_ERROR`. Missing `calendar-home-set` → `PARSE_ERROR`. More than 20 MB → aborted.
- `add_or_update_account`: new, then the same username in a different case → the same id and an updated secret. A settings write failure → the secret is removed again.
- No secret in logs or output: run discover with a fake 401, capture the logs and the exception `str`, and check the secret isn't there.

### Step 8 — `test_no_gi` covers `calpi.sync`
Extend the subprocess check from US-04 to import `calpi.sync.errors`, `http`, `caldav`, `icloud`, and `cli`.

### Step 9 — Check with the real account (with the owner)
1. Deploy (`scripts/pi deploy`).
2. **Ask the owner to run** (so they type the password, and it never passes through the agent):
   ```
   ! ssh -t calpi 'cd /opt/calpi && sudo -u kiosk env STATE_DIRECTORY=/var/lib/calpi CALPI_LOG_LEVEL=DEBUG /usr/bin/python3 -m calpi.sync.cli discover --username <their Apple ID>'
   ```
   (The `!` prefix runs it in their terminal session inside Claude Code. `ssh -t` gives getpass a TTY.)
3. Check the output with the owner: the calendars match, the colours look right, and the reminder lists are absent.
4. To capture fixtures: add a `--dump-dir DIR` option (dev only) that saves the raw response bodies. **Anonymise them before copying them into `tests/fixtures/`** (DSIDs, emails, and calendar names: use `sed`, then look at the result).
5. Then the owner runs `add-account` the same way, followed by `list-accounts`, and `sudo systemctl restart calpi-kiosk`. The account is now on the device for US-15/US-16.

---

## Files

| File | Change |
|---|---|
| `calpi/sync/__init__.py`, `errors.py`, `http.py`, `caldav.py`, `icloud.py`, `cli.py` | New |
| `calpi/data/models.py` | `Account`, `RemoteCalendar` |
| `calpi/data/accounts.py` | New |
| `calpi/data/settings_store.py` | `K_ACCOUNTS` with a validator |
| `tests/fixtures/icloud/*.xml` | New |
| `tests/test_http.py`, `test_caldav.py`, `test_icloud.py`, `test_accounts.py`, `test_no_gi.py` (extended) | New/changed |

---

## Pitfalls

- **Following redirects with auth to any host.** That would leak the password (D3).
- **Letting `urllib` handle PROPFIND redirects.** It won't (it raises).
- **String-formatted XML**: escape problems. Build it with `ET`.
- **Trusting 207 propstats blindly**: a propstat with `404` means "property not found". Ignore those.
- **Hard-coding `pNN-caldav.icloud.com`**: always discover it.
- **Putting the secret in the `Account` dataclass.** Keep it only in `CredentialStore`.
- **Asking the owner to paste the password in chat.** Never.
- **CLI writes while the app is running** could lose an update (two writers). Document it (step 5).

---

## Definition of done

- [ ] All acceptance criteria met, and the tests cover every listed case.
- [ ] Real-account discovery checked with the owner on the Pi, and the account saved for US-15.
- [ ] Anonymised real fixtures added.
- [ ] The no-gi test covers `calpi.sync`.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `ErrorCode`, `SyncError(code, detail, retry_after, transient)`, `classify_exception` | US-15, US-16, US-17, US-18, US-20, US-25, US-38 |
| `HttpClient` (with the transport seam) and `caldav.propfind`/`parse_multistatus`/`NS` | US-15 (REPORT), US-20 (generic CalDAV) |
| `icloud.discover(username, secret) -> Discovery` | US-15, US-25 |
| `Account`, `RemoteCalendar` models; `accounts.list_accounts/get_account/find_account/add_or_update_account` | US-15, US-16, US-18, US-25, US-31 |
| `K_ACCOUNTS` settings key (a list of account dicts, no secrets) | US-16 (the sync process reads it), US-25, US-32 |
| The CLI (`discover`, `add-account`, `list-accounts`, `remove-account`) | the developer workflow until US-25; US-20 extends it |
