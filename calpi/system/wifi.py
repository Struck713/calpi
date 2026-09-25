"""Wi-Fi helpers (US-23). Pure: no gi, no GTK. nmcli command builders, parsers, merge/sort logic,
security classification, PSK validation, NM connection settings dict, failure mapping.

Passwords NEVER appear in any command builder here (they only travel over D-Bus, see
calpi/system/networkmanager.py).

NM numbers (checked against nm-dbus-interface.h, NM 1.4x):
  NMActiveConnectionStateReason: 2 USER_DISCONNECTED, 6 CONNECT_TIMEOUT, 9 NO_SECRETS,
    10 LOGIN_FAILED, 11 CONNECTION_REMOVED.  (The story text says CONNECT_TIMEOUT is 5; in the
    header 5 is IP_CONFIG_INVALID and CONNECT_TIMEOUT is 6.)
  NMDeviceStateReason: 5 IP_CONFIG_UNAVAILABLE, 7 NO_SECRETS, 8 SUPPLICANT_DISCONNECT,
    11 SUPPLICANT_TIMEOUT, 53 SSID_NOT_FOUND.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

IFACE = "wlan0"
FIELDS = "IN-USE,BSSID,SSID,CHAN,FREQ,SIGNAL,SECURITY"

# failure codes (strings; FAILED carries the numeric reason: "FAILED:12")
WRONG_PASSWORD = "WRONG_PASSWORD"
NOT_REACHABLE = "NOT_REACHABLE"
CANCELLED = "CANCELLED"
WPA3_UNSUPPORTED = "WPA3_UNSUPPORTED"
FAILED = "FAILED"

_DEVICE_WRONG = {7, 8}
_DEVICE_UNREACHABLE = {11, 53}


class NmcliError(RuntimeError):
    pass


def split_terse(line: str) -> list[str]:
    """Split an `nmcli -t` line on unescaped ':' and unescape '\\:' and '\\\\'."""
    out: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            out.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: int                  # 0..100
    security: str                # raw nmcli SECURITY
    kind: str                    # "open" | "psk" | "sae" | "enterprise" | "wep" | "unsupported"
    in_use: bool
    saved_uuid: str | None
    freq_mhz: int | None

    @property
    def supported(self) -> bool:
        return self.kind in ("open", "psk", "sae")

    @property
    def secured(self) -> bool:
        return self.kind != "open"


def classify_security(sec: str) -> str:
    s = (sec or "").strip()
    if s in ("", "--"):
        return "open"
    toks = set(s.split())
    if "802.1X" in toks:
        return "enterprise"
    if "WEP" in toks:
        return "wep"
    if "WPA3" in toks and not (toks & {"WPA1", "WPA2", "WPA"}):
        return "sae"
    if toks & {"WPA1", "WPA2", "WPA", "WPA3"}:
        return "psk"
    return "unsupported"        # e.g. OWE


def _int(text: str, default: int | None = 0) -> int | None:
    m = re.match(r"\s*(\d+)", text or "")
    return int(m.group(1)) if m else default


def parse_scan(stdout: str) -> list[dict]:
    """Rows of `nmcli -t -f IN-USE,BSSID,SSID,CHAN,FREQ,SIGNAL,SECURITY device wifi list`.
    Empty SSIDs (hidden APs) are dropped."""
    rows = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        f = split_terse(line)
        if len(f) < 7:
            continue
        ssid = f[2]
        if not ssid.strip():
            continue
        rows.append({"in_use": f[0].strip() == "*", "bssid": f[1], "ssid": ssid,
                     "chan": _int(f[3], None), "freq": _int(f[4], None),
                     "signal": _int(f[5], 0), "security": f[6].strip()})
    return rows


def merge(scan_rows: list[dict], saved: dict[str, str]) -> list[WifiNetwork]:
    """One entry per SSID: strongest AP's signal/security; in_use if any AP is; saved marked."""
    best: dict[str, dict] = {}
    in_use: set[str] = set()
    for r in scan_rows:
        s = r["ssid"]
        if r["in_use"]:
            in_use.add(s)
        if s not in best or r["signal"] > best[s]["signal"]:
            best[s] = r
    return [WifiNetwork(ssid=s, signal=r["signal"], security=r["security"],
                        kind=classify_security(r["security"]), in_use=s in in_use,
                        saved_uuid=saved.get(s), freq_mhz=r["freq"])
            for s, r in best.items()]


def sort_networks(nets) -> list[WifiNetwork]:
    """Connected first, then saved, then strongest signal; ties by SSID."""
    return sorted(nets, key=lambda n: (not n.in_use, n.saved_uuid is None, -n.signal, n.ssid.lower()))


