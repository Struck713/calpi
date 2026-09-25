# US-17 — Offline resilience

| | |
|---|---|
| **Epic** | 2. Calendar Syncing |
| **Priority** | P0 |
| **Blocked by** | US-16 Scheduled background sync |
| **Blocks** | — |
| **Phase** | 2. Syncing |

## Story

> As a user, I want the calendar to keep showing the last synced events when the network is down, and to retry quietly until it's back.

## Context

Home Wi-Fi drops out, routers reboot at night, and iCloud has short outages. The display must **never go blank, never show an error dialog, and never flicker** because of it. It keeps showing what it has (the event store: US-04), it shows a **subtle** hint that it's offline, and it **retries on its own**, quickly at first and then less often, **plus straight away when the network comes back**.

Most of the "keep showing" part is already true by design: the UI reads only from SQLite, and US-15 never changes the store on a failure. This story adds:
1. **The retry policy**: backoff after transient failures, reset on success, and no fast retries for non-transient failures such as a wrong password.
2. **The network monitor**: listen to NetworkManager over D-Bus and trigger a sync as soon as the device is connected again.
3. **Offline and stale states in the header indicator** (US-16's `SyncIndicator`).
4. **Clock trust**: the Pi has no RTC. After a long power-off it boots with an old date and can't fix it until the network is back. That's a real offline problem for a calendar ("today" is wrong!). Detect "time not synchronised" and show it.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-16** Scheduled background sync | `SyncEngine` (`request_sync`, `result_callbacks`, the scheduling internals `_arm`), the result JSON with per-account `error` codes and `retry_after`, `SyncIndicator`, `last_success_wall` | `/usr/bin/python3 -m pytest tests/test_sync_engine.py` passes. On the Pi, `scripts/pi logs \| grep "sync:"` shows scheduled runs. |

### Soft dependencies
- **US-23** (Wi-Fi) will also create `calpi/system/networkmanager.py`, for connecting. **This story creates the module first** (the monitoring part). US-23 adds to it. Keep the D-Bus code in one module.
- **US-10**: `app.clock` for refreshing the "stale" wording every minute. Without it, refresh on sync results only.
- **US-18/US-38** will turn the error states into detailed messages. Here, offline means only the subtle indicator.

### External blockers

| Blocker | What to do |
|---|---|
| **NetworkManager on the Pi** (Pi OS Bookworm and Trixie use it) and its D-Bus API | Check: `ssh calpi 'nmcli general status; busctl introspect org.freedesktop.NetworkManager /org/freedesktop/NetworkManager \| grep -E "State\|Connectivity"'`. If the Pi doesn't use NM, stop and report it (US-23 depends on NM too). |
| **The `kiosk` user can read NM properties on the system bus** | Reading properties needs no polkit permission. Check: `ssh calpi 'sudo -u kiosk busctl get-property org.freedesktop.NetworkManager /org/freedesktop/NetworkManager org.freedesktop.NetworkManager State'` → `u 70` (connected globally). |
| **A safe way to take the Pi offline for testing** | If the Pi is on Wi-Fi, turning Wi-Fi off **cuts your SSH session**. Schedule the re-enable *first* (step 7), or ask the owner to unplug the router / use Ethernet. |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| NM's `Connectivity` property stays `UNKNOWN` (0) or `FULL` (4) whatever happens | Debian ships NM with **connectivity checking disabled** (no check URI). Use **`State`** (70 = `CONNECTED_GLOBAL`) as the main signal, and our own sync results as the truth. Record what the Pi reports. Don't turn on an external connectivity-check URL without asking the owner (privacy). |
| D-Bus property-change signals don't arrive | Subscribe to `org.freedesktop.DBus.Properties.PropertiesChanged` on `/org/freedesktop/NetworkManager` (in NM ≥ 1.x this is what's emitted), or use `Gio.DBusProxy` and its `g-properties-changed` signal (it caches properties and emits on changes). Test both in the devcontainer against a stub (step 6). |
| The devcontainer has no system bus or NM | The monitor must degrade to "unknown" without errors. Test it there with a fake. |
| `timedate1` access for NTP status | `org.freedesktop.timedate1` → property `NTPSynchronized` (boolean). Reading it needs no privileges. If it isn't available, fall back to `timedatectl show -p NTPSynchronized --value` in a worker thread. |

