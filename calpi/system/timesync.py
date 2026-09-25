"""NTP synchronised state via org.freedesktop.timedate1 (US-17). Async only; main loop."""
from __future__ import annotations

import logging

from gi.repository import Gio, GLib

log = logging.getLogger("calpi.timesync")

BUS, PATH, IFACE = "org.freedesktop.timedate1", "/org/freedesktop/timedate1", "org.freedesktop.timedate1"
POLL_S = 60


class ClockTrust:
    """`synced`: True/False, or None while unknown (no timedated). Polls while not synced."""

    def __init__(self):
        self.synced: bool | None = None
        self.callbacks: list = []                 # cb(synced: bool)
        self._proxy = None
        self._poll_id = 0
        try:
            Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
                                      None, BUS, PATH, "org.freedesktop.DBus.Properties", None,
                                      self._on_proxy)
        except Exception as e:
            log.info("clock: timedate1 not available (%s)", e)

    def _on_proxy(self, _src, res):
        try:
            self._proxy = Gio.DBusProxy.new_for_bus_finish(res)
        except GLib.Error as e:
            log.info("clock: timedate1 not available (%s)", e.message)
            return
        self._query()

    def _query(self) -> None:
        self._proxy.call("Get", GLib.Variant("(ss)", (IFACE, "NTPSynchronized")),
                         Gio.DBusCallFlags.NONE, 10000, None, self._on_reply)

    def _on_reply(self, proxy, res):
        try:
            value = proxy.call_finish(res).unpack()[0]
            self.set_synced(bool(value))
        except Exception as e:
            log.debug("clock: NTPSynchronized query failed: %s", e)
        if self.synced is False and not self._poll_id:
            self._poll_id = GLib.timeout_add_seconds(POLL_S, self._on_poll)

    def _on_poll(self):
        self._poll_id = 0
        try:
            self._query()
        except Exception:
            log.exception("clock: poll failed")
        return GLib.SOURCE_REMOVE

    def set_synced(self, synced: bool) -> None:
        if synced == self.synced:
            return
        self.synced = synced
        log.info("clock: NTP %s", "synchronised" if synced else "not synchronised")
        for cb in list(self.callbacks):
            try:
                cb(synced)
            except Exception:
                log.exception("clock callback failed")
