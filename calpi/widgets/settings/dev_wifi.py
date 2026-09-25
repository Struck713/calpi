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