def signal_bars(signal: int) -> str:
    if signal >= 75:
        return "▂▄▆█"
    if signal >= 50:
        return "▂▄▆"
    if signal >= 25:
        return "▂▄"
    return "▂"


def validate_psk(password: str) -> str | None:
    """Error text, or None if acceptable (8..63 chars, or exactly 64 hex digits)."""
    n = len(password)
    if n == 64 and re.fullmatch(r"[0-9a-fA-F]{64}", password):
        return None
    if n < 8:
        return "The password must be at least 8 characters."
    if n > 63:
        return "The password can be at most 63 characters."
    return None


def build_connection_settings(ssid: str, password: str | None, kind: str, hidden: bool) -> dict:
    """Plain dict for AddAndActivateConnection: {group: {key: value}} (bytes for ssid)."""
    d: dict = {
        "connection": {"id": ssid, "type": "802-11-wireless", "autoconnect": True},
        "802-11-wireless": {"ssid": ssid.encode("utf-8"), "mode": "infrastructure",
                            "hidden": bool(hidden)},
        "ipv4": {"method": "auto"},
        "ipv6": {"method": "auto"},
    }
    if kind in ("psk", "sae"):
        d["802-11-wireless-security"] = {"key-mgmt": "sae" if kind == "sae" else "wpa-psk",
                                         "psk": password or ""}
    elif kind != "open":
        raise ValueError(f"unsupported security kind {kind!r}")
    return d


def map_failure(active_reason: int | None, device_reason: int | None,
                timed_out: bool = False, cancelled: bool = False, kind: str = "psk") -> str:
    if cancelled:
        return CANCELLED
    if timed_out:
        return NOT_REACHABLE
    if device_reason in _DEVICE_WRONG or active_reason == 9:
        return WPA3_UNSUPPORTED if (kind == "sae" and device_reason == 8) else WRONG_PASSWORD
    if device_reason in _DEVICE_UNREACHABLE or active_reason == 6:
        return NOT_REACHABLE
    if active_reason == 2:
        return CANCELLED
    return f"{FAILED}:{active_reason if active_reason is not None else (device_reason or 0)}"


def map_nmcli_error(message: str) -> str:
    """Failure code from an nmcli stderr line (activating a saved profile)."""
    m = (message or "").lower()
    if "secrets were required" in m or "password" in m:
        return WRONG_PASSWORD
    if "timeout" in m or "not found" in m or "no suitable" in m or "no network with ssid" in m:
        return NOT_REACHABLE
    return f"{FAILED}:{(message or 'unknown').strip()[:60]}"


def failure_message(code: str, ssid: str) -> str:
    if code == WRONG_PASSWORD:
        return f"Wrong password for {ssid}. Check it and try again."
    if code == NOT_REACHABLE:
        return f"Couldn't connect to {ssid}. Move closer to the router or try again."
    if code == WPA3_UNSUPPORTED:
        return "This network uses WPA3, which this device may not support."
    if code.startswith(FAILED + ":"):
        return f"Couldn't connect ({code.split(':', 1)[1]})"
    return "Couldn't connect"


# ---- command builders (lists, no shell, never a password) ----
def cmd_scan(rescan: str) -> list[str]:
    if rescan not in ("yes", "auto", "no"):
        raise ValueError(rescan)
    return ["nmcli", "-t", "-f", FIELDS, "device", "wifi", "list", "--rescan", rescan,
            "ifname", IFACE]


def cmd_saved() -> list[str]:
    return ["nmcli", "-t", "-f", "NAME,UUID,TYPE,AUTOCONNECT,TIMESTAMP,ACTIVE", "connection", "show"]


def cmd_connection_ssid(uuid: str) -> list[str]:
    return ["nmcli", "-t", "-g", "802-11-wireless.ssid,802-11-wireless-security.key-mgmt",
            "connection", "show", "uuid", uuid]


def cmd_up(uuid: str) -> list[str]:
    return ["nmcli", "--wait", "45", "connection", "up", "uuid", uuid]


def cmd_down(uuid: str) -> list[str]:
    return ["nmcli", "connection", "down", "uuid", uuid]


def cmd_delete(uuid: str) -> list[str]:
    return ["nmcli", "connection", "delete", "uuid", uuid]


def cmd_radio(on: bool) -> list[str]:
    return ["nmcli", "radio", "wifi", "on" if on else "off"]


def cmd_radio_state() -> list[str]:
    return ["nmcli", "-t", "-f", "WIFI", "general"]


def cmd_devices() -> list[str]:
    return ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]