---

## Scope

### In scope
- `calpi/sync/retry.py` (no gi): `RetryPolicy`, pure and tested.
- An engine extension: `schedule_retry()`, and applying the policy after each result.
- `calpi/system/networkmanager.py`: `NetworkMonitor` (Gio D-Bus: State and Connectivity, change callbacks).
- `calpi/system/timesync.py`: `ClockTrust` (NTPSynchronized through timedate1, change callback).
- `SyncIndicator` states: `offline`, `stale`, `time-unsynced`.
- Quiet logging (state changes at INFO, repeats at DEBUG).

### Out of scope
- Detailed error messages and fixes (US-38), per-calendar status (US-18), Wi-Fi UI (US-23), and the Status screen (US-31).

---

## Acceptance criteria

1. With the network down, the grid keeps showing the last synced events **unchanged**. No dialog appears, and the grid never empties.
2. **Retry schedule** after a run where every account failed with a **transient** error (`NETWORK_DOWN`, `DNS_FAILED`, `TIMEOUT`, `SERVER_ERROR`, `RATE_LIMITED`): the next attempts come after **1, 2, 4, 8, then 15 minutes**, and after that every `min(15, interval)` minutes, never more often than every 60 s. A `retry_after` from the server is respected when it's longer. A **successful** run resets the backoff.
3. **Non-transient** failures (`AUTH_FAILED`, `CREDENTIALS_UNREADABLE`, `PARSE_ERROR`, `NOT_FOUND`) **don't** use fast retries. The normal interval continues (so a fixed password gets picked up, and the log isn't spammed).
4. **Network comes back**: when NM's `State` changes to `CONNECTED_GLOBAL` (70) from any lower state, a sync is requested **5 s later** (debounced, so DHCP and DNS can settle), whatever the backoff says.
5. The header indicator shows:
   - `Offline · updated 14:05` when the last run failed with a network-type error **or** NM reports it's not connected (grey, subtle),
   - `Updated yesterday 22:15` or `Updated 3 days ago`, in a warmer colour (`@text_dim` → an amber `.stale` class), when the last success is more than **6 hours** old, whatever the cause,
   - `Clock not set` (amber) when `NTPSynchronized` is false **and** the network is down. The today marker might be wrong in that situation. See D5.
   - Otherwise the normal US-16 text.
6. The log shows **one** INFO line when going offline (`sync: offline (NETWORK_DOWN); retrying in 1m`), DEBUG for each retry after that, and **one** INFO line when back online (`sync: back online after 23m`).
7. At **boot with no network**: the calendar appears normally (US-01 D3 already removed the network wait). Retries follow acceptance criterion 2, and the first sync after the network appears happens within about 10 s of it appearing.
8. The NM monitor and ClockTrust never block the main loop: every D-Bus call is async (`Gio.DBusProxy.new_for_bus` with a callback, and properties read from the proxy cache). In the devcontainer (no system bus), they log **one** INFO line (`network: NetworkManager not available; relying on sync results`) and do nothing else.
9. `RetryPolicy` is fully unit-tested (sequence, reset, retry_after, the non-transient rule, the cap at the interval).
10. On the Pi: take the network away for 20 minutes → the indicator shows offline within one retry, the retry timestamps in the log follow the schedule, and when the network is restored the events refresh within 15 s, without anyone touching anything.

---

## Design decisions (already made)

