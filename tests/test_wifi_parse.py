import os
import pathlib
import secrets

import pytest

from calpi.system import wifi

FIX = pathlib.Path(__file__).parent / "fixtures" / "nmcli"


def fx(name):
    return (FIX / name).read_text()


def test_split_terse_escapes():
    assert wifi.split_terse(r"a\:b:c\\d:") == ["a:b", "c\\d", ""]


def test_parse_scan_and_merge():
    rows = wifi.parse_scan(fx("scan.txt"))
    assert len(rows) == 8                       # the empty SSID is dropped
    assert rows[0]["bssid"] == "AA:BB:CC:00:00:01" and rows[0]["freq"] == 2437
    ssids = {r["ssid"] for r in rows}
    assert "Cafe:Guest" in ssids and "Back\\slash" in ssids
    nets = {n.ssid: n for n in wifi.merge(rows, {"Cafe:Guest": "u1"})}
    assert len(nets) == 7                       # HomeNet deduped
    assert nets["HomeNet"].signal == 91 and nets["HomeNet"].in_use
    assert nets["Cafe:Guest"].saved_uuid == "u1" and nets["Cafe:Guest"].kind == "open"
    assert nets["Corp"].kind == "enterprise" and not nets["Corp"].supported
    assert nets["OldWep"].kind == "wep"


@pytest.mark.parametrize("sec,kind", [
    ("WPA2", "psk"), ("WPA1 WPA2", "psk"), ("WPA3", "sae"), ("WPA2 WPA3", "psk"),
    ("WPA2 802.1X", "enterprise"), ("WEP", "wep"), ("--", "open"), ("", "open"),
    ("OWE", "unsupported")])
def test_classify(sec, kind):
    assert wifi.classify_security(sec) == kind


def test_sort_and_bars():
    mk = lambda s, sig, use=False, saved=None: wifi.WifiNetwork(s, sig, "WPA2", "psk", use, saved, 2412)
    nets = [mk("a", 90), mk("b", 50, saved="u"), mk("c", 40, use=True), mk("d", 95)]
    assert [n.ssid for n in wifi.sort_networks(nets)] == ["c", "b", "d", "a"]
    assert [wifi.signal_bars(x) for x in (0, 24, 25, 49, 50, 74, 75, 100)] == [
        "▂", "▂", "▂▄", "▂▄", "▂▄▆", "▂▄▆", "▂▄▆█", "▂▄▆█"]


def test_validate_psk():
    assert wifi.validate_psk("a" * 7)
    assert wifi.validate_psk("a" * 8) is None
    assert wifi.validate_psk("a" * 63) is None
    assert wifi.validate_psk("g" * 64)
    assert wifi.validate_psk("0f" * 32) is None
    assert wifi.validate_psk("a" * 65)


def test_build_settings():
    d = wifi.build_connection_settings("Net", "secretpw1", "psk", False)
    assert d["802-11-wireless"]["ssid"] == b"Net" and d["802-11-wireless"]["hidden"] is False
    assert d["802-11-wireless-security"] == {"key-mgmt": "wpa-psk", "psk": "secretpw1"}
    assert wifi.build_connection_settings("N", "secretpw1", "sae", True)[
        "802-11-wireless-security"]["key-mgmt"] == "sae"
    o = wifi.build_connection_settings("N", None, "open", True)
    assert "802-11-wireless-security" not in o and o["802-11-wireless"]["hidden"] is True
    with pytest.raises(ValueError):
        wifi.build_connection_settings("N", "x", "enterprise", False)


def test_map_failure():
    assert wifi.map_failure(9, None) == wifi.WRONG_PASSWORD
    assert wifi.map_failure(1, 7) == wifi.WRONG_PASSWORD
    assert wifi.map_failure(1, 8) == wifi.WRONG_PASSWORD
    assert wifi.map_failure(1, 8, kind="sae") == wifi.WPA3_UNSUPPORTED
    assert wifi.map_failure(1, 11) == wifi.NOT_REACHABLE
    assert wifi.map_failure(1, 53) == wifi.NOT_REACHABLE
    assert wifi.map_failure(6, None) == wifi.NOT_REACHABLE
    assert wifi.map_failure(None, None, timed_out=True) == wifi.NOT_REACHABLE
    assert wifi.map_failure(2, None) == wifi.CANCELLED
    assert wifi.map_failure(1, None, cancelled=True) == wifi.CANCELLED
    assert wifi.map_failure(12, 3) == "FAILED:12"


def test_nmcli_error_mapping():
    assert wifi.map_nmcli_error("Error: Connection activation failed: Secrets were required, but not provided") == wifi.WRONG_PASSWORD
    assert wifi.map_nmcli_error("Error: Timeout expired (45 seconds)") == wifi.NOT_REACHABLE
    assert wifi.map_nmcli_error("weird").startswith("FAILED:")


