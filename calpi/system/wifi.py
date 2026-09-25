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
    return ["nmcli", "-t", "-f", "NAME,UUID,TYPE,AUTOCONNECT,TIMESTAMP", "connection", "show"]


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
    """Wi-Fi profiles: [{name, uuid}] from cmd_saved() output."""
    out = []
    for line in stdout.splitlines():
        f = split_terse(line)
        if len(f) >= 3 and f[2] == "802-11-wireless":
            out.append({"name": f[0], "uuid": f[1]})
    return out


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