- **D1. The policy is pure**: `RetryPolicy.next_delay(result_kind, retry_after, interval_s) -> seconds`, with the state `failures: int`. `result_kind` is one of `success`, `transient`, `permanent`, `mixed` (some accounts succeeded: treat as success for scheduling). Backoff steps: `[60, 120, 240, 480, 900]`, and then `min(900, interval_s)`.
- **D2. The engine applies the policy** in its post-run step: `delay = policy.next_delay(...)`, then `_arm(delay)` instead of the plain interval. Add `SyncEngine.schedule_retry(delay)` as the public way to do it, and make US-16's arming go through the policy (with a success result, the policy returns the interval).
- **D3. Network state enum** (`calpi/system/networkmanager.py`): `ONLINE` (NM state 70), `LIMITED` (60, 50: site/local connectivity), `OFFLINE` (< 50, including asleep/disconnected), `UNKNOWN` (NM not available). Callback `on_change(old, new)`.
- **D4. "Offline" for the UI** = (the last run's account errors are all network-type) **or** (`NetworkMonitor.state in (OFFLINE, LIMITED)`). The sync result wins when NM is `UNKNOWN`.
- **D5. Clock trust**: `ClockTrust.synced: bool | None`. We **don't** try to guess the right date. We only warn when it may be wrong. Because systemd-timesyncd restores the last saved clock at boot, the date is only wrong if the device was off for a long time. The warning shows only while unsynced **and** offline, and disappears as soon as NTP syncs (after which US-10's clock detects the jump and fixes "today").
- **D6. The debounce for network-up** = 5 s. The minimum retry spacing = 60 s. A manual refresh (US-19) always bypasses the backoff.
- **D7. The indicator's states** have a priority: `running` > `clock-unsynced` > `offline` > `stale` > `ok`. One label, text and CSS class changed only when different.

---

## Implementation plan

