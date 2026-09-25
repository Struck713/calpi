# US-41 — Weather

| | |
|---|---|
| **Epic** | 5. Extras |
| **Priority** | P2 |
| **Blocked by** | US-06 Month grid, US-23 Wi-Fi scan and connect |
| **Blocks** | — |
| **Phase** | 5. Extras (optional) |

## Story

> As a user, I want today's weather and a short forecast shown alongside the calendar.

## Context

A wall calendar is a natural place to glance at the weather before heading out. This story shows:
- **In the calendar header**: the current temperature and conditions, plus today's high and low ("☁ 14° · 18°/9°").
- **In the day cells** for today and the next 6 days: a small condition glyph and the high/low in the top-right corner of each cell, next to the day number. It's the "short forecast" shown **alongside the calendar**, not in a separate screen.

Data comes from **Open-Meteo** (`api.open-meteo.com`). It's free for non-commercial use, needs **no API key**, gives current conditions and daily forecasts in one request, and has a free **geocoding** API for finding the owner's city. The licence requires **attribution** ("Weather data by Open-Meteo.com", CC BY 4.0), which is shown in the Weather settings section.

Constraints:
- The fetch is small JSON, so it runs in `run_in_thread` in the UI process (it doesn't need the sync process). Every 30 minutes.
- **Offline**: keep the cached forecast (`<state>/weather.json`), and hide it when it's stale (older than 6 hours). **Never** show an error in the header for weather. Problems appear only in the Weather settings section and on the Status screen.
- **No icon theme or emoji fonts**: use DejaVu Sans glyphs (☀ ☁ ☂ ❄ ⚡ ≋) for conditions. They're monochrome but readable, and don't need assets (D3).
- **Privacy**: the location (the city's coordinates) is sent to Open-Meteo. Say so in Settings. It's opt-in, and off by default.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-06** Month grid | `MonthView.header.end_slot`, `DayCell` (the day number row where the forecast goes), `timeutil` (the zone, today), `month_changed_callbacks` | `grep -n "end_slot" calpi/widgets/header.py`; `grep -n "class DayCell" calpi/widgets/day_cell.py` |
| **US-23** Wi-Fi scan and connect | Network set-up (the device is online), and through it US-22 (the settings shell and rows for the Weather section) and US-21 (the OSK for city search) | Settings → Network works. `grep -n "def register_section" calpi/widgets/settings/shell.py` |

### Soft dependencies
- **US-17** `app.network`: skip fetches while it's `OFFLINE`, and fetch at once when the network comes back.
- **US-10** `app.clock`: re-render on the day change (the forecast shifts by one day).
- **US-28** `K_TIME_FORMAT`/zone: Open-Meteo's `timezone=auto` returns the forecast dates in the location's zone. Map them to our display dates (D4).
- **US-12** `safe_mode`: weather is disabled in safe mode.
- **US-31/US-38**: add `WEATHER_UNAVAILABLE` to the messages catalogue (status context only), and a line on the Status screen.
- **US-37**: register the periodic timer (`tasks.register_periodic("weather", ...)`).

### External blockers

| Blocker | What to do |
|---|---|
| **The owner's consent** to send their approximate location to Open-Meteo, and their city | Weather is **off by default**. The owner turns it on and picks the city in Settings. |
| **Open-Meteo's current terms and API** | Check with WebFetch: `https://open-meteo.com/en/terms` (non-commercial use, attribution) and the forecast API documentation (`/v1/forecast` parameters). Record the date checked in `docs/providers.md` (a Weather section). |
| **Glyph coverage in DejaVu Sans on the Pi** | Check that ☀ U+2600, ☁ U+2601, ☂ U+2602, ❄ U+2744, ⚡ U+26A1, and ≋ U+224B render (take a screenshot of a test label). If one is missing, swap it for another glyph or a short word ("Fog"). |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| The header gets too crowded (title, nav, weather, sync status, refresh, settings) | Keep the weather compact (≤ 260 px). If it still doesn't fit, shorten the sync status text (US-16) to "14:05" with a small "Updated" label above it. Check on the Pi screenshot. |
| The forecast in the cells clashes with the today marker or the event bars | It sits on the **day-number row only** (to the right of the number, inside `DAY_NUMBER_HEIGHT`), so the event layout (US-07 capacity) isn't affected. Use a small font (18 px). |
| The geocoding API returns many "Springfield"s | Show the region and country in each result ("Springfield, Illinois, United States"). |

---

## Scope

### In scope
- `calpi/weather/client.py` (no gi): the Open-Meteo forecast and geocoding requests (urllib, timeouts, size limits), parsing, WMO code → glyph and label mapping.
- `calpi/weather/cache.py` (no gi): an atomic JSON cache and staleness.
- `calpi/weather/service.py` (GLib): `WeatherService` (30-minute schedule, network-aware, the cache, callbacks).
- `calpi/widgets/weather_panel.py`: the header widget. The `DayCell` forecast labels (a small addition to US-06/07 widgets).
- The Weather settings section (`"weather"`, order 55): enable, location search, units (°C/°F), attribution, privacy note, last update.
- Settings key `K_WEATHER` (a dict).

### Out of scope
- Radar, hourly charts, weather alerts, and multiple locations.
- Location detection by IP or GPS.

---

## Acceptance criteria

1. **Off by default.** With it off: no network requests, and no weather UI anywhere except the settings section.
2. **Settings → Weather**: **Show weather** (switch), **Location** (a search field with the OSK → a results list with "City, Region, Country" → pick), **Units** (°C | °F), **Last updated**, a privacy note ("Your city's location is sent to Open-Meteo to get the forecast."), and the attribution "Weather data by Open-Meteo.com" (always visible in this section).
3. **Fetch**: one request to `/v1/forecast` with `latitude`, `longitude`, `current=temperature_2m,weather_code,is_day`, `daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max`, `forecast_days=7`, `timezone=auto`, `temperature_unit` from the setting. Timeout 10 s, response ≤ 1 MB. It runs in `run_in_thread`: every 30 minutes, when it's enabled, at startup (10 s after the first paint, **after** the first calendar sync has started), when the location or units change, and when the network comes back (US-17).
4. **Header**: "<glyph> <current temp>° · <max>°/<min>°" (≤ 260 px, 26 px font), placed in `header.end_slot` before the sync status. Hidden when it's disabled, when there's no data, or when the data is older than **6 hours**.
5. **Day cells**: for each visible date that has forecast data (today + 6 days), a small "<glyph> <max>°/<min>°" at the right of the day-number row (18 px, dimmed). Nothing for other dates. Updated when the forecast or the month changes. **No new widgets per render**: each `DayCell` has one forecast label, created once and hidden when there's nothing to show.
6. **Offline and failure**: keep showing the cached data until it's 6 hours old, then hide it. Failures are logged at INFO (once per state change), the "Last updated" line in Settings shows the failure time and reason in plain words, and US-31's Status screen shows "Weather: not updated since HH:MM". **No header or banner errors** for weather.
7. **Cache**: `<state>/weather.json` (written atomically) holds the last good response plus metadata (fetched_at, location, units), and it's loaded at startup so weather shows at once after a reboot if it's fresh.
8. **WMO codes → glyphs** (D3) cover every code Open-Meteo documents (0, 1–3, 45/48, 51–57, 61–67, 71–77, 80–82, 85–86, 95–99). Unit-tested, including a fallback for unknown codes.
9. **Dates**: forecast dates are placed on the matching **display dates** (D4). If the location's zone differs from the display zone, the daily entries still map by calendar date (the forecast day for "2026-09-25" goes on the 25 September cell).
10. **Safe mode** → weather is off. **Night mode** (US-30) doesn't stop fetches (they're cheap), but the render is skipped while the screen is off and done when it wakes.
11. The client, cache, and mapping are pure and unit-tested with fixture JSON. No gi in `calpi/weather/` except `service.py`.
12. Idle CPU and memory are unchanged (one timer every 30 minutes, registered with the US-37 registry).

---

## Design decisions (already made)

- **D1. `K_WEATHER`** = `{"enabled": false, "name": null, "lat": null, "lon": null, "units": "celsius"}`. The validator: lat in [-90, 90], lon in [-180, 180], units in {"celsius", "fahrenheit"}, and a name ≤ 100 characters. Written as one dict (copy then `set`, as in US-30 D1).
- **D2. Endpoints**: forecast `https://api.open-meteo.com/v1/forecast?...`; geocoding `https://geocoding-api.open-meteo.com/v1/search?name=<q>&count=10&language=en&format=json`. No auth. Use a small `urllib` wrapper with a timeout, the `User-Agent: calpi/<version>` header, and a size limit (reuse the size-limited reading idea from US-14's `http.py`, but **not** `HttpClient` itself: there's no auth and no redirect policy needed; `urlopen` redirects are fine for GET).
- **D3. Glyph mapping** (monochrome DejaVu glyphs):
  | Codes | Glyph | Label |
  |---|---|---|
  | 0 | ☀ (night: ☾) | Clear |
  | 1, 2 | ⛅ if present in DejaVu, else ☀ | Partly cloudy |
  | 3 | ☁ | Cloudy |
  | 45, 48 | ≋ | Fog |
  | 51–57 | ☂ | Drizzle |
  | 61–67, 80–82 | ☂ | Rain |
  | 71–77, 85–86 | ❄ | Snow |
  | 95–99 | ⚡ | Thunderstorm |
  | other | · | — |
  Check ⛅ (U+26C5) is in DejaVu Sans on the Pi. If it isn't, use ☀ for 1–2.
- **D4. Date mapping**: `daily.time` values are ISO dates in the location's zone. Map each to `date.fromisoformat(...)`, and show it on the cell with that date. It's a calendar-date match, not an instant conversion (weather for "Friday" belongs on Friday's cell).
- **D5. Staleness**: data is fresh for 6 hours for display. The fetch schedule is 30 minutes, with backoff after failures (1, 5, 15, then 30 minutes), a separate small policy from sync's.

---

## Implementation plan

1. **Check the API and terms** (external blockers). Save a real response (anonymised: a generic city's coordinates) as `tests/fixtures/weather/forecast.json`, plus a geocoding response.
2. **`calpi/weather/client.py`**: `fetch_forecast(lat, lon, units, timeout=10) -> Forecast`, `search_places(query) -> list[Place]`, `parse_forecast(json) -> Forecast` (current temp/code/is_day, and daily lists → a `dict[date, Daily(max, min, code, precip)]`), `glyph(code, is_day=True)`, `label(code)`. Errors → `WeatherError(kind)`, where kind is `offline`/`timeout`/`server`/`parse`. Classify with the same patterns as US-14's `classify_exception`: reuse it if it's importable without side effects, since it's pure.
3. **`calpi/weather/cache.py`**: `load(path) -> CachedForecast | None` (tolerant of corruption), `save(path, forecast, meta)` using `atomic_write_json`, `is_fresh(cached, now, max_age=6h)`.
4. **`calpi/weather/service.py`**: `WeatherService(app)` with `callbacks` (a `CallbackList`), `current: CachedForecast | None`, `status` (last success, last error), a timer (registered as periodic), network-up → fetch, settings subscription → refetch, safe-mode check, and the fetch through `run_in_thread` → save cache → notify.
5. **The header widget** `WeatherPanel(Gtk.Box)`: one label (glyph + temps), hidden when there's nothing fresh. It subscribes to the service callbacks and the minute clock (to hide it when it gets stale). Placed in `header.end_slot` before the sync indicator.
6. **Day cells**: add `self.forecast = Gtk.Label(css_classes=["cell-forecast"], halign=END, visible=False)` to `DayCell` (in the same row as the day number: turn the number row into a horizontal `Gtk.Box` [number | spacer | forecast], keeping the total height at `DAY_NUMBER_HEIGHT`). `MonthView` gets `set_forecast(dict[date, Daily] | None)`, which updates only the cells whose text changes. It's called on service updates and month changes.
7. **The settings section** (`calpi/widgets/settings/weather.py`): the switch; location search (an entry + OSK `text` purpose + a "Search" button → `run_in_thread(search_places)` → a results `ListPickerPage`); units `ChoiceRow`; last-updated `InfoRow`; privacy and attribution labels. Register `SectionSpec("weather", "Weather", 55, WeatherSection)`.
8. **Messages and Status** (if US-31/US-38 exist): the `WEATHER_UNAVAILABLE` entry (status context, info severity), and the Status line "Weather: updated 14:05" / "not updated since 09:10 (offline)".
9. **Tests**: `tests/test_weather_client.py` (parsing the fixtures, every WMO code range, unknown codes, is_day), `tests/test_weather_cache.py` (atomic save and load, corrupt file → None, freshness), the service scheduling with injectable timers (enabled/disabled, backoff, network-up trigger, safe mode).
10. **Pi check**: turn it on, search for the owner's city (the owner types it), and pick it. The header and cells show weather within 15 s. Screenshot. Check the glyphs render (D3). Switch to °F. Disconnect the network (US-17 method) → the cached weather keeps showing, and it's hidden after 6 hours (use a fake clock drop-in to check this faster: `CALPI_FAKE_NOW` offset +7 h, **removed afterwards**). The attribution is visible in the section.

---

## Files

| File | Change |
|---|---|
| `calpi/weather/__init__.py`, `client.py`, `cache.py`, `service.py` | New |
| `calpi/widgets/weather_panel.py` | New |
| `calpi/widgets/day_cell.py`, `month_view.py` | Forecast label, `set_forecast` |
| `calpi/widgets/settings/weather.py` | New |
| `calpi/widgets/settings/__init__.py` | Imports `weather` |
| `calpi/data/settings_store.py` | `K_WEATHER` |
| `calpi/app.py` | `app.weather = WeatherService(app)`, the header placement |
| `calpi/data/messages.py`, `calpi/widgets/settings/status.py` | Weather lines (if present) |
| `calpi/style.css` | `.weather-panel`, `.cell-forecast` |
| `docs/providers.md` | The Weather section (terms checked, attribution) |
| `tests/test_weather_*.py`, `tests/fixtures/weather/*` | New |

---

## Pitfalls

- **Turning weather on by default** (privacy, and network use on first boot).
- **Weather errors in the header or banner.** Weather is non-essential. Stay quiet (acceptance criterion 6).
- **Changing `DAY_NUMBER_HEIGHT`** or the cell layout, which breaks US-07's capacity. Keep the forecast within the number row.
- **Creating labels on every render.**
- **Fetching on the main thread.**
- **Missing attribution** (required by Open-Meteo's licence).
- **Emoji weather icons** (there's no emoji font on Pi OS Lite). Use the DejaVu glyphs.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] Checked on the Pi with the owner's city, including the offline and stale behaviour. Screenshots taken.
- [ ] Terms and API checked and recorded, and the attribution shown.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `app.weather` (`WeatherService`: `current`, `status`, `callbacks`) | US-39/US-40 (could show weather per day: optional), US-31 |
| `DayCell.forecast` label and `MonthView.set_forecast` | US-39 (the week view's day headers could reuse the same data) |
| `K_WEATHER` | — |
