# US-24 — Saved network management

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P1 |
| **Blocked by** | US-23 Wi-Fi scan and connect |
| **Blocks** | — |
| **Phase** | 3. Setup and Settings (P1) |

## Story

> As a user, I want to see the current connection's status and forget saved networks.

## Context

US-23 gets the device onto a network. Over time the owner needs to **see how it's connected** (which network, how strong, whether the internet actually works) and to **remove networks** it shouldn't use any more: an old router, a neighbour's guest network used once, or the network that was set up with the Imager at flashing time.

This story adds two groups to the **Network** section from US-23:
1. **Current connection**: the network name, signal, IP address, router (gateway), and whether the internet is reachable. It also shows Ethernet when that's in use.
2. **Saved networks**: every saved Wi-Fi profile, each with a **Forget** button (and a confirmation, with a stronger warning when forgetting the network in use).

All reading is done with `nmcli -t` in worker threads (US-23's parsers and runner). Deleting uses `nmcli connection delete uuid <UUID>`, which involves no secrets.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-23** Wi-Fi scan and connect | The Network section (`"network"`, order 10), `wifi.split_terse`, `run_nmcli`, the command builders, the **polkit rule** (the app can delete connections), `WifiPicker` (which refreshes after changes), `ConfirmDialog` use | `ssh calpi 'ls /etc/polkit-1/rules.d/50-calpi-networkmanager.rules'`. `grep -n "def run_nmcli\|def split_terse" calpi/system/wifi.py`. Settings → Network lists networks on the Pi. |

### Soft dependencies
- **US-17** `NetworkMonitor` (`app.network`): refresh the status when the NM state changes.
- **US-16/US-18**: "Internet" reachability uses the last sync result and time as extra evidence (D3).

### External blockers
- **At least two saved Wi-Fi profiles** on the Pi, to test forgetting a non-active one (for example a phone hotspot saved via US-23). And a way back if you forget the active one (**Ethernet**, or the US-17 restore trick).

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| The Imager-created profile is called `preconfigured`, not by its SSID | Show the **SSID** (`802-11-wireless.ssid`), and show the profile name only if it differs, as a dimmed second line. |
| Several profiles for the same SSID | List them all, with "(duplicate)" on the extra ones. Forget works per UUID. |
| IP details | `nmcli -t -f IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show wlan0` (the multi-value fields come as `IP4.ADDRESS[1]:...`). Parse the keys with their index suffixes. |

---

## Scope

### In scope
- A "Current connection" group: interface type (Wi-Fi/Ethernet), SSID, signal (bars + %), IPv4 address, gateway, DNS servers, internet status.
- A "Saved networks" group: SSID (+ profile name if different), "Connected" marker, auto-connect indicator, and a **Forget** button per profile.
- Forget flow with confirmation. Forgetting the active network gives a stronger warning, and then the device disconnects.
- Refreshing: on section show, after forget/connect, on an NM state change, and every 10 s while visible (just the status, **not** a rescan).
- Parsers in `calpi/system/wifi.py` (pure) with tests.

### Out of scope
- Editing saved profiles (password changes: forget and reconnect instead), priorities, static IP, IPv6 details, and Ethernet configuration.
- A "Disconnect" button (not requested). Forget covers the need.

---

## Acceptance criteria

1. **Current connection** shows, when connected over Wi-Fi: "Wi-Fi · <SSID>", signal bars and a percentage, "IP address 192.168.1.23", "Router 192.168.1.1", "DNS 192.168.1.1", and **Internet**: "Working" / "No internet" / "Checking…" (D3). Over Ethernet: "Ethernet" plus the IP details (no signal). When not connected: "Not connected", with a hint pointing to the network list below.
2. The status is read in a worker thread and appears within 2 s of opening the section. While visible, it refreshes every **10 s**, and straight away after connect/forget and NM state changes. The rows update only when the text changed.
3. **Saved networks** lists every `802-11-wireless` profile (never Ethernet, loopback, or other types). Each row shows the SSID, the profile name in dimmed text if it differs, "Connected" if it's active, and "Won't connect automatically" if autoconnect is off. It's sorted: active first, then by last-used time (`TIMESTAMP`), newest first.
4. **Forget** (a button ≥ 160 × 72 per row, styled as destructive):
   - A non-active network → confirm "Forget <SSID>? calpi won't join it automatically any more." → delete → the toast "Forgot <SSID>" → the list refreshes.
   - The **active** network → confirm "Forget <SSID>? calpi will disconnect now and stay offline until you connect to another network." (destructive style) → delete → the device disconnects → the status shows "Not connected" → the network list (US-23) is still there to reconnect.
   - The **only** saved network while there's no Ethernet → the same as the active case, plus the extra line "This is the only saved network."
5. A delete failure (for example no permission) → the toast "Couldn't forget <SSID>" and a WARNING in the log, with the list unchanged.
6. **Internet status logic** (D3) is pure and unit-tested.
7. The parsers (`parse_saved`, `parse_device_show`) are unit-tested with fixtures, including escaped colons, the `IP4.ADDRESS[1]`-style keys, several DNS servers, and missing fields.
8. No blocking calls on the main thread. Refreshes don't overlap (only one worker at a time; ignore ticks while one is running).
9. The whole section still meets the target-size rules (`CALPI_CHECK_TARGETS=1`).

---

## Design decisions (already made)

- **D1. Commands** (lists, `LC_ALL=C`, through `run_nmcli`):
  - Active device: `nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device` → pick the `connected` device, preferring Ethernet if both are connected (that's the route NM uses by default).
  - Details: `nmcli -t -f GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show <dev>`.
  - Signal for Wi-Fi: from the latest `device wifi list` (the `IN-USE` row), **without** a rescan (`--rescan no`).
  - Saved: `nmcli -t -f NAME,UUID,TYPE,AUTOCONNECT,TIMESTAMP,ACTIVE connection show`, plus the SSID per wifi profile (US-23's `cmd_connection_ssid`). Cache the SSID per UUID for the session (profiles rarely change), and invalidate it after forget/connect.
  - Forget: `nmcli connection delete uuid <UUID>`.
- **D2. The UI structure**: the Network section becomes three groups, in this order: **Current connection** (this story), **Networks** (US-23's `WifiPicker`), **Saved networks** (this story). In wizard mode (US-32), only `WifiPicker` is shown.
- **D3. Internet status** (`wifi.internet_status(nm_state, last_sync_result, last_sync_age_s)`):
  - NM state 70 (`CONNECTED_GLOBAL`) and a recent successful sync (< 30 min) → "Working".
  - NM state 70 and no recent success, or the last sync failed with a network-type error → "No internet" (hint: "Connected to <SSID> but calpi can't reach the internet. Check the router.").
  - NM state 60/50 (site or local only) → "No internet".
  - NM state unknown (no NM) → derived from the sync result only, or "Checking…" before the first sync.
  - **No active probing** of external hosts: the sync results are the probe. (That keeps it private and cheap.)

---

## Implementation plan

### Step 1 — Parsers (`calpi/system/wifi.py`)
```python
@dataclass(frozen=True)
class SavedWifi:
    uuid: str; name: str; ssid: str; autoconnect: bool; last_used: int; active: bool

def parse_saved(conn_stdout: str) -> list[dict]: ...           # NAME,UUID,TYPE,AUTOCONNECT,TIMESTAMP,ACTIVE → only 802-11-wireless
def parse_device_status(stdout: str) -> list[dict]: ...        # DEVICE,TYPE,STATE,CONNECTION
def parse_device_show(stdout: str) -> dict:                    # {"connection": ..., "ip4": ["192.168.1.23/24"], "gateway": ..., "dns": [...]}
    # lines like "IP4.ADDRESS[1]:192.168.1.23/24" — split on the FIRST unescaped ':' only
def active_device(rows) -> dict | None: ...                    # prefer ethernet if both connected
def internet_status(nm_state, last_result, last_success_age_s) -> tuple[str, str | None]: ...  # (label, hint)
```
Note: in `device show -t` output, the **key** is before the first `:` and the value after it. Values like IPv6 addresses contain `:` (escaped as `\:`). Use `split_terse` with a max-split of 1, or split once and then unescape.

Strip the prefix length for display (`192.168.1.23/24` → `192.168.1.23`).

### Step 2 — The status group
```python
class ConnectionStatusGroup(SettingsGroup):
    def __init__(self, app):
        super().__init__("Current connection")
        self.kind = InfoRow("Connection", "…"); self.signal = InfoRow("Signal", "")
        self.ip = InfoRow("IP address", ""); self.gw = InfoRow("Router", ""); self.dns = InfoRow("DNS", "")
        self.inet = InfoRow("Internet", "Checking…")
        ...
    def refresh(self):
        if self._busy: return
        self._busy = True
        run_in_thread(self._collect, on_done=self._apply, on_error=self._failed)
    def _collect(self) -> dict:           # worker: device status → active device → device show → signal (no rescan)
        ...
    def _apply(self, info): ...           # main thread: set_text_if_changed on each row; hide the signal row for ethernet
```
The internet status is computed on the main thread (it needs `app.network.state` and `app.sync.last_result`/`last_success_wall`, which are main-thread objects).

The 10 s timer runs only while the section is visible (`on_show`/`on_hide` from US-22). Subscribe to `app.network.callbacks` in the section, and unsubscribe in `dispose`.

### Step 3 — The saved networks group
```python
class SavedNetworksGroup(SettingsGroup):
    def refresh(self): run_in_thread(self._collect_saved, on_done=self._render)
    def _render(self, items: list[SavedWifi]):
        key = tuple((s.uuid, s.ssid, s.active, s.autoconnect) for s in items)
        if key == self._last_key: return
        ... rebuild rows (small list, rebuilding is fine)
    def _forget(self, s: SavedWifi, only_one: bool):
        body = ...  # D2 texts per case
        self.app.window.confirm.ask(f"Forget {s.ssid}?", body, "Forget", lambda: self._do_forget(s), destructive=True)
    def _do_forget(self, s):
        run_in_thread(lambda: run_nmcli(cmd_delete(s.uuid), 15),
                      on_done=lambda _: (self.app.toast(f"Forgot {s.ssid}"), self._after_change()),
                      on_error=lambda e: (log.warning("forget %s failed: %s", s.uuid, e), self.app.toast(f"Couldn't forget {s.ssid}")))
```
`_after_change()` refreshes all three groups (status, the saved list, and a `WifiPicker` rescan with `--rescan auto`), and clears the SSID cache.

"Only one" = only one saved Wi-Fi profile **and** no connected Ethernet device.

### Step 4 — Put them in the section
Update `NetworkSection` (US-23): in settings mode, the groups are `ConnectionStatusGroup`, `WifiPicker`, `SavedNetworksGroup`. After a successful connect in `WifiPicker` → call `_after_change()`.

### Step 5 — Tests
- `tests/test_wifi_parse.py` (extend): `parse_saved` (skips ethernet and loopback; the `preconfigured` name; `TIMESTAMP` 0 for never used), `parse_device_show` (several DNS entries, escaped IPv6, no gateway), `active_device` preferring Ethernet, `internet_status` truth table.
- GTK (fake runner): the forget flow for the active and non-active cases shows the right dialog text. A failure → the toast.

### Step 6 — Pi check
1. Save a second network (a phone hotspot) through US-23. Settings → Network: both are listed, the active one marked. Take a screenshot.
2. Forget the **non-active** one → gone from the list, and `ssh calpi 'nmcli -t -f NAME,TYPE connection show'` confirms.
3. **Only on Ethernet** (or with the scheduled restore): forget the **active** Wi-Fi → the status shows "Not connected" (or Ethernet). Reconnect using US-23 (the owner types the password).
4. Unplug the WAN at the router (the owner) → "No internet" within a sync cycle, or straight away if a sync fails.

---

## Files

| File | Change |
|---|---|
| `calpi/system/wifi.py` | Parsers, `internet_status` |
| `calpi/widgets/settings/network.py` | `ConnectionStatusGroup`, `SavedNetworksGroup`, section layout |
| `tests/test_wifi_parse.py`, `tests/fixtures/nmcli/*` | More cases |

---

## Pitfalls

- **Deleting by name** (`nmcli connection delete <name>`): names can be duplicated or ambiguous. Always use the UUID.
- **Listing non-Wi-Fi profiles** with a Forget button: deleting the Ethernet profile would be bad. Filter on type.
- **Probing the internet** with external requests: use the sync evidence (D3).
- **Rescanning every 10 s** for the status: only the status refreshes. Scans are US-23's 20 s cycle.
- **Forgetting the active network over a Wi-Fi SSH session** without a fallback.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] Forget of non-active and active networks checked on the Pi, and reconnected afterwards.
- [ ] Screenshots of the status and saved lists recorded.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `wifi.internet_status(...)` → (label, hint) | US-31 (the Status screen's Network block), US-38 |
| `ConnectionStatusGroup` (can be embedded read-only) | US-31 |
| `wifi.parse_device_show`, `active_device` | US-31, US-41 (to decide if the weather fetch is worth trying) |
