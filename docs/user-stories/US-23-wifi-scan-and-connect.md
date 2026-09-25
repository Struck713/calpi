# US-23 — Wi-Fi scan and connect

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P0 |
| **Blocked by** | US-01 Kiosk OS provisioning, US-21 On-screen keyboard, US-22 Settings shell |
| **Blocks** | US-24 Saved network management, US-31 Status screen, US-32 First-time setup wizard, US-41 Weather |
| **Phase** | 3. Setup and Settings |

## Story

> As a user, I want to see nearby Wi-Fi networks, pick one, enter its password and connect.

## Context

"Self-contained" is a project goal: a new owner must be able to get the device online **from its own screen**, with no SSH, no Imager settings, and no keyboard. This story builds the **Network** section of Settings: a list of nearby networks, a password page with the on-screen keyboard (US-21), connecting with clear feedback, and a way to join a hidden network. The same picker is reused in the setup wizard (US-32).

The Pi runs **NetworkManager** (Pi OS Bookworm and later). The app runs as the unprivileged `kiosk` user, so it needs a **polkit rule** to control NetworkManager. And **Wi-Fi passwords must never go on a command line** (other processes can see command lines in `ps` and `/proc`), so connecting goes through **NetworkManager's D-Bus API**, where the password travels inside the D-Bus message. Scanning and listing use `nmcli -t` in a worker thread, which is simple and easy to debug.

The Pi 3B's radio is **2.4 GHz only**. 5 GHz-only networks never show up, and the UI has to say so, otherwise people think the device is broken.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-01** Kiosk OS provisioning | NetworkManager managing `wlan0`, **the Wi-Fi country set** (otherwise rfkill blocks Wi-Fi), `setup-pi.sh` to extend, and the `kiosk` user in a real logind session on seat0 | `ssh calpi 'nmcli -t -f DEVICE,TYPE,STATE device; nmcli radio wifi; rfkill list wifi'` → `wlan0:wifi:...`, `enabled`, not soft-blocked. |
| **US-21** On-screen keyboard | `window.keyboard.attach(entry, "password", done_label="Connect", on_done=...)`, `make_password_field()`, the rule to keep fields in the top ~540 px | `grep -n "def attach\|def make_password_field" calpi/widgets/keyboard.py` |
| **US-22** Settings shell | `register_section`, `SectionContext.push_page/pop_page`, the rows, `ConfirmDialog`, `BlockingOverlay`, `app.toast` | `grep -n "def register_section\|class BlockingOverlay" calpi/widgets/settings/shell.py calpi/widgets/overlays.py` |

### Soft dependencies
- **US-17** created `calpi/system/networkmanager.py` with `NetworkMonitor` (the state signal). **Add the Wi-Fi functions to the same module.** If US-17 isn't done, create the module and leave the monitor to US-17.
- **US-03** for the Pi check. There's no other way to test Wi-Fi.

### External blockers