### Step 1 — `calpi/sync/retry.py`
```python
TRANSIENT = {"NETWORK_DOWN", "DNS_FAILED", "TIMEOUT", "SERVER_ERROR", "RATE_LIMITED"}
NETWORKISH = {"NETWORK_DOWN", "DNS_FAILED", "TIMEOUT"}
STEPS = [60, 120, 240, 480, 900]

def classify(result: dict) -> str:
    if result.get("status") != "done": return "transient"          # crashed/timeout: retry soon-ish
    accs = result.get("accounts", [])
    if not accs: return "success"
    errs = [a.get("error") for a in accs]
    if any(e is None for e in errs): return "success"             # at least one account fine ("mixed" treated as success)
    if all(e in TRANSIENT for e in errs): return "transient"
    return "permanent"

def is_offline(result: dict) -> bool:
    accs = result.get("accounts", [])
    return bool(accs) and all(a.get("error") in NETWORKISH for a in accs)

class RetryPolicy:
    def __init__(self): self.failures = 0
    def next_delay(self, kind: str, retry_after: int | None, interval_s: int) -> int:
        if kind in ("success", "permanent"):
            self.failures = 0
            return interval_s
        step = STEPS[self.failures] if self.failures < len(STEPS) else min(900, interval_s)
        self.failures += 1
        delay = max(60, min(step, interval_s)) if self.failures > len(STEPS) else max(60, step)
        if retry_after: delay = max(delay, min(int(retry_after), 3600))
        return delay
```
Careful with one detail: the steps must never be **longer** than the normal interval (a 5-minute interval shouldn't back off to 15 minutes). **Decision: `delay = min(step, interval_s)`, but at least 60 s.** Adjust the sketch to match, and test it: interval 5 minutes → 60, 120, 240, 300, 300… Interval 60 minutes → 60, 120, 240, 480, 900, 900…

`retry_after` = the largest `retry_after` of the accounts in the result.

### Step 2 — Engine integration (`calpi/sync_engine.py`)
- `self.policy = RetryPolicy()`, `self.offline = False`, `self._offline_since = None`.
- In the post-run step: `kind = classify(r)`, `delay = self.policy.next_delay(kind, max_retry_after(r), interval_s)`. If there's a pending request, launch it (as before), else `_arm(delay)`.
- Offline transitions: `now_off = is_offline(r)`. If it changed, log INFO and call `state_callbacks` (the indicator updates).
- `request_sync(reason="manual")` resets nothing, but runs at once. After it, the policy applies again.
- **Don't reset the policy on network-up.** The resulting sync either succeeds (reset) or fails (continues the backoff).

### Step 3 — `calpi/system/networkmanager.py` (the monitoring part)
```python
NM_BUS, NM_PATH, NM_IFACE = "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager"

class NetworkMonitor:
    def __init__(self):
        self.state = NetState.UNKNOWN
        self.callbacks: list = []
        self._proxy = None
        Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None,
                                  NM_BUS, NM_PATH, NM_IFACE, None, self._on_proxy)

    def _on_proxy(self, _src, res):
        try:
            self._proxy = Gio.DBusProxy.new_for_bus_finish(res)
        except GLib.Error as e:
            log.info("network: NetworkManager not available (%s); relying on sync results", e.message); return
        if self._proxy.get_name_owner() is None:
            log.info("network: NetworkManager not running"); return
        self._proxy.connect("g-properties-changed", self._on_props)
        self._update(self._proxy.get_cached_property("State"))

    def _on_props(self, _proxy, changed, _invalidated):
        v = changed.lookup_value("State", None)
        if v is not None: self._update(v)

    def _update(self, variant):
        if variant is None: return
        new = _map_state(variant.get_uint32())
        if new != self.state:
            old, self.state = self.state, new
            log.info("network: %s -> %s", old.name, new.name)
            for cb in list(self.callbacks):
                try: cb(old, new)
                except Exception: log.exception("network callback failed")
```
- It's gi-based (Gio), so it sits outside `calpi/data` and `calpi/sync`, in `calpi/system/`. Put the pure state mapping `_map_state(int) -> NetState` in a no-gi helper so it can be tested.
- Keep a reference to the proxy on the object (and the object on the app), so it isn't garbage-collected and the signal keeps coming.
- In the app: `self.network = NetworkMonitor()`, and `self.network.callbacks.append(self._on_network_change)`. When the state becomes ONLINE from anything else → debounce 5 s → `self.sync.request_sync("network-up")`.

### Step 4 — `calpi/system/timesync.py`
The same pattern, on `org.freedesktop.timedate1` `/org/freedesktop/timedate1`, property `NTPSynchronized` (`b`). `timedate1` is bus-activated: creating the proxy **starts** `systemd-timedated` on demand (fine; it exits again when idle). **Caution**: `timedated` might not send property-change signals for `NTPSynchronized` (it's computed on request). So, in addition, **poll** it with an async `Get` call every 60 s **while unsynced** (stop polling once it's true). Use `proxy.call("org.freedesktop.DBus.Properties.Get", GLib.Variant("(ss)", ("org.freedesktop.timedate1", "NTPSynchronized")), ..., callback)`. Or, simpler: create a new proxy with `DO_NOT_LOAD_PROPERTIES` off each time. **Prefer the explicit async `Get` call.**

### Step 5 — `SyncIndicator` states
Extend `calpi/widgets/sync_indicator.py`:
```python
def compute_state(running, offline, clock_synced, net_state, last_success, now) -> tuple[str, str]:
    """Pure (no gi) → (css_state, text). Priority per D7."""
```
Put `compute_state` in `calpi/data/formatting.py` or a new `calpi/data/sync_text.py` (no gi), and test it thoroughly: every priority combination, "yesterday", "N days ago", and the 6-hour stale threshold. The widget only calls it and applies the result. Refresh on: engine state or result callbacks, network change, clock-trust change, and every minute (`app.clock.subscribe_minute`) so "3 days ago" and staleness stay current.

CSS:
```css
.sync-status          { font-size: 20px; color: @text_faint; }
.sync-status.offline  { color: @text_dim; }
.sync-status.stale, .sync-status.clock { color: #e0a040; }
```

### Step 6 — Tests
- `tests/test_retry.py`: D1 sequences for interval 5, 15, and 60 minutes; reset on success; `permanent` → interval; `retry_after=1800` → 1800; `mixed` → success; a crashed run → transient.
- `tests/test_sync_text.py`: `compute_state` cases.
- `tests/test_sync_engine.py` (extend): with the fake spawner, a transient result → armed with 60 s, then 120 s; a success → the interval; network-up → a request after the 5 s debounce (injectable timers).
- `_map_state`: 70 → ONLINE, 60 → LIMITED, 50 → LIMITED, 40 → OFFLINE (connecting), 20 → OFFLINE, 10 → OFFLINE (asleep), 0 → UNKNOWN.
- A devcontainer run with no system bus: the app starts, one INFO line, and nothing else goes wrong (smoke test).

### Step 7 — Offline test on the Pi (carefully)
Find out how the Pi is connected: `scripts/pi ssh 'nmcli -t -f DEVICE,TYPE,STATE device'`.
- **On Ethernet, with Wi-Fi unused**: ask the owner to unplug the router's WAN cable (the Pi keeps its LAN and your SSH, but loses the internet). That tests `DNS_FAILED`/`NETWORK_DOWN` while NM stays at 70 (or 60).
- **On Wi-Fi only**: schedule the recovery **before** cutting:
  ```bash
  scripts/pi ssh 'sudo systemd-run --on-active=20min --unit=calpi-wifi-restore /usr/bin/nmcli radio wifi on'
  scripts/pi ssh 'sudo nmcli radio wifi off'      # your SSH session drops now
  ```
  Wait 20 minutes. The Pi comes back by itself. Then read the logs: `scripts/pi logs -n 300 | grep -E "sync:|network:"`. Check the retry timestamps and the "back online" line. Ask the owner to look at the screen during the outage (or take a screenshot right after reconnecting, although by then it's back to normal: ask the owner for a phone photo during the outage).
- Boot offline (acceptance criterion 7): with the owner's help, power-cycle with the router off, then turn the router on after 5 minutes. Check the logs.

Record the observed schedule (a table of retry timestamps) in the hand-off notes.

---

## Files

| File | Change |
|---|---|
| `calpi/sync/retry.py` | New |
| `calpi/sync_engine.py` | Policy integration, offline tracking, `schedule_retry` |
| `calpi/system/__init__.py`, `networkmanager.py` (monitor), `timesync.py` | New |
| `calpi/data/sync_text.py` | New (pure indicator logic) |
| `calpi/widgets/sync_indicator.py` | States |
| `calpi/app.py` | Creates the monitors, network-up debounce |
| `calpi/style.css` | Indicator states |
| `tests/test_retry.py`, `tests/test_sync_text.py`, `tests/test_netstate.py` | New |

---

## Pitfalls

- **Synchronous D-Bus calls on the main thread** (`new_for_bus_sync`, `call_sync`). They can block for up to 25 s (the D-Bus default timeout) if a service hangs, and the watchdog (US-12) would fire. Always use async calls.
- **Retrying faster than every 60 s**, or hammering iCloud with AUTH_FAILED retries (it could lock the Apple ID's app passwords).
- **Blanking or dimming the calendar when offline.** Only the indicator changes.
- **Logging every retry at INFO.** It fills the capped journal over a long outage.
- **Cutting Wi-Fi on a Wi-Fi-only Pi without a scheduled restore.**
- **Turning on NM's external connectivity check** without asking the owner.

---

## Definition of done

- [ ] All acceptance criteria met. The retry and indicator tests pass.
- [ ] A real offline test done on the Pi, with the retry schedule recorded, and back online without intervention.
- [ ] The boot-offline check done (with the owner), or explicitly deferred.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `calpi/system/networkmanager.py`: `NetworkMonitor` (`state`, `callbacks`), `NetState` | US-23 (adds the Wi-Fi functions to the same module), US-24, US-31, US-41 |
| `app.network`, `app.clock_trust` | US-31, US-38, US-41 |
| `retry.classify(result)`, `retry.is_offline(result)`, `NETWORKISH`, `TRANSIENT` | US-18, US-38 |
| `sync_text.compute_state(...)` and the indicator states (`running`, `clock`, `offline`, `stale`, `ok`) | US-19 (a tappable indicator), US-38 (adds `error`) |
| `SyncEngine.schedule_retry`, `.offline` | US-19, US-31 |
