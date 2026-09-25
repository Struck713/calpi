"""Network settings section (US-23): WifiPicker, password page, hidden network page.

WifiPicker(ctx, on_connected=None) is mode-agnostic (also used by the setup wizard, US-32): it
talks only to ctx (push_page/pop_page, window.keyboard/blocking/confirm, app.toast).
Backend (scan) and connector are injectable; CALPI_FAKE_WIFI=1 uses fakes (devcontainer).
"""
from __future__ import annotations

import logging
import os

from gi.repository import GLib, Gtk

from calpi.system import wifi
from calpi.tasks import run_in_thread, safe_callback
from calpi.widgets.keyboard import make_password_field
from calpi.widgets.settings.registry import SectionSpec, register_section
from calpi.widgets.settings.rows import InfoRow, ListPickerRow, SettingsGroup
from calpi.widgets.util import set_class, set_text_if_changed

log = logging.getLogger("calpi.settings.network")

SCAN_INTERVAL_S = 20
NOTE_24GHZ = ("calpi can only see 2.4 GHz networks. If yours doesn't appear, check that your "
              "router's 2.4 GHz band is on.")
CONNECT_LABEL = "Connect"


def make_backend():
    if os.environ.get("CALPI_FAKE_WIFI") == "1":
        from calpi.widgets.settings.dev_wifi import FakeBackend
        return FakeBackend()
    return wifi.NmcliBackend()


def make_connector():
    if os.environ.get("CALPI_FAKE_WIFI") == "1":
        from calpi.widgets.settings.dev_wifi import FakeConnector
        return FakeConnector()
    from calpi.system.networkmanager import WifiConnector
    return WifiConnector()


class ConnectPage(Gtk.Box):
    """Password page for a known SSID, or (hidden=True) the "Other network" page."""

    def __init__(self, ctx, ssid: str | None, kind: str, on_submit, hidden: bool = False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20,
                         css_classes=["wifi-page"])
        self.ctx, self.ssid, self.kind, self.hidden = ctx, ssid, kind, hidden
        self._on_submit = on_submit
        kb = getattr(ctx.window, "keyboard", None)
        self.ssid_entry = None
        if hidden:
            self.append(Gtk.Label(label="Network name (SSID)", xalign=0, css_classes=["row-desc"]))
            self.ssid_entry = Gtk.Entry(hexpand=True, css_classes=["osk-entry"],
                                        input_purpose=Gtk.InputPurpose.FREE_FORM,
                                        input_hints=Gtk.InputHints.NO_SPELLCHECK
                                        | Gtk.InputHints.LOWERCASE)
            self.append(self.ssid_entry)
            if kb:
                kb.attach(self.ssid_entry, "text", done_label="Next")
            sec = Gtk.Box(spacing=16)
            self._sec_buttons = {}
            first = None
            for k, label in (("psk", "WPA / WPA2 / WPA3 Personal"), ("open", "None")):
                b = Gtk.ToggleButton(label=label, css_classes=["choice-button"])
                if first is None:
                    first = b
                    b.set_active(True)
                else:
                    b.set_group(first)
                b.connect("toggled", self._on_sec_toggled, k)
                sec.append(b)
                self._sec_buttons[k] = b
            self.append(sec)
        self.pw_label = Gtk.Label(label="Password", xalign=0, css_classes=["row-desc"])
        self.append(self.pw_label)
        self.pw_box, self.entry, self.toggle = make_password_field()
        self.append(self.pw_box)
        if kb:
            kb.attach(self.entry, "password", done_label=CONNECT_LABEL, on_done=self.submit)
        self.error = Gtk.Label(label="", xalign=0, wrap=True, css_classes=["wifi-error"])
        self.error.set_visible(False)
        self.append(self.error)
        self.button = Gtk.Button(label=CONNECT_LABEL, halign=Gtk.Align.START,
                                 css_classes=["row-button", "wifi-connect"])
        self.button.connect("clicked", lambda *_: self.submit())
        self.append(self.button)
        self.entry.connect("activate", lambda *_: self.submit())
        self.connect("map", self._on_map)

    def _on_sec_toggled(self, b, k):
        if b.get_active():
            self.kind = k
            self.pw_label.set_visible(k != "open")
            self.pw_box.set_visible(k != "open")

    def _on_map(self, *_):
        target = self.ssid_entry if self.ssid_entry is not None else self.entry
        GLib.idle_add(safe_callback(lambda: target.grab_focus() and False, repeat=False))

    def set_error(self, text: str, select_password: bool = False) -> None:
        set_text_if_changed(self.error, text)
        self.error.set_visible(bool(text))
        if select_password:
            self.entry.grab_focus()
            self.entry.select_region(0, -1)

    def submit(self) -> None:
        ssid = self.ssid_entry.get_text().strip() if self.ssid_entry is not None else self.ssid
        if not ssid:
            self.set_error("Enter the network name.")
            return
        pw = self.entry.get_text()
        if self.kind != "open":
            err = wifi.validate_psk(pw)
            if err:
                self.set_error(err)
                return
        self.set_error("")
        self._on_submit(self, ssid, pw if self.kind != "open" else None, self.kind, self.hidden)


