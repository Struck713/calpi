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

## Weather (Open-Meteo, US-41)

Checked 2026-09-25 (live request and https://open-meteo.com/en/terms):

- Free API, no key. Non-commercial use only; limits 10,000 calls/day, 5,000/hour, 600/minute (calpi makes about 48
  forecast calls a day). Data is licensed CC BY 4.0, so **attribution is required**: "Weather data by Open-Meteo.com"
  is always visible in Settings, Weather.
- Forecast: `GET https://api.open-meteo.com/v1/forecast?latitude&longitude&current=temperature_2m,weather_code,is_day&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&forecast_days=7&timezone=auto&temperature_unit=celsius|fahrenheit`.
- Geocoding: `GET https://geocoding-api.open-meteo.com/v1/search?name=<q>&count=10&language=en&format=json`
  (`admin1` = region, `country`).
- `daily.time` dates are in the location's zone; calpi puts each on the cell with the same calendar date.
- Privacy: the chosen city's coordinates (and the Pi's IP address) reach Open-Meteo. Weather is off by default.
- Fixtures in `tests/fixtures/weather/` are real responses (Berlin coordinates; the "Springfield" search).
- Glyphs: DejaVu Sans has U+2600 U+2601 U+2602 U+2744 U+26A1 U+224B U+263E but NOT U+26C5, so codes 1-2 use the sun.
