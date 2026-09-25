"""NetworkManager connect flow over D-Bus (US-23). Uses Gio; all callbacks run on the main loop.

The Wi-Fi password travels only inside the AddAndActivateConnection D-Bus message, never in
argv, logs or settings. A failed NEW connection's profile is deleted (D7).

WifiConnector contract:
    connect_new(ssid, password, kind, hidden, on_result, replace_uuid=None)
    activate_saved(uuid, on_result)
    cancel()
    on_result(("ok", None)) or on_result(("error", code))   # codes: see calpi.system.wifi
US-17's NetworkMonitor can be added to this module later.
"""
from __future__ import annotations

import logging

from gi.repository import Gio, GLib

from calpi.system import wifi
from calpi.tasks import run_in_thread

log = logging.getLogger("calpi.nm")

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
ACTIVE_IFACE = "org.freedesktop.NetworkManager.Connection.Active"
CONNECT_TIMEOUT_S = 45
STATE_ACTIVATED, STATE_DEACTIVATED = 2, 4


def to_variant(settings: dict) -> GLib.Variant:
    """{group: {key: value}} -> a{sa{sv}} (bool->b, int->u, bytes->ay, str->s)."""
    def v(x):
        if isinstance(x, bool):
            return GLib.Variant("b", x)
        if isinstance(x, int):
            return GLib.Variant("u", x)
        if isinstance(x, bytes):
            return GLib.Variant("ay", x)
        if isinstance(x, str):
            return GLib.Variant("s", x)
        raise TypeError(type(x))
    return GLib.Variant("a{sa{sv}}", {g: {k: v(x) for k, x in kv.items()}
                                      for g, kv in settings.items()})


class _Attempt:
    def __init__(self, ssid, kind, on_result):
        self.ssid, self.kind, self.on_result = ssid, kind, on_result
        self.device_path = self.settings_path = self.active_path = None
        self.sub_id = 0
        self.timer = 0
        self.done = False
        self.cancelled = False
        self.saved_uuid: str | None = None       # nmcli path


