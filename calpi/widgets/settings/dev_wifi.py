"""Fakes for developing/testing the Network section without NetworkManager (CALPI_FAKE_WIFI=1)."""
from __future__ import annotations

from gi.repository import GLib

from calpi.system import wifi

NETS = [
    ("Home-Net", 82, "WPA2", True, False),
    ("Neighbour 5", 55, "WPA2 WPA3", False, False),
    ("Cafe Guest", 40, "--", False, False),
    ("Office Corp", 70, "WPA2 802.1X", False, False),
    ("Saved-Old", 30, "WPA2", False, True),
]


class FakeBackend:
    def __init__(self):
        self.radio = True

    def scan(self, rescan):
        if not self.radio:
            return wifi.ScanResult(False, [])
        nets = [wifi.WifiNetwork(s, sig, sec, wifi.classify_security(sec), use,
                                 "uuid-" + s if saved else None, 2437)
                for s, sig, sec, use, saved in NETS]
        return wifi.ScanResult(True, wifi.sort_networks(nets))

    def radio_on(self):
        self.radio = True


class FakeConnector:
    """connect_new succeeds only with password 'goodpass1'; result after 300 ms."""

    def __init__(self):
        self._timer = 0
        self.calls = []

    def connect_new(self, ssid, password, kind, hidden, on_result, replace_uuid=None):
        self.calls.append(("new", ssid, password, kind, hidden, replace_uuid))
        res = ("ok", None) if (kind == "open" or password == "goodpass1") else ("error", wifi.WRONG_PASSWORD)
        self._later(on_result, res)

    def activate_saved(self, uuid, on_result):
        self.calls.append(("saved", uuid))
        self._later(on_result, ("ok", None))

    def cancel(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _later(self, cb, res):
        def fire():
            self._timer = 0
            cb(res)
            return GLib.SOURCE_REMOVE
        self._timer = GLib.timeout_add(300, fire)


class FakeStatusBackend:
    """Fake StatusBackend (CALPI_FAKE_WIFI=1): Home-Net active, Saved-Old saved; forget works."""

    def __init__(self, fail_forget=False):
        self.fail_forget = fail_forget
        self.calls = []
        self.profiles = [wifi.SavedWifi("uuid-Home-Net", "preconfigured", "Home-Net", True, 1700000900, True),
                         wifi.SavedWifi("uuid-Saved-Old", "Saved-Old", "Saved-Old", False, 1600000000, False)]

    def invalidate(self):
        pass

    def status(self):
        act = next((p for p in self.profiles if p.active), None)
        if act is None:
            return {"kind": None, "ssid": "", "signal": None, "ip": "", "gateway": "", "dns": [],
                    "nm_state": 20, "ethernet_up": False}
        return {"kind": "wifi", "ssid": act.ssid, "signal": 82, "ip": "192.168.1.23",
                "gateway": "192.168.1.1", "dns": ["192.168.1.1", "8.8.8.8"], "nm_state": 70,
                "ethernet_up": False}

    def saved(self):
        return wifi.sort_saved(self.profiles)

    def forget(self, uuid):
        self.calls.append(uuid)
        if self.fail_forget:
            raise wifi.NmcliError("Insufficient privileges")
        self.profiles = [p for p in self.profiles if p.uuid != uuid]