def run_nmcli(cmd: list[str], timeout: float) -> str:
    """Blocking. Call from a worker thread. Raises NmcliError(first stderr line)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "LC_ALL": "C"})
    except subprocess.TimeoutExpired as e:
        raise NmcliError("timeout") from e
    except OSError as e:
        raise NmcliError(str(e)) from e
    if r.returncode != 0:
        first = (r.stderr or r.stdout or f"exit {r.returncode}").strip().splitlines()
        raise NmcliError(first[0] if first else f"exit {r.returncode}")
    return r.stdout


# ---- parsers for the other read-only commands ----
def parse_radio(stdout: str) -> bool:
    return stdout.strip().lower() == "enabled"


def parse_saved(stdout: str) -> list[dict]:
    """Wi-Fi profiles only (never ethernet/loopback/other) from cmd_saved() output:
    [{name, uuid, autoconnect, last_used, active}]. Missing trailing fields default sensibly."""
    out = []
    for line in stdout.splitlines():
        f = split_terse(line)
        if len(f) >= 3 and f[2] == "802-11-wireless":
            out.append({"name": f[0], "uuid": f[1],
                        "autoconnect": (f[3].strip().lower() == "yes") if len(f) > 3 else True,
                        "last_used": (_int(f[4], 0) or 0) if len(f) > 4 else 0,
                        "active": (f[5].strip().lower() == "yes") if len(f) > 5 else False})
    return out


@dataclass(frozen=True)
class SavedWifi:
    uuid: str
    name: str
    ssid: str
    autoconnect: bool
    last_used: int
    active: bool


def sort_saved(items) -> list[SavedWifi]:
    """Active first, then most recently used first, then by SSID."""
    return sorted(items, key=lambda s: (not s.active, -s.last_used, s.ssid.lower()))


def parse_device_status(stdout: str) -> list[dict]:
    """Alias of parse_devices (DEVICE,TYPE,STATE,CONNECTION)."""
    return parse_devices(stdout)


def strip_prefix(addr: str) -> str:
    return addr.split("/", 1)[0]


def parse_device_show(stdout: str) -> dict:
    """`nmcli -t -f GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show DEV`.
    Lines are KEY:VALUE with indexed keys (IP4.ADDRESS[1]); split on the FIRST unescaped ':'.
    -> {"connection": str, "ip4": [addr/prefix], "gateway": str, "dns": [str]}"""
    res: dict = {"connection": "", "ip4": [], "gateway": "", "dns": []}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = split_terse(line)
        key, value = parts[0], ":".join(parts[1:])   # re-join: split_terse unescaped IPv6 colons
        base = key.split("[", 1)[0]
        if not value.strip():
            continue
        if base == "GENERAL.CONNECTION":
            res["connection"] = value
        elif base == "IP4.ADDRESS":
            res["ip4"].append(value)
        elif base == "IP4.GATEWAY":
            res["gateway"] = value
        elif base == "IP4.DNS":
            res["dns"].append(value)
    return res


def active_device(rows) -> dict | None:
    """The connected ethernet/wifi device; ethernet wins when both are connected."""
    ok = [r for r in rows if r.get("state") == "connected" and r.get("type") in ("ethernet", "wifi")]
    for kind in ("ethernet", "wifi"):
        for r in ok:
            if r["type"] == kind:
                return r
    return None


def nm_state_from_text(text: str) -> int | None:
    """`nmcli -t -g STATE general` text -> NMState number (None when unknown)."""
    t = (text or "").strip().lower()
    if t == "connected":
        return 70
    if t.startswith("connected (site"):
        return 60
    if t.startswith("connected (local"):
        return 50
    if t == "connecting":
        return 40
    if t == "disconnecting":
        return 30
    if t == "disconnected":
        return 20
    return None


def cmd_nm_state() -> list[str]:
    return ["nmcli", "-t", "-g", "STATE", "general"]


def cmd_device_show(dev: str) -> list[str]:
    return ["nmcli", "-t", "-f", "GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS",
            "device", "show", dev]


INTERNET_WORKING = "Working"
INTERNET_NONE = "No internet"
INTERNET_CHECKING = "Checking\u2026"
RECENT_SYNC_S = 30 * 60
_NETWORK_ERRORS = {"NETWORK_DOWN", "DNS_FAILED", "TIMEOUT"}


def _sync_network_failed(last_result) -> bool:
    if not last_result:
        return False
    errs = [a.get("error") for a in last_result.get("accounts", [])]
    return bool(errs) and all(e in _NETWORK_ERRORS for e in errs)


def internet_status(nm_state, last_result, last_success_age_s, ssid: str | None = None):
    """D3: (label, hint). No active probing; sync results are the evidence."""
    where = f"Connected to {ssid}" if ssid else "Connected"
    hint = f"{where} but calpi can't reach the internet. Check the router."
    recent = last_success_age_s is not None and last_success_age_s < RECENT_SYNC_S
    failed = _sync_network_failed(last_result)
    if nm_state in (50, 60):
        return INTERNET_NONE, hint
    if nm_state == 70:
        if failed:
            return INTERNET_NONE, hint
        if recent:
            return INTERNET_WORKING, None
        if last_result is None:
            return INTERNET_CHECKING, None
        return INTERNET_NONE, hint
    if nm_state is None:                      # no NetworkManager: sync evidence only
        if last_result is None and last_success_age_s is None:
            return INTERNET_CHECKING, None
        if failed:
            return INTERNET_NONE, hint
        return (INTERNET_WORKING, None) if recent else (INTERNET_NONE, hint)
    return INTERNET_NONE, hint


def parse_devices(stdout: str) -> list[dict]:
    out = []
    for line in stdout.splitlines():
        f = split_terse(line)
        if len(f) >= 4:
            out.append({"device": f[0], "type": f[1], "state": f[2], "connection": f[3]})
    return out


@dataclass(frozen=True)
class ScanResult:
    radio_on: bool
    networks: list[WifiNetwork]


class StatusBackend:
    """Blocking nmcli reads/deletes for the connection status and saved lists (US-24).
    Call from a worker thread. SSIDs are cached per UUID until invalidate()."""

    def __init__(self):
        self._ssids: dict[str, str] = {}

    def invalidate(self) -> None:
        self._ssids.clear()

    def status(self) -> dict:
        """{"kind": "wifi"|"ethernet"|None, "ssid", "signal", "ip", "gateway", "dns", "nm_state",
        "ethernet_up"}"""
        rows = parse_devices(run_nmcli(cmd_devices(), 5))
        try:
            nm_state = nm_state_from_text(run_nmcli(cmd_nm_state(), 5))
        except NmcliError:
            nm_state = None
        eth_up = any(r["type"] == "ethernet" and r["state"] == "connected" for r in rows)
        dev = active_device(rows)
        info = {"kind": None, "ssid": "", "signal": None, "ip": "", "gateway": "", "dns": [],
                "nm_state": nm_state, "ethernet_up": eth_up}
        if dev is None:
            return info
        show = parse_device_show(run_nmcli(cmd_device_show(dev["device"]), 8))
        info.update(kind=dev["type"], ip=strip_prefix(show["ip4"][0]) if show["ip4"] else "",
                    gateway=show["gateway"], dns=show["dns"])
        info["ssid"] = dev["connection"] or show["connection"]
        if dev["type"] == "wifi":
            try:
                for r in parse_scan(run_nmcli(cmd_scan("no"), 10)):
                    if r["in_use"]:
                        info["ssid"], info["signal"] = r["ssid"], r["signal"]
                        break
            except NmcliError:
                pass
        return info

    def saved(self) -> list[SavedWifi]:
        out = []
        for p in parse_saved(run_nmcli(cmd_saved(), 5)):
            ssid = self._ssids.get(p["uuid"])
            if ssid is None:
                try:
                    lines = run_nmcli(cmd_connection_ssid(p["uuid"]), 5).splitlines()
                    ssid = lines[0] if lines and lines[0] else p["name"]
                except NmcliError:
                    ssid = p["name"]
                self._ssids[p["uuid"]] = ssid
            out.append(SavedWifi(p["uuid"], p["name"], ssid, p["autoconnect"], p["last_used"],
                                 p["active"]))
        return sort_saved(out)

    def forget(self, uuid: str) -> None:
        run_nmcli(cmd_delete(uuid), 15)
        self.invalidate()


class NmcliBackend:
    """Blocking nmcli operations for the picker; call from a worker thread."""

    def scan(self, rescan: str) -> ScanResult:
        if not parse_radio(run_nmcli(cmd_radio_state(), 5)):
            return ScanResult(False, [])
        rows = parse_scan(run_nmcli(cmd_scan(rescan), 25))
        return ScanResult(True, sort_networks(merge(rows, self._saved())))

    def _saved(self) -> dict[str, str]:
        saved: dict[str, str] = {}
        try:
            profiles = parse_saved(run_nmcli(cmd_saved(), 5))
        except NmcliError:
            return saved
        for p in profiles:
            try:
                lines = run_nmcli(cmd_connection_ssid(p["uuid"]), 5).splitlines()
            except NmcliError:
                continue
            if lines and lines[0]:
                saved[lines[0]] = p["uuid"]
        return saved

    def radio_on(self) -> None:
        run_nmcli(cmd_radio(True), 10)