| Blocker | What to do |
|---|---|
| **At least one real 2.4 GHz network** you're allowed to join, and its password | The owner's home network. **The owner types the password on the device** (with the mouse and the OSK, or the physical keyboard). Never ask for it in chat. Ideally also a **second** network (a phone hotspot set to 2.4 GHz) to test switching and a wrong password. |
| **A way back if Wi-Fi breaks while you're connected over Wi-Fi** | Before testing connects on a Wi-Fi-only Pi, **connect the Pi by Ethernet**, or schedule a restore (see US-17 step 7). Otherwise a bad connect cuts you off. |
| **polkit on the Pi** (`polkitd`, with JavaScript `.rules` support: polkit ≥ 0.106, and Bookworm has 122) | Check: `ssh calpi 'pkaction --version; ls /etc/polkit-1/rules.d/'`. |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| `nmcli` works over SSH with `sudo -u kiosk` but not from the app (or the other way round) | polkit decides per **session**: an SSH `sudo` session is inactive and non-local. The **app** runs in the active seat0 session. Our rule grants by **user** (`kiosk`), so both behave the same once it's installed. Test from the app. |
| `Not authorized to control networking` | The polkit rule is missing or wrong. Check `journalctl -u polkit` on the Pi. |
| A wrong password connects "forever" or hangs | NM retries asking for secrets. There's no secret agent, so it fails with `NO_SECRETS` after a while. Our 45 s timeout and reason mapping handle it (D6). **Delete the failed new profile.** |
| `nmcli -t` escaping breaks the parser | In terse mode, `:` inside values is escaped as `\:` and `\` as `\\`. BSSIDs contain colons. Write a proper splitter (step 2) and test it with fixtures. |
| Scans return nothing right after boot | NM may not have scanned yet. Use `--rescan yes` on the first scan, then `auto`. A rescan takes about 3–10 s, so always run it in a worker. |
| D-Bus variant building from Python is fiddly | Build a **plain Python dict** first (pure, tested), then convert with a small `to_variant()` helper (`a{sa{sv}}`). The SSID must be `ay` (bytes), not a string. |

---

## Scope

### In scope
- Provisioning: the polkit rule (a `setup-pi.sh` section).
- `calpi/system/wifi.py` (no gi): `nmcli` command builders and **parsers** (scan list, saved connections, device status), and the merge, dedupe, and sort logic.
- `calpi/system/networkmanager.py` (Gio): `connect_wifi(ssid, password, security, hidden) → async result`, `activate_saved(uuid)`, `delete_connection(uuid)`, active-connection state tracking, and failure reason mapping.
- The **Network** settings section: current connection summary (brief; details are US-24), network list, rescan, password page, hidden network page, connect flow, errors.
- A reusable `WifiPicker` for US-32.
- The 2.4 GHz notice.

### Out of scope
- Forgetting networks, full status details, and the saved-networks list (US-24).
- Enterprise Wi-Fi (802.1X/EAP): shown as "not supported".
- Captive portals (hotel or guest Wi-Fi sign-in pages): out of scope. Say so if connectivity is limited.
- Ethernet settings, static IP.

---

## Acceptance criteria

1. **Permissions**: after provisioning, the app (as `kiosk`) can scan, connect, and delete connections without prompts. The polkit rule only grants `org.freedesktop.NetworkManager.*` actions, and only to the user `kiosk`.
2. **List**: opening Settings → Network shows (within 10 s of opening, with the first result as soon as it's available) the nearby networks. Each row shows: the SSID, a signal indicator (4 levels, text bars `▂▄▆█`, no icon theme), "Secured" or "Open", and a ✓ "Connected" on the current one. Rows are ≥ 88 px. Empty and hidden SSIDs are left out. The same SSID seen on several access points is shown **once**, with the strongest signal.
3. **Sorting**: the connected network first, then saved (known) networks, then by signal (strongest first).
4. **Scanning** only while the section is visible: once on show (`--rescan yes`), then every **20 s** (`--rescan auto`), stopped on hide. A **Rescan** button triggers one at once (disabled while a scan is running). No scan ever blocks the UI.
5. **Connect to a saved network**: tapping it activates the saved profile, with no password prompt.
6. **Connect to a new secured network**: tapping it opens a password page (`push_page`) with the SSID as the title, a password field with a Show/Hide toggle, the OSK (purpose `password`, done label "Connect"), and a Connect button. A WPA password shorter than 8 or longer than 63 characters shows an inline error without trying (except 64 hex digits, which is allowed as a raw PSK).
7. **While connecting**: `BlockingOverlay` "Connecting to <SSID>…" (with a **Cancel** button that deactivates the attempt), for at most **45 s**.
8. **Result**: success → overlay closed, a toast "Connected to <SSID>", the list shows it as connected, and a sync is requested (`app.sync.request_sync("network-connected")` if US-16 exists). A wrong password → back to the password page with an inline message "Wrong password for <SSID>. Check it and try again." (the field is kept, the text selected), and **the failed profile is deleted**. Timeout or network not found → "Couldn't connect to <SSID>. Move closer to the router or try again." Other failures → "Couldn't connect (<short reason>)".
9. **Open networks**: a confirm dialog "<SSID> is an open network. Anyone nearby can see the traffic. Connect anyway?" then connect without a password.
10. **Hidden networks**: an "Other network…" row at the bottom → a page with SSID (the OSK `text` purpose, no autocapitalisation), a security choice (WPA/WPA2/WPA3 Personal, or None), a password → connect with `hidden=true`.
11. **Unsupported**: networks whose security is 802.1X/Enterprise are listed but greyed out, with "Enterprise networks aren't supported".
12. **The 2.4 GHz note**: a dimmed note under the list: "calpi can only see 2.4 GHz networks. If yours doesn't appear, check that your router's 2.4 GHz band is on."
13. **Secrets**: the Wi-Fi password never appears in logs, command-line arguments, settings, or the event database. (It lives only in NM's own protected storage, `/etc/NetworkManager/system-connections/*.nmconnection`, mode 0600, root-owned.) A test checks the command builders never include a password.
14. **Wi-Fi radio off** (rfkill or `nmcli radio wifi off`): the section shows "Wi-Fi is turned off" and a **Turn on** button (`nmcli radio wifi on`).
15. `WifiPicker` can be embedded in the wizard (`ctx.mode == "wizard"`) and gives its result to a callback (`on_connected(ssid)`), with no Settings-specific assumptions.

---

## Design decisions (already made)

- **D1. The polkit rule** (`/etc/polkit-1/rules.d/50-calpi-networkmanager.rules`):
  ```js
  // Allow the calpi kiosk user to manage networking without prompts.
  polkit.addRule(function(action, subject) {
      if (subject.user === "kiosk" && action.id.indexOf("org.freedesktop.NetworkManager.") === 0) {
          return polkit.Result.YES;
      }
  });
  ```
  Installed by `setup-pi.sh` (a new idempotent section), mode 0644, followed by `systemctl restart polkit`.
- **D2. Read-only operations use `nmcli -t` in `run_in_thread`**:
  - Scan: `nmcli -t -f IN-USE,BSSID,SSID,CHAN,FREQ,SIGNAL,SECURITY device wifi list --rescan {yes|auto} ifname wlan0`
  - Saved: `nmcli -t -f NAME,UUID,TYPE,AUTOCONNECT,TIMESTAMP connection show`, then for each `802-11-wireless` connection: `nmcli -t -g 802-11-wireless.ssid,802-11-wireless-security.key-mgmt connection show uuid <UUID>`
  - Device and radio state: `nmcli -t -f WIFI general` and `nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device`
  - Radio on: `nmcli radio wifi on`. Activate saved: `nmcli --wait 45 connection up uuid <UUID>` (no secrets involved). Delete: `nmcli connection delete uuid <UUID>`.
  - Always call it through `subprocess.run([...], capture_output=True, text=True, timeout=...)` with a list (no shell), `env={"LC_ALL": "C", **os.environ}` for stable output, and **never with a password argument**.
- **D3. Connecting with a new secret uses D-Bus**: `org.freedesktop.NetworkManager.AddAndActivateConnection(a{sa{sv}} settings, o device, o specific_object)` on the system bus, async through `Gio.DBusConnection.call`. The device path comes from `GetDeviceByIpIface("wlan0")`. `specific_object = "/"`.
- **D4. The connection settings dict** (built in pure Python by `wifi.build_connection_settings`):
  ```python
  {"connection": {"id": ssid, "type": "802-11-wireless", "autoconnect": True},
   "802-11-wireless": {"ssid": ssid.encode(), "mode": "infrastructure", "hidden": hidden},
   "802-11-wireless-security": {"key-mgmt": "wpa-psk", "psk": password},     # omitted for open networks
   "ipv4": {"method": "auto"}, "ipv6": {"method": "auto"}}
  ```
  Security mapping from the scan's `SECURITY` field: contains `802.1X` → unsupported. Contains `WPA3` and **not** `WPA2`/`WPA1` → `key-mgmt: "sae"`. Contains `WPA`/`WPA2` → `"wpa-psk"` (NM negotiates WPA2/WPA3 transition mode). `WEP` → unsupported (it's obsolete; say so). Empty or `--` → open (no security block).
  Note: WPA3-SAE support on the Pi 3B's brcmfmac chip with the stock firmware may be limited. If SAE fails, report "This network uses WPA3, which this device may not support" (D6).
- **D5. Watching activation**: `AddAndActivateConnection` returns `(settings_path, active_connection_path)`. Subscribe to `org.freedesktop.NetworkManager.Connection.Active` → `StateChanged(u state, u reason)` on the active path (through `Gio.DBusConnection.signal_subscribe`). `state == 2` (ACTIVATED) → success. `state == 4` (DEACTIVATED) → failure with a reason. Also a 45 s timeout (`GLib.timeout_add_seconds`) → call `DeactivateConnection(active_path)` and report TIMEOUT. **Always unsubscribe and remove the timeout** when finished.
- **D6. Reason mapping** (pure, in `wifi.py`): `NM_ACTIVE_CONNECTION_STATE_REASON_NO_SECRETS (9)` and the device reason `NO_SECRETS (7)` / `SUPPLICANT_DISCONNECT (8)` → `WRONG_PASSWORD`. `SUPPLICANT_TIMEOUT (11)`, `SSID_NOT_FOUND (53)`, `CONNECT_TIMEOUT (5)`, our own timeout → `NOT_REACHABLE`. `USER_DISCONNECTED` / our cancel → `CANCELLED`. Otherwise `FAILED(<code>)`. **Check these numbers against the NM version's `nm-dbus-interface.h`** (`NMActiveConnectionStateReason`, `NMDeviceStateReason`) and record them. When the active-connection reason is generic, also read the device's `StateReason` property for detail.
- **D7. After a failed *new* connection**, delete the settings object that `AddAndActivateConnection` created (`org.freedesktop.NetworkManager.Settings.Connection.Delete` on `settings_path`), so wrong passwords are never saved and never retried automatically.
- **D8. `WifiPicker`** is the list widget with its own scan loop and connect flow. The Network section wraps it (adding the current-connection summary, and US-24's saved-network management later). The wizard wraps it with "Skip" and "Next".

---

## Implementation plan

### Step 1 — Provisioning (polkit)
Add to `.claude/skills/pi-kiosk-setup/setup-pi.sh`:
```bash
echo "==> polkit: kiosk may manage NetworkManager"
install -d -m 0755 /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/50-calpi-networkmanager.rules <<'EOF'
// calpi: allow the kiosk user to manage networking without prompts (US-23)
polkit.addRule(function(action, subject) {
    if (subject.user === "kiosk" && action.id.indexOf("org.freedesktop.NetworkManager.") === 0) {
        return polkit.Result.YES;
    }
});
EOF
chmod 0644 /etc/polkit-1/rules.d/50-calpi-networkmanager.rules
systemctl restart polkit || true
```
Copy it over and run it. Check: `ssh calpi 'sudo -u kiosk nmcli -t -f SSID,SIGNAL device wifi list --rescan yes | head'` works without an authorisation error.

### Step 2 — `calpi/system/wifi.py` (pure, no gi)
```python
def split_terse(line: str) -> list[str]:
    """Split an nmcli -t line on unescaped ':' and unescape '\\:' and '\\\\'."""
    out, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1]); i += 2; continue
        if c == ":":
            out.append("".join(cur)); cur = []; i += 1; continue
        cur.append(c); i += 1
    out.append("".join(cur))
    return out

@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: int              # 0..100
    security: str            # raw nmcli SECURITY
    kind: str                # "open" | "psk" | "sae" | "enterprise" | "wep"
    in_use: bool
    saved_uuid: str | None
    freq_mhz: int | None

def parse_scan(stdout: str) -> list[dict]: ...
def classify_security(sec: str) -> str: ...
def merge(scan_rows, saved: dict[str, str]) -> list[WifiNetwork]: ...    # dedupe by SSID, strongest signal, mark saved/in-use
def sort_networks(nets) -> list[WifiNetwork]: ...
def signal_bars(signal: int) -> str: ...        # "▂", "▂▄", "▂▄▆", "▂▄▆█"
def validate_psk(password: str) -> str | None:   # error text or None
def build_connection_settings(ssid, password, kind, hidden) -> dict: ...
def map_failure(active_reason: int | None, device_reason: int | None, timed_out: bool, cancelled: bool) -> str: ...
# command builders (lists, never containing a password):
def cmd_scan(rescan: str) -> list[str]: ...
def cmd_saved() -> list[str]: ...
def cmd_connection_ssid(uuid: str) -> list[str]: ...
def cmd_up(uuid: str) -> list[str]: ...
def cmd_delete(uuid: str) -> list[str]: ...
def cmd_radio(on: bool) -> list[str]: ...
def run_nmcli(cmd: list[str], timeout: float) -> str:     # subprocess.run; raises NmcliError(stderr_first_line)
```
SSIDs can hold any bytes. `nmcli` prints them as UTF-8 where possible. Treat the SSID as a display string, and **use the same string** in `build_connection_settings` (`.encode("utf-8")`). SSIDs that aren't valid UTF-8 are rare: accept that limitation, and note it.

### Step 3 — `calpi/system/networkmanager.py` (Gio): the connect flow
```python
class WifiConnector:
    """One connect attempt at a time. All callbacks on the main loop."""
    def connect_new(self, ssid, password, kind, hidden, on_result): ...
    def activate_saved(self, uuid, on_result): ...       # nmcli --wait 45 connection up uuid ... in run_in_thread
    def cancel(self): ...
```
`connect_new`:
1. `bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)`. **Don't** call `_sync` on the main thread (it can block): use `Gio.bus_get(Gio.BusType.SYSTEM, None, cb)`, or keep one connection obtained at startup asynchronously.
2. `GetDeviceByIpIface("wlan0")` → device path (async call).
3. `AddAndActivateConnection(to_variant(settings), device_path, "/")` (async) → `(settings_path, active_path)`.
4. `signal_subscribe(sender="org.freedesktop.NetworkManager", interface_name="org.freedesktop.NetworkManager.Connection.Active", member="StateChanged", object_path=active_path, ...)`.
5. On ACTIVATED → `on_result(("ok", None))`. On DEACTIVATED → read `/org/freedesktop/NetworkManager/Devices/N` `StateReason` (async Properties.Get) → `map_failure(...)` → delete `settings_path` (async) → `on_result(("error", code))`.
6. On timeout or cancel → `DeactivateConnection(active_path)` → treat as `NOT_REACHABLE` or `CANCELLED` → delete `settings_path`.

`to_variant(d)`:
```python
def to_variant(settings: dict) -> GLib.Variant:
    def v(x):
        if isinstance(x, bool): return GLib.Variant("b", x)
        if isinstance(x, int):  return GLib.Variant("u", x)
        if isinstance(x, bytes): return GLib.Variant("ay", x)
        if isinstance(x, str):  return GLib.Variant("s", x)
        raise TypeError(type(x))
    return GLib.Variant("(a{sa{sv}}oo)", ...)   # build the outer tuple at the call site
```
The inner type is `a{sa{sv}}`: `{group: {key: variant}}`. Check the exact construction in PyGObject (`GLib.Variant("a{sa{sv}}", {g: {k: v(x) for k, x in kv.items()} for g, kv in settings.items()})`).

**If an existing saved profile has the same SSID** but the user enters a new password (because the saved one failed): delete the old profile first, then add the new one. Otherwise NM ends up with duplicates.

### Step 4 — `WifiPicker` widget (`calpi/widgets/settings/network.py`)
```
WifiPicker (Gtk.Box vertical)
├─ status line: "Scanning…" / "12 networks" / "Wi-Fi is turned off [Turn on]"
├─ SettingsGroup "Networks" → one NetworkRow per WifiNetwork (reuse rows; rebuild the group's children only when the list changed)
│     NetworkRow: SSID (28px) | "Secured"/"Open" · bars | "✓ Connected" or chevron "›"
├─ row "Other network…"
├─ note (2.4 GHz)
└─ [Rescan] button
```
The scan loop:
```python
def on_show(self):
    self._visible = True
    self._scan(rescan="yes")
    self._timer = GLib.timeout_add_seconds(20, self._on_tick)
def on_hide(self):
    self._visible = False
    if self._timer: GLib.source_remove(self._timer); self._timer = 0
def _scan(self, rescan):
    if self._scanning: return
    self._scanning = True
    run_in_thread(lambda: (wifi.parse_scan(run_nmcli(cmd_scan(rescan), 20)), self._saved_ssids()),
                  on_done=self._on_scan, on_error=self._on_scan_error)
def _on_scan(self, res):
    self._scanning = False
    if not self._visible: return          # the section was closed meanwhile
    ...
```
Only rebuild the rows when the list of `(ssid, in_use, saved, kind, bars)` changed. Signal jitter would otherwise rebuild everything every 20 s: compare the **bars**, not the raw signal numbers.

The password page (pushed with `ctx.push_page(page, ssid)`): the title, `make_password_field()` (US-21), an inline error label, and a Connect button (≥ 200 × 88), placed in the top ~540 px. `window.keyboard.attach(entry, "password", done_label="Connect", on_done=self._try_connect)`. Focus the entry on show (the OSK appears).

`_try_connect` → `validate_psk` → `BlockingOverlay.show(f"Connecting to {ssid}…", on_cancel=connector.cancel)` → `connector.connect_new(...)` → on the result: hide the overlay, then success (toast, pop the page, refresh, request a sync) or failure (inline message, select the password text).

### Step 5 — The Network section
Register `SectionSpec("network", "Network", 10, NetworkSection)`. The section contains:
- **A current-connection summary** (a simple `InfoRow`: "Connected to <SSID>" or "Not connected", refreshed on show and after connecting). US-24 expands this.
- The `WifiPicker`.

Hook it into `NetworkMonitor` (US-17): when the NM state changes while the section is visible, refresh the summary and trigger a scan.

### Step 6 — Tests
- `tests/test_wifi_parse.py` with fixtures (`tests/fixtures/nmcli/*.txt`, captured from the Pi and **anonymised**: change the SSIDs and BSSIDs): the escaped colons in BSSIDs, SSIDs containing `:` and `\`, empty SSIDs dropped, the same SSID on several APs merged, `IN-USE` `*` detected, security classification of `WPA2`, `WPA1 WPA2`, `WPA3`, `WPA2 WPA3`, `WPA2 802.1X`, `WEP`, `--`, and empty.
- `sort_networks`, `signal_bars` boundaries, `validate_psk` (7, 8, 63, 64 hex, 64 non-hex, 65).
- `build_connection_settings` for open, psk, sae, and hidden. **Assert that no command builder output ever contains a given password**: generate a password, build every command, and check.
- `map_failure` for each mapped reason.
- The GTK layer: a fake connector (it gets `on_result` called by the test) to check the page flow in Broadway: wrong password → the inline error; success → toast and pop.

### Step 7 — Check on the Pi (with care)
**Before anything else**: plug the Pi into **Ethernet** (ask the owner), so a Wi-Fi mistake can't lock you out. If Ethernet isn't possible, schedule a restore of the current connection first:
`sudo systemd-run --on-active=15min --unit=calpi-wifi-restore nmcli connection up uuid <current-uuid>`.

1. Deploy and provision (polkit). Open Settings → Network with the mouse. The list appears. Take a screenshot.
2. **Wrong password** on the owner's network (the owner types a wrong one) → the inline error within 45 s. Then `ssh calpi 'nmcli -t -f NAME connection show'` shows **no** new profile.
3. **Right password** (the owner types it) → the toast, and connected. `nmcli -t -f NAME,DEVICE connection show --active` shows it on `wlan0`.
4. Hidden network: if the owner can set one up (a phone hotspot with a hidden SSID), test it. Otherwise note it as not tested on hardware.
5. `sudo nmcli radio wifi off` (**only when on Ethernet**) → the section shows "Wi-Fi is turned off" → Turn on works.
6. Check the logs contain no password: `scripts/pi logs -n 500 | grep -c <a unique substring of the password the owner used>` → **ask the owner to run this themselves** with `!` (so the password isn't in your context), expecting `0`.
7. `CALPI_CHECK_TARGETS=1` → no small targets on the list or password page (temporary drop-in; remove it afterwards).

---

## Files

| File | Change |
|---|---|
| `.claude/skills/pi-kiosk-setup/setup-pi.sh` | The polkit section |
| `calpi/system/wifi.py` | New |
| `calpi/system/networkmanager.py` | `WifiConnector` (plus US-17's monitor) |
| `calpi/widgets/settings/network.py` | New: `WifiPicker`, `NetworkSection`, the password and hidden-network pages |
| `calpi/widgets/settings/__init__.py` | Imports `network` |
| `calpi/style.css` | Network row styles |
| `tests/test_wifi_parse.py`, `tests/fixtures/nmcli/*` | New |

---

## Pitfalls

- **A password in `argv`** (`nmcli ... password X`). Never. Use D-Bus (D3).
- **Synchronous D-Bus or `subprocess` on the main thread.** Scans take seconds, and the watchdog is 30 s.
- **Keeping failed profiles.** They're retried automatically in a loop, and pile up.
- **Rebuilding the list every 20 s** on signal jitter.
- **Testing Wi-Fi changes over a Wi-Fi SSH session** without a fallback.
- **Forgetting the 2.4 GHz note**: it's the number one "my network is missing" cause.
- **Treating `IN-USE` from a stale scan as the truth**: refresh the summary from the device state (`nmcli device`) after connecting.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] Wrong password, right password, radio off/on checked on the Pi. Hidden network checked or explicitly noted.
- [ ] The owner confirmed "no password in logs" (acceptance criterion 13, step 7.6).
- [ ] The provisioning script is idempotent, and the skill doc mentions the polkit rule.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| `WifiPicker(ctx, on_connected=None)` | US-32 (wizard Wi-Fi step) |
| `wifi.*` parsers and command builders, `run_nmcli` | US-24 (saved networks, forget, status details) |
| `WifiConnector` (connect_new / activate_saved / cancel) | US-24, US-32 |
| The Network section id `"network"` (order 10) | US-24 adds groups to it, US-31/US-38 link to it (`navigator.show("settings", section="network")`) |
| The polkit rule for `kiosk` | US-24 |
| `app.sync.request_sync("network-connected")` after a successful connect | US-16/US-17 |
