# Calendar providers

| Provider | Name in code | Sign-in | Notes |
|---|---|---|---|
| iCloud | `icloud` | Apple ID + app-specific password | See the iCloud guide (US-33). |
| Other CalDAV (Fastmail, Nextcloud, mailbox.org, Radicale, Synology) | `caldav` | Username + app password over https | Server address, e.g. `https://cloud.example.com` (Nextcloud also works as `.../remote.php/dav`). Discovery tries `/.well-known/caldav`, then the address itself, then an optional principal/home URL. Credentials go only to that exact host. |
| Calendar subscription | `ics` | None: the secret link is the credential | `https://` or `webcal://`. Read-only. |

CLI (stop the kiosk first, or restart it afterwards):

    python3 -m calpi.sync.cli add-account --provider caldav --server https://cloud.example.com --username me
    python3 -m calpi.sync.cli add-account --provider ics --name Holidays [--color '#ff8800']   # link prompted, hidden
    python3 -m calpi.sync.cli discover --provider caldav --server ... --username ...

## Getting credentials

- **Google (recommended path):** Google Calendar on the web, Settings, the calendar, "Integrate calendar",
  "Secret address in iCal format". Anyone with this link can read the calendar: never paste it in chat or logs.
  Google refreshes these links only every few hours, so new events can take that long to appear.
- **Outlook / holiday / sports / school feeds:** use the published ICS link.
- **Fastmail:** Settings, Privacy & Security, Integrations, New app password (CalDAV). Server `https://caldav.fastmail.com`.
- **Nextcloud:** Settings, Security, Devices & sessions, create an app password. Server `https://<host>/remote.php/dav`.

## Behaviour

- ICS feeds are fetched with `If-None-Match` / `If-Modified-Since`; a 304 means unchanged. Without validators a
  SHA-256 of the body is compared. Never more often than every 15 minutes per feed.
- The feed URL is stored encrypted in the credential store, not in settings; logs show only the host.
- Plain `http://` servers and feeds are rejected.

## Google OAuth feasibility (not built)

Dated 2026-09-25. Written from prior knowledge of Google's "OAuth 2.0 for TV and Limited-Input Device
Applications" page (https://developers.google.com/identity/protocols/oauth2/limited-input-device); it was NOT
re-checked against the live page in this session (no web access used). That page lists the allowed device-flow
scopes as `openid`, `email`, `profile`, `drive.appdata`, `drive.file`, `youtube` and `youtube.readonly`; the Calendar
scopes are not on the list. It would also need a Google Cloud project, consent-screen configuration (with testing-mode
refresh tokens expiring after 7 days) and possibly verification. Decision rule from US-20: Google = ICS secret
address only. Re-verify the scope list before revisiting.