def test_other_parsers():
    assert wifi.parse_radio("enabled\n") and not wifi.parse_radio("disabled\n")
    assert [p["uuid"][0] for p in wifi.parse_saved(fx("saved.txt"))] == ["1", "4"]
    d = wifi.parse_devices(fx("devices.txt"))
    assert d[0] == {"device": "wlan0", "type": "wifi", "state": "connected", "connection": "Home Wifi"}


def test_commands_never_contain_password():
    pw = secrets.token_hex(12)
    cmds = [wifi.cmd_scan("yes"), wifi.cmd_scan("auto"), wifi.cmd_saved(),
            wifi.cmd_connection_ssid("uuid"), wifi.cmd_up("uuid"), wifi.cmd_down("uuid"),
            wifi.cmd_delete("uuid"), wifi.cmd_radio(True), wifi.cmd_radio_state(), wifi.cmd_devices()]
    for c in cmds:
        assert isinstance(c, list) and pw not in " ".join(c) and "password" not in c
    import inspect
    for name, fn in inspect.getmembers(wifi, inspect.isfunction):
        if name.startswith("cmd_"):
            assert "password" not in inspect.signature(fn).parameters


def test_wifi_module_does_not_import_gi():
    import subprocess, sys
    r = subprocess.run([sys.executable, "-c", "import sys, calpi.system.wifi; assert 'gi' not in sys.modules"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---- US-24 ----
def test_parse_saved_fields():
    a, b = wifi.parse_saved(fx("saved.txt"))
    assert (a["name"], a["autoconnect"], a["last_used"], a["active"]) == ("Home Wifi", True, 1700000000, True)
    assert (b["name"], b["autoconnect"], b["last_used"], b["active"]) == ("preconfigured", False, 0, False)
    assert wifi.parse_saved("x:u:802-11-wireless\n")[0]["last_used"] == 0   # missing fields


def test_sort_saved():
    mk = lambda u, t, act=False: wifi.SavedWifi(u, u, u, True, t, act)
    assert [s.uuid for s in wifi.sort_saved([mk("old", 1), mk("new", 9), mk("act", 0, True)])] == ["act", "new", "old"]


def test_parse_device_show():
    d = wifi.parse_device_show(fx("device_show.txt"))
    assert d == {"connection": "Home Wifi", "ip4": ["192.168.1.23/24"], "gateway": "192.168.1.1",
                 "dns": ["192.168.1.1", "8.8.8.8"]}
    assert wifi.strip_prefix("192.168.1.23/24") == "192.168.1.23"
    e = wifi.parse_device_show("GENERAL.CONNECTION:Cafe\\: Guest\nIP4.ADDRESS[1]:10.0.0.2/8\nIP4.GATEWAY:\nIP4.DNS[1]:fe80\\:\\:1\n")
    assert e["connection"] == "Cafe: Guest" and e["gateway"] == "" and e["dns"] == ["fe80::1"]
    assert wifi.parse_device_show("") == {"connection": "", "ip4": [], "gateway": "", "dns": []}


def test_active_device_prefers_ethernet():
    rows = [{"device": "wlan0", "type": "wifi", "state": "connected", "connection": "H"},
            {"device": "eth0", "type": "ethernet", "state": "connected", "connection": "W"},
            {"device": "lo", "type": "loopback", "state": "connected (externally)", "connection": "lo"}]
    assert wifi.active_device(rows)["device"] == "eth0"
    assert wifi.active_device(rows[:1])["device"] == "wlan0"
    assert wifi.active_device([{"device": "eth0", "type": "ethernet", "state": "unavailable", "connection": ""}]) is None
    assert wifi.active_device(wifi.parse_devices(fx("devices.txt")))["device"] == "wlan0"


def test_nm_state_text():
    assert wifi.nm_state_from_text("connected\n") == 70
    assert wifi.nm_state_from_text("connected (site only)") == 60
    assert wifi.nm_state_from_text("connected (local only)") == 50
    assert wifi.nm_state_from_text("disconnected") == 20
    assert wifi.nm_state_from_text("weird") is None


def test_internet_status_truth_table():
    ok = {"status": "done", "accounts": [{"error": None}]}
    bad = {"status": "done", "accounts": [{"error": "NETWORK_DOWN"}]}
    auth = {"status": "done", "accounts": [{"error": "AUTH_FAILED"}]}
    f = wifi.internet_status
    assert f(70, ok, 60)[0] == "Working"
    assert f(70, bad, 60)[0] == "No internet" and "Home" in f(70, bad, 60, "Home")[1]
    assert f(70, ok, 3600)[0] == "No internet"
    assert f(70, auth, 3600)[0] == "No internet"
    assert f(70, None, None)[0] == "Checking…"
    assert f(60, ok, 10)[0] == f(50, ok, 10)[0] == "No internet"
    assert f(None, None, None)[0] == "Checking…"
    assert f(None, ok, 10) == ("Working", None)
    assert f(None, bad, None)[0] == "No internet"
