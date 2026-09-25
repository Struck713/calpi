# US-20 — Additional providers

| | |
|---|---|
| **Epic** | 2. Calendar Syncing |
| **Priority** | P2 |
| **Blocked by** | US-15 Event fetching and parsing |
| **Blocks** | — |
| **Phase** | 5. Extras (optional) |

## Story

> As a user, I want to add calendars from other providers, such as Google, alongside iCloud.

## Context

The sync pipeline so far knows only iCloud. This story generalises it into a **provider registry**, and adds providers that make sense for a device with no browser and no keyboard:

| Provider | How it authenticates | Feasibility on this device |
|---|---|---|
| **Generic CalDAV** (Fastmail, Nextcloud, mailbox.org, Radicale, Synology, …) | Username + app password over HTTPS Basic auth, like iCloud | **Easy.** It reuses US-14/15 almost unchanged. The user enters a server URL. Discovery through `/.well-known/caldav` (RFC 6764). |
| **ICS subscription URL** (Google's "Secret address in iCal format", Outlook "published calendar" links, holiday/sports/school feeds) | A secret URL, no login | **Easy.** One HTTP GET, parsed by US-15's `ical_parse`. Read-only, and exactly what this device needs. |
| **Google Calendar through OAuth** | OAuth 2.0. Needs a browser consent screen, or the "limited input device" flow | **Hard, and possibly impossible for calendar scopes.** Google's device flow only allows a **short list of scopes**. At the time of writing, the Calendar API scopes may not be on it. It also needs a registered Google Cloud project, a client id, a verification process, and token refresh. **Research first (step 1). Don't build it unless it's confirmed viable.** |

**The recommended path for Google** is the ICS secret address (Google Calendar → Settings → the calendar → "Integrate calendar" → "Secret address in iCal format"). It's read-only, needs no OAuth, and has good freshness (Google updates it every few hours; that limitation must be shown to the user).

Because this is **P2**, keep it tight: the provider abstraction + generic CalDAV + ICS subscriptions. Google OAuth only goes as far as a written feasibility note unless the owner explicitly asks for more.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-15** Event fetching and parsing | `fetch.sync_account`, `ical_parse.parse_resources`, `compute_window`, `provider_hosts()`, `calendar_id_for()`, `EventStore.apply_calendar_sync`; plus US-14's `HttpClient`, `caldav` helpers, `Account`, `accounts.*`, CLI | `/usr/bin/python3 -m pytest tests/test_fetch.py tests/test_ical_parse.py` passes; `grep -n "def provider_hosts" calpi/sync/fetch.py` |

### Soft dependencies
- **US-16** worker — provider dispatch happens inside `sync_account`, so the worker needs no change if the dispatch lives in `fetch.py`. Check after implementing.
- **US-25** Account management UI — adding non-iCloud accounts **in the UI** requires US-25's flow to offer a provider choice. If US-25 exists, add provider forms there (step 6); if not, the CLI is enough for this story (note it).
- **US-21** on-screen keyboard — needed for typing server URLs / ICS URLs on the device. Long URLs are painful on an OSK: D6.
- **US-33** guide pattern — a short guide for "how to get your Google secret iCal address" follows the same pattern.

### External blockers

| Blocker | What to do |
|---|---|
| **Test accounts** for generic CalDAV (e.g. a free Nextcloud/Fastmail trial, or a local **Radicale** server in the devcontainer) | Radicale is pure Python (`pip install radicale` in a **devcontainer venv only**, never on the Pi) — run it locally for tests. Ask the owner which real providers they care about. |
| **A Google account with a calendar** for the ICS secret-address check | Owner provides the URL **by typing it on the device or via the CLI prompt** — it's a secret (anyone with it can read the calendar). Never paste into chat. |
| **Google OAuth research** needs current Google documentation | Use WebSearch/WebFetch on Google's "OAuth 2.0 for TV and Limited-Input Device Applications" page and its "allowed scopes" list. Record findings with date and URL. |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| A CalDAV server needs a non-standard discovery (no `.well-known`, principal elsewhere) | Allow the user to enter the **full calendar home or principal URL** as a fallback (advanced field). |
| An ICS feed is huge (years of history) or slow | Cap response size (US-14's 20 MB), timeout 30 s; parse only the window (US-15 already does). |
| ICS feeds have no ctag | Use HTTP `ETag`/`If-None-Match` and `Last-Modified`/`If-Modified-Since` → 304 = unchanged. Store the ETag in `calendars.ctag`. |
| Credentials for generic CalDAV servers on other hosts | `HttpClient.allowed_auth_hosts` must be set from the **user-entered server's host** (exact host match, https only). Never send credentials to redirect targets on other hosts. |

---

## Scope

### In scope
- `calpi/sync/providers.py`: `Provider` protocol + registry (`icloud`, `caldav`, `ics`).
- Refactor iCloud into the registry without behaviour change (all US-14/15 tests keep passing).
- Generic CalDAV provider: discovery via `/.well-known/caldav` → principal → home; manual URL fallback; per-account allowed auth host.
- ICS subscription provider: GET with ETag/Last-Modified, parse via `ical_parse`, one calendar per subscription, `webcal://` → `https://` normalization.
- Account model: `server_url` for caldav, `feed_url` stored **as a secret** for ICS (the URL is the credential).
- CLI support: `add-account --provider caldav --server URL --username U`, `add-account --provider ics --name "Holidays"` (URL prompted, hidden).
- UI forms in US-25's add-account flow **if** US-25 exists.
- A dated feasibility note on Google OAuth in `docs/providers.md`.

### Out of scope
- Google OAuth implementation (unless research proves viable **and** the owner asks).
- Microsoft Exchange/Graph (OAuth; same concerns).
- Write access (project-wide out of scope).

---

## Acceptance criteria

1. `providers.get(name) -> Provider` returns a provider with: `display_name`, `discover(account_fields, secret) -> Discovery`, `sync(account, secret, store, window, force) -> AccountResult`, `auth_hosts(account) -> tuple[str, ...]`. `icloud`, `caldav`, `ics` are registered.
2. **No regression:** all US-14/US-15/US-16 tests pass unchanged after the refactor; the owner's iCloud account keeps syncing on the Pi.
3. **Generic CalDAV:** given `server=https://cloud.example.com` (or `.../remote.php/dav` for Nextcloud), username and app password: discovery tries `<server>/.well-known/caldav` (following redirects to the same host), then the server URL itself, then an optional user-entered principal/home URL; finds VEVENT calendars; syncs events exactly like iCloud (ctag skip, REPORT, parse). Tested against a local Radicale server **and** fixture-based tests.
4. Credentials for a CalDAV account are only sent to its configured host (exact match) over https; a redirect to another host fails with `SERVER_ERROR`.
5. **ICS subscription:** given an `https://` or `webcal://` URL: GET with `If-None-Match`/`If-Modified-Since` when known; 304 → `unchanged`; 200 → parse with `ical_parse.parse_resources([body], ...)` and apply as one calendar; name from `X-WR-CALNAME` or the user-given name; colour: user-chosen or a default palette colour (ICS feeds rarely carry colour).
6. The ICS URL is stored in the `CredentialStore` (it is a secret), **not** in settings; logs show only the host (`ics: calendar.google.com …`).
7. Mixed accounts (iCloud + CalDAV + ICS) sync in one worker run; each account's result/status recorded independently (US-18).
8. `docs/providers.md` documents: supported providers, how to get credentials/URLs for each (Google secret address steps, Fastmail/Nextcloud app passwords), freshness caveats (Google ICS can lag hours), and the dated Google OAuth feasibility finding with sources.
9. If US-25 exists: the "Add account" flow offers iCloud / Other CalDAV / Calendar subscription (ICS URL), with forms using the OSK; long URL entry is made practical (D6).

---

## Design decisions (already made)

- **D1. Provider protocol** (`typing.Protocol`), implementations are modules `calpi/sync/provider_icloud.py`, `provider_caldav.py`, `provider_ics.py`; `providers.py` holds the registry. `fetch.sync_account` becomes a thin dispatcher: `providers.get(account.provider).sync(...)`. The CalDAV-generic machinery from `fetch.py` (list calendars, ctag, REPORT, apply) is shared by `icloud` and `caldav` — iCloud is "CalDAV with a fixed server and allowed host `icloud.com`".
- **D2. Account fields:** `Account` gains optional `server_url` (already exists) and `options: dict` (e.g. `{"principal_url_override": ...}`); for ICS: `server_url` = scheme+host only (for display/allowed host), full URL in the secret.
- **D3. ICS change detection** via HTTP validators; store `ETag` (or `Last-Modified` prefixed `lm:`) in `calendars.ctag`; also compare a SHA-256 of the body as a fallback when the server sends no validators (store as `sha:<hex>`), skipping the DB write when unchanged.
- **D4. ICS calendar id:** `f"{account.id}:feed"` (one calendar per ICS account).
- **D5. Minimum ICS refresh**: respect the global interval, but never more often than every 15 minutes for ICS (feeds are often rate-limited; Google updates slowly anyway).
- **D6. Long URL entry on the device** is error-prone. Offer, in this order: (a) the CLI over SSH for developers; (b) in the UI, a **paste-free** approach: show a short explanation that the URL can be typed on the OSK, with a monospace entry, a "show/hide" toggle and a **"Test"** button that validates before saving. (A companion web page or QR hand-off is out of scope — remote management is out of scope project-wide.)

---

## Implementation plan

### Step 1 — Google OAuth feasibility research (time-boxed: 1–2 hours)
Search Google's current docs: "OAuth 2.0 for TV and Limited-Input Device Applications" → "Allowed scopes". Record in `docs/providers.md`: date, URL, whether `https://www.googleapis.com/auth/calendar.readonly` (or `calendar.events.readonly`) is allowed for the device flow, what verification is required for a personal-use project. **Decision rule:** if not allowed → Google = ICS secret address only; stop. If allowed → still implement only if the owner explicitly asks (report back; don't expand scope yourself).

### Step 2 — Refactor into providers (no behaviour change)
1. Move iCloud-specific bits (root URL, allowed host, discovery entry) into `provider_icloud.py`.
2. Move the generic CalDAV sync loop from `fetch.py` into `caldav_sync.py` (`sync_caldav_account(account, secret, store, window, force, client)`), used by both icloud and caldav providers.
3. `fetch.sync_account` → dispatcher. `provider_hosts()` → `providers.get(p).auth_hosts(account)`.
4. Run all tests; deploy; confirm the owner's iCloud still syncs (`cli fetch`, then watch a scheduled run).

### Step 3 — Generic CalDAV provider
```python
class CalDavProvider:
    name = "caldav"; display_name = "Other CalDAV server"
    def auth_hosts(self, account): return (urlsplit(account.server_url).hostname,)
    def discover(self, fields, secret, client=None):
        base = normalize_server(fields["server_url"])          # add https:// if missing; reject http://
        candidates = [urljoin(base, "/.well-known/caldav"), base] + ([fields["principal_url"]] if fields.get("principal_url") else [])
        for url in candidates:
            try:
                principal = find_principal(client, url, auth)    # PROPFIND current-user-principal
                break
            except SyncError as e:
                if e.code in (ErrorCode.AUTH_FAILED,): raise
                continue
        home = find_home(client, principal, auth)
        calendars = list_event_calendars(client, home, auth)
        return Discovery(principal, home, display_name, calendars)
```
Reuse the US-14 helpers (`caldav.propfind`, the calendar filter). The allowed-auth-host check uses the **exact host** (not suffix) for generic servers.

Local test server: in the devcontainer only, `python3 -m venv /tmp/radicale-venv && /tmp/radicale-venv/bin/pip install radicale`, run with a config allowing htpasswd plain auth on `localhost:5232`, create a calendar with a few events (PUT .ics files via curl). Write an **opt-in** integration test (`CALPI_RADICALE_URL=http://localhost:5232`) — note: Radicale here is `http://`; allow `http://localhost` **only** when an explicit test flag is set (`allow_insecure_localhost=True` in the client), never in production code paths.

### Step 4 — ICS provider
```python
class IcsProvider:
    name = "ics"; display_name = "Calendar subscription (ICS link)"
    def auth_hosts(self, account): return ()                   # no Authorization header ever
    def sync(self, account, secret, store, window, force=False, client=None):
        url = normalize_feed(secret.reveal())                   # webcal:// -> https://; reject http://
        cid = f"{account.id}:feed"
        store.upsert_calendar(Calendar(id=cid, account_id=account.id, remote_href=None,
                                       remote_name=account.display_name, remote_color=account.options.get("color")))
        ctag = None if force else store.sync_state(cid)[0]
        headers = conditional_headers(ctag)                     # If-None-Match / If-Modified-Since
        r = client.request("GET", url, headers=headers, auth=None)
        if r.status == 304: return AccountResult(... unchanged ...)
        new_tag = validator_from(r) or "sha:" + sha256(r.body)
        if new_tag == ctag and not force: return AccountResult(... unchanged ...)
        events, stats = parse_resources([r.body], cid, window, timeutil.display_tz())
        n = store.apply_calendar_sync(cid, events, new_tag, None, window_ints(window))
        return AccountResult(account.id, None, "", [CalendarResult(cid, account.display_name, "ok", n, ...)])
```
`HttpClient` must accept 304 as a non-error response (extend `request()` with `ok_statuses=(200, 304)`). Log only the host of the feed URL.

### Step 5 — CLI
```
cli add-account --provider caldav --server https://cloud.example.com --username me   (password via getpass)
cli add-account --provider ics --name "Holidays" [--color '#ff8800']                (URL via getpass-style hidden prompt)
cli discover --provider caldav --server ... --username ...
```

### Step 6 — UI (only if US-25 exists)
In the add-account flow: provider chooser (3 large buttons) → provider-specific form (US-25's form component + OSK) → "Test & continue" → calendar selection (CalDAV) or name/colour (ICS). For ICS show the freshness caveat ("Google updates these links every few hours").

### Step 7 — Tests
- Registry & dispatch; iCloud unchanged (existing tests).
- CalDAV discovery: fixtures for Nextcloud-style (`/.well-known/caldav` → 301 → `/remote.php/dav/`), Fastmail-style, a server without well-known (falls back to base), manual principal override; exact-host auth check; http:// rejected.
- ICS: 200 then 304 → unchanged; no validators → sha fallback unchanged; webcal normalization; URL never in logs (caplog); X-WR-CALNAME naming; parse errors counted.
- Mixed-account worker run with fake transports.
- Opt-in Radicale integration test.

### Step 8 — Pi check
Add an ICS feed (e.g. a public holiday calendar URL the owner chooses) via CLI on the Pi; sync; see events in the grid in its colour. If the owner has a CalDAV provider, add it too.

---

## Files

| File | Change |
|---|---|
| `calpi/sync/providers.py`, `provider_icloud.py`, `provider_caldav.py`, `provider_ics.py`, `caldav_sync.py` | New (refactor + new) |
| `calpi/sync/fetch.py` | Becomes dispatcher |
| `calpi/sync/http.py` | `ok_statuses`, test-only insecure localhost |
| `calpi/data/models.py` | `Account.options` |
| `calpi/sync/cli.py` | Provider options |
| `calpi/widgets/settings/accounts.py` | Provider forms (if US-25 exists) |
| `docs/providers.md` | New |
| `tests/test_providers.py`, `tests/fixtures/caldav/*`, `tests/fixtures/ics/feeds/*` | New |

---

## Pitfalls

- **Breaking iCloud during the refactor** — do the refactor first, deploy, verify, then add providers.
- **Suffix host matching for generic servers** — `evil-example.com` ends with `example.com`. Exact match only.
- **Logging ICS URLs** — they are credentials.
- **Plain `http://`** feeds/servers — reject (credentials/secret URLs over cleartext).
- **Building Google OAuth without confirmed feasibility and owner request** — scope creep on a P2 story.
- **Installing Radicale (or anything from pip) on the Pi.**

---

## Definition of done

- [ ] All acceptance criteria met; iCloud regression-free on the Pi.
- [ ] `docs/providers.md` with dated Google OAuth finding.
- [ ] ICS feed (and CalDAV if available) verified on the Pi.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `providers.get(name)`, `providers.all()` (name, display_name) | US-25 (provider chooser), US-31/US-38 (provider names in messages) |
| `Account.provider` values: `icloud`, `caldav`, `ics` | US-25, US-38 |
| ICS accounts: one calendar `<account_id>:feed`; URL in CredentialStore | US-25, US-26 |