class WifiConnector:
    """One connect attempt at a time."""

    def __init__(self, iface: str = wifi.IFACE):
        self.iface = iface
        self._bus: Gio.DBusConnection | None = None
        self._attempt: _Attempt | None = None

    # ---- public ----
    def connect_new(self, ssid, password, kind, hidden, on_result, replace_uuid=None):
        if self._attempt is not None:
            on_result(("error", f"{wifi.FAILED}:busy"))
            return
        a = _Attempt(ssid, kind, on_result)
        self._attempt = a
        a.timer = GLib.timeout_add_seconds(CONNECT_TIMEOUT_S, self._on_timeout, a)
        settings = wifi.build_connection_settings(ssid, password, kind, hidden)

        def start():
            if replace_uuid:
                run_in_thread(lambda: self._nmcli_quiet(wifi.cmd_delete(replace_uuid)),
                              on_done=lambda _r: self._with_bus(a, lambda: self._get_device(a, settings)),
                              name="wifi-replace")
            else:
                self._with_bus(a, lambda: self._get_device(a, settings))
        start()

    def activate_saved(self, uuid, on_result):
        if self._attempt is not None:
            on_result(("error", f"{wifi.FAILED}:busy"))
            return
        a = _Attempt("", "psk", on_result)
        a.saved_uuid = uuid
        self._attempt = a

        def work():
            try:
                wifi.run_nmcli(wifi.cmd_up(uuid), 60)
                return ("ok", None)
            except wifi.NmcliError as e:
                return ("error", wifi.map_nmcli_error(str(e)))

        def done(res):
            if res[0] == "error" and a.cancelled:
                res = ("error", wifi.CANCELLED)
            self._finish(a, res)
        run_in_thread(work, on_done=done, name="wifi-up")

    def cancel(self):
        a = self._attempt
        if a is None or a.done:
            return
        a.cancelled = True
        if a.saved_uuid:
            run_in_thread(lambda: self._nmcli_quiet(wifi.cmd_down(a.saved_uuid)), name="wifi-down")
            self._finish(a, ("error", wifi.CANCELLED))
            return
        self._teardown(a)
        self._finish(a, ("error", wifi.CANCELLED))

    # ---- internals ----
    @staticmethod
    def _nmcli_quiet(cmd):
        try:
            wifi.run_nmcli(cmd, 15)
        except wifi.NmcliError as e:
            log.info("nmcli %s failed: %s", cmd[1:3], e)

    def _finish(self, a: _Attempt, result):
        if a.done:
            return
        a.done = True
        if a.sub_id and self._bus:
            self._bus.signal_unsubscribe(a.sub_id)
            a.sub_id = 0
        if a.timer:
            GLib.source_remove(a.timer)
            a.timer = 0
        if self._attempt is a:
            self._attempt = None
        try:
            a.on_result(result)
        except Exception:
            log.exception("connect result callback failed")

    def _with_bus(self, a, then):
        if a.done:
            return
        if self._bus is not None:
            then()
            return

        def ready(_src, res):
            try:
                self._bus = Gio.bus_get_finish(res)
            except GLib.Error as e:
                log.warning("system bus unavailable: %s", e.message)
                self._finish(a, ("error", f"{wifi.FAILED}:no D-Bus"))
                return
            then()
        Gio.bus_get(Gio.BusType.SYSTEM, None, ready)

    def _call(self, path, iface, method, params, reply, cb):
        """Async D-Bus call; cb(result_variant_or_None, error_or_None)."""
        def ready(src, res):
            try:
                cb(src.call_finish(res), None)
            except GLib.Error as e:
                cb(None, e)
        self._bus.call(NM, path, iface, method, params, GLib.VariantType(reply),
                       Gio.DBusCallFlags.NONE, 30000, None, ready)

    def _get_device(self, a, settings):
        if a.done:
            return

        def got(res, err):
            if a.done:
                return
            if err or res is None:
                log.warning("GetDeviceByIpIface failed: %s", err.message if err else "?")
                self._finish(a, ("error", f"{wifi.FAILED}:no Wi-Fi device"))
                return
            a.device_path = res.unpack()[0]
            self._add_activate(a, settings)
        self._call(NM_PATH, NM, "GetDeviceByIpIface", GLib.Variant("(s)", (self.iface,)), "(o)", got)

    def _add_activate(self, a, settings):
        def added(res, err):
            if err or res is None:
                msg = err.message if err else "?"
                log.warning("AddAndActivateConnection failed: %s", msg)
                self._finish(a, ("error", wifi.map_nmcli_error(msg) if a.cancelled is False
                                 else wifi.CANCELLED))
                return
            a.settings_path, a.active_path = res.unpack()[0], res.unpack()[1]
            if a.done or a.cancelled:
                self._teardown(a)
                self._finish(a, ("error", wifi.CANCELLED))
                return
            a.sub_id = self._bus.signal_subscribe(
                NM, ACTIVE_IFACE, "StateChanged", a.active_path, None,
                Gio.DBusSignalFlags.NONE, self._on_state_signal, a)
            # the state may already have changed before we subscribed
            self._call(a.active_path, "org.freedesktop.DBus.Properties", "Get",
                       GLib.Variant("(ss)", (ACTIVE_IFACE, "State")), "(v)",
                       lambda r, e: self._on_state(a, r.unpack()[0], 0) if r else None)
        params = GLib.Variant.new_tuple(to_variant(settings),
                                        GLib.Variant("o", a.device_path), GLib.Variant("o", "/"))
        self._call(NM_PATH, NM, "AddAndActivateConnection", params, "(oo)", added)

    def _on_state_signal(self, _c, _s, _p, _i, _m, params, a):
        state, reason = params.unpack()
        self._on_state(a, state, reason)

    def _on_state(self, a, state, reason):
        if a.done:
            return
        if state == STATE_ACTIVATED:
            self._finish(a, ("ok", None))
        elif state == STATE_DEACTIVATED:
            self._fail(a, reason)

    def _fail(self, a, active_reason):
        def got(res, err):
            dev_reason = None
            if res is not None:
                try:
                    dev_reason = res.unpack()[0][1]      # StateReason is (uu)
                except Exception:
                    pass
            code = wifi.map_failure(active_reason, dev_reason, cancelled=a.cancelled, kind=a.kind)
            log.info("connect to %r failed: active_reason=%s device_reason=%s -> %s",
                     a.ssid, active_reason, dev_reason, code)
            self._delete_profile(a)
            self._finish(a, ("error", code))
        self._call(a.device_path, "org.freedesktop.DBus.Properties", "Get",
                   GLib.Variant("(ss)", ("org.freedesktop.NetworkManager.Device", "StateReason")),
                   "(v)", got)

    def _delete_profile(self, a):
        if a.settings_path and self._bus:
            self._call(a.settings_path, "org.freedesktop.NetworkManager.Settings.Connection",
                       "Delete", None, "()", lambda r, e: None)

    def _teardown(self, a):
        """Deactivate and delete the profile of a new attempt (cancel/timeout)."""
        if a.active_path and self._bus:
            self._call(NM_PATH, NM, "DeactivateConnection", GLib.Variant("(o)", (a.active_path,)),
                       "()", lambda r, e: None)
        self._delete_profile(a)

    def _on_timeout(self, a):
        a.timer = 0
        if not a.done:
            self._teardown(a)
            self._finish(a, ("error", wifi.NOT_REACHABLE))
        return GLib.SOURCE_REMOVE