class WifiPicker(Gtk.Box):
    def __init__(self, ctx, on_connected=None, backend=None, connector=None, on_networks=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["wifi-picker"])
        self.ctx, self.on_connected, self.on_networks = ctx, on_connected, on_networks
        self.backend = backend or make_backend()
        self.connector = connector or make_connector()
        self._visible = False
        self._scanning = False
        self._timer = 0
        self._sig = None
        self.networks: list[wifi.WifiNetwork] = []
        self._pages: list[ConnectPage] = []

        top = Gtk.Box(spacing=24, margin_bottom=16)
        self.status = Gtk.Label(label="Scanning…", xalign=0, hexpand=True, css_classes=["row-desc"])
        self.rescan = Gtk.Button(label="Rescan", css_classes=["row-button"])
        self.rescan.connect("clicked", lambda *_: self.scan("yes"))
        top.append(self.status)
        top.append(self.rescan)
        self.append(top)

        self.off_box = Gtk.Box(spacing=24, css_classes=["settings-row", "wifi-off"])
        self.off_box.append(Gtk.Label(label="Wi-Fi is turned off", xalign=0, hexpand=True,
                                      css_classes=["row-title"]))
        self.turn_on = Gtk.Button(label="Turn on", css_classes=["row-button"])
        self.turn_on.connect("clicked", lambda *_: self._turn_on())
        self.off_box.append(self.turn_on)
        self.off_box.set_visible(False)
        self.append(self.off_box)

        self.group = SettingsGroup("Networks")
        self.append(self.group)
        self.other = ListPickerRow("Other network…", "", self._open_hidden,
                                   description="Join a hidden network")
        self.other_group = SettingsGroup()
        self.other_group.add(self.other)
        self.append(self.other_group)
        self.note = Gtk.Label(label=NOTE_24GHZ, xalign=0, wrap=True, css_classes=["row-desc", "wifi-note"])
        self.append(self.note)

    # ---- lifecycle ----
    def on_show(self):
        self._visible = True
        self.scan("yes")
        if not self._timer:
            self._timer = GLib.timeout_add_seconds(SCAN_INTERVAL_S,
                                                   safe_callback(self._on_tick, repeat=True))

    def on_hide(self):
        self._visible = False
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _on_tick(self):
        if self._visible:
            self.scan("auto")

    # ---- scanning ----
    def scan(self, rescan: str = "auto") -> None:
        if self._scanning:
            return
        self._scanning = True
        self.rescan.set_sensitive(False)
        set_text_if_changed(self.status, "Scanning…")
        run_in_thread(lambda: self.backend.scan(rescan), on_done=self._on_scan,
                      on_error=self._on_scan_error, name="wifi-scan")

    def _on_scan_error(self, e):
        self._scanning = False
        self.rescan.set_sensitive(True)
        if self._visible:
            set_text_if_changed(self.status, "Couldn't scan for networks. Try Rescan.")

    def _on_scan(self, res):
        self._scanning = False
        self.rescan.set_sensitive(True)
        if not self._visible:
            return
        self.off_box.set_visible(not res.radio_on)
        self.group.set_visible(res.radio_on)
        self.other_group.set_visible(res.radio_on)
        self.note.set_visible(res.radio_on)
        self.rescan.set_visible(res.radio_on)
        if not res.radio_on:
            set_text_if_changed(self.status, "")
            self.networks = []
            self._sig = None
            self._notify_networks()
            return
        n = len(res.networks)
        set_text_if_changed(self.status, "No networks found" if n == 0
                            else f"{n} network{'s' if n != 1 else ''}")
        self.networks = res.networks
        sig = [(x.ssid, x.in_use, x.saved_uuid, x.kind, wifi.signal_bars(x.signal))
               for x in res.networks]
        if sig != self._sig:            # bars, not raw numbers: no rebuild on signal jitter
            self._sig = sig
            self._rebuild(res.networks)
        self._notify_networks()

    def _notify_networks(self):
        if self.on_networks:
            try:
                self.on_networks(self.networks)
            except Exception:
                log.exception("on_networks failed")

    def _rebuild(self, nets) -> None:
        rows = self.group.rows
        while (c := rows.get_first_child()) is not None:
            rows.remove(c)
        for n in nets:
            self.group.add(self._make_row(n))

    def _make_row(self, n: wifi.WifiNetwork) -> ListPickerRow:
        sec = "Secured" if n.secured else "Open"
        if n.in_use:
            value = f"✓ Connected  {wifi.signal_bars(n.signal)}"
        else:
            value = f"{sec}  {wifi.signal_bars(n.signal)}"
        desc = None if n.supported else (
            "Enterprise networks aren't supported" if n.kind == "enterprise"
            else "This kind of network isn't supported")
        row = ListPickerRow(n.ssid, value, lambda n=n: self._on_pick(n), description=desc)
        set_class(row, "unsupported", not n.supported)
        return row

    def _turn_on(self) -> None:
        self.turn_on.set_sensitive(False)

        def done(_r=None):
            self.turn_on.set_sensitive(True)
            GLib.timeout_add(1500, safe_callback(lambda: self.scan("yes") and False, repeat=False))
        run_in_thread(self.backend.radio_on, on_done=done, on_error=lambda e: done(),
                      name="wifi-radio")

    # ---- connect flow ----
    def _toast(self, text):
        try:
            self.ctx.app.toast(text)
        except Exception:
            log.warning("toast unavailable: %s", text)

    def _on_pick(self, n: wifi.WifiNetwork) -> None:
        if not n.supported:
            self._toast("Enterprise networks aren't supported" if n.kind == "enterprise"
                        else "This kind of network isn't supported")
        elif n.in_use:
            self._toast(f"Already connected to {n.ssid}")
        elif n.saved_uuid:
            self._connect_saved(n)
        elif n.kind == "open":
            self.ctx.window.confirm.ask(
                n.ssid, f"{n.ssid} is an open network. Anyone nearby can see the traffic. "
                        "Connect anyway?", "Connect",
                lambda: self._connect(None, n.ssid, None, "open", False))
        else:
            self._open_password(n)

    def _open_password(self, n, replace_uuid=None):
        page = ConnectPage(self.ctx, n.ssid, n.kind, self._submit)
        page.replace_uuid = replace_uuid
        self._push(page, n.ssid)

    def _open_hidden(self):
        self._push(ConnectPage(self.ctx, None, "psk", self._submit, hidden=True), "Other network")

    def _push(self, page, title):
        page.replace_uuid = getattr(page, "replace_uuid", None)
        self._pages.append(page)
        self.ctx.push_page(page, title)

    def _submit(self, page, ssid, password, kind, hidden):
        self._connect(page, ssid, password, kind, hidden, getattr(page, "replace_uuid", None))

    def _show_blocking(self, ssid):
        w = self.ctx.window
        try:
            w.keyboard.hide()
        except Exception:
            pass
        w.blocking.show(f"Connecting to {ssid}…", on_cancel=self.connector.cancel)

    def _connect(self, page, ssid, password, kind, hidden, replace_uuid=None):
        self._show_blocking(ssid)
        self.connector.connect_new(ssid, password, kind, hidden,
                                   lambda r: self._on_result(page, ssid, r), replace_uuid)

    def _connect_saved(self, n):
        self._show_blocking(n.ssid)
        self.connector.activate_saved(n.saved_uuid, lambda r: self._on_result(None, n.ssid, r, n))

    def _on_result(self, page, ssid, result, saved_net=None):
        self.ctx.window.blocking.hide()
        status, code = result
        if status == "ok":
            self._toast(f"Connected to {ssid}")
            if page is not None and page in self._pages:
                self.ctx.pop_page()
            self._pages = []
            self.scan("auto")
            sync = getattr(self.ctx.app, "sync", None)
            if sync is not None and hasattr(sync, "request_sync"):
                try:
                    sync.request_sync("network-connected")
                except Exception:
                    log.exception("request_sync failed")
            if self.on_connected:
                self.on_connected(ssid)
            return
        if code == wifi.CANCELLED:
            return
        if saved_net is not None and code == wifi.WRONG_PASSWORD:
            # the saved profile's password no longer works: ask again, replacing the profile
            self._open_password(saved_net, replace_uuid=saved_net.saved_uuid)
            return
        msg = wifi.failure_message(code, ssid)
        if page is not None:
            page.set_error(msg, select_password=(code == wifi.WRONG_PASSWORD))
        else:
            self._toast(msg)


class NetworkSection:
    def __init__(self, ctx):
        self.ctx = ctx
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        g = SettingsGroup("Connection")
        self.summary = g.add(InfoRow("Wi-Fi", "Checking…"))
        self.widget.append(g)
        self.picker = WifiPicker(ctx, on_connected=self._connected, on_networks=self._networks)
        self.widget.append(self.picker)

    def _networks(self, nets):
        cur = next((n for n in nets if n.in_use), None)
        self.summary.set_value(f"Connected to {cur.ssid}" if cur else "Not connected")

    def _connected(self, ssid):
        self.summary.set_value(f"Connected to {ssid}")

    def on_show(self):
        self.picker.on_show()

    def on_hide(self):
        self.picker.on_hide()


register_section(SectionSpec("network", "Network", 10, NetworkSection))
