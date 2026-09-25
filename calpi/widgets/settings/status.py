"""Status section (US-31): one plain-language screen for network, updates, device and recent runs."""
from __future__ import annotations

import logging

from gi.repository import GLib, Gtk

from calpi import __version__
from calpi.data import accounts as accounts_mod
from calpi.data import formatting, messages, status_summary, timeutil
from calpi.data.status_summary import StatusInputs
from calpi.system import device_info, wifi
from calpi import tasks
from calpi.tasks import run_in_thread, safe_callback
from calpi.widgets.settings.registry import SectionSpec, register_section
from calpi.widgets.settings.rows import ButtonRow, InfoRow, SettingsGroup
from calpi.widgets.util import set_class, set_text_if_changed, set_visible_if_changed

log = logging.getLogger("calpi.settings.status")

TICK_SECONDS = 5
DEVICE_PROBE_S = 30
RUNS_SHOWN = 5


def _small(text: str = "") -> Gtk.Label:
    return Gtk.Label(label=text, xalign=0, wrap=True, css_classes=["status-detail"], margin_start=24)


class StatusSection:
    def __init__(self, ctx):
        self.ctx = ctx
        self.app = ctx.app
        self._timer = 0
        self._visible = False
        self._subs: list = []
        self._device: device_info.DeviceInfo | None = None
        self._device_at = 0.0
        self._device_busy = False
        self._net_info: dict | None = None
        self._net_busy = False
        self._backend = None
        self._keys: dict[str, tuple] = {}

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.widget = root
        # verdict
        self.verdict = Gtk.Box(spacing=24, css_classes=["verdict", "verdict-ok"])
        self.verdict_label = Gtk.Label(label="Checking…", xalign=0, hexpand=True, wrap=True,
                                       css_classes=["verdict-text"])
        self.verdict.append(self.verdict_label)
        self.verdict_fix = Gtk.Button(label="Fix", valign=Gtk.Align.CENTER, css_classes=["row-button"])
        self._fix_section: str | None = None
        self.verdict_fix.connect("clicked", lambda *_: self._goto(self._fix_section))
        self.verdict_fix.set_visible(False)
        self.verdict.append(self.verdict_fix)
        root.append(self.verdict)
        # network
        g = SettingsGroup("Network")
        self.net_kind = g.add(InfoRow("Connection", "Checking…"))
        self.net_signal = g.add(InfoRow("Signal"))
        self.net_ip = g.add(InfoRow("IP address"))
        self.net_inet = g.add(InfoRow("Internet", wifi.INTERNET_CHECKING))
        g.add(ButtonRow("Network settings", "Open", lambda: self._goto("network")))
        root.append(g)
        # updates
        g = SettingsGroup("Calendar updates")
        self.last_row = g.add(InfoRow("Last updated"))
        self.next_row = g.add(InfoRow("Next update"))
        self.accounts_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        g.add(self.accounts_box)
        g.add(ButtonRow("Update now", "Update", self._update_now))
        self.accounts_btn = g.add(ButtonRow("Sign-in", "Accounts", lambda: self._goto("accounts")))
        self.accounts_btn.set_visible(False)
        root.append(g)
        # device
        g = SettingsGroup("Device")
        self.clock_row = g.add(InfoRow("Clock"))
        self.power_row = g.add(InfoRow("Power"))
        self.temp_row = g.add(InfoRow("Temperature"))
        self.disk_row = g.add(InfoRow("Storage"))
        self.notices_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        g.add(self.notices_box)
        self.dim_row = g.add(InfoRow("Overnight mode"))
        self.weather_row = g.add(InfoRow("Weather"))
        from calpi.widgets.settings.about import build_stamp
        self.version = _small(f"calpi {__version__} · build {build_stamp()}")
        self.version.set_margin_top(8)
        g.add(self.version)
        root.append(g)
        # recent
        g = SettingsGroup("Recent updates")
        self.runs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        g.add(self.runs_box)
        root.append(g)

    # ---- lifecycle: nothing runs while hidden ----
    def on_show(self, **_kw) -> None:
        self._visible = True
        app = self.app
        self._sub(getattr(app, "status_callbacks", None), self._on_event)
        eng = getattr(app, "sync", None)
        if eng is not None:
            self._sub(eng.state_callbacks, self._on_event)
            self._sub(eng.result_callbacks, self._on_event)
        net = getattr(app, "network", None)
        if net is not None:
            self._sub(net.callbacks, self._on_event)
        ct = getattr(app, "clock_trust", None)
        if ct is not None:
            self._sub(ct.callbacks, self._on_event)
        if not self._timer:
            self._timer = tasks.add_periodic_seconds("status-screen", TICK_SECONDS, self._tick)
        self._device_at = 0.0
        self._render()
        self._probe()

    def on_hide(self) -> None:
        self._visible = False
        if self._timer:
            tasks.remove_periodic("status-screen")
            self._timer = 0
        for lst, cb in self._subs:
            if cb in lst:
                lst.remove(cb)
        self._subs = []

    def _sub(self, lst, cb) -> None:
        if lst is not None and cb not in lst:
            lst.append(cb)
            self._subs.append((lst, cb))

    def _on_event(self, *_a) -> None:
        if self._visible:
            self._render()

    @safe_callback(repeat=True)
    def _tick(self):
        if not self._visible:
            return
        self._probe()
        self._render()

    # ---- probes (workers) ----
    def _probe(self) -> None:
        import time
        now = time.monotonic()
        if not self._device_busy and now - self._device_at >= DEVICE_PROBE_S:
            self._device_busy = True
            self._device_at = now
            run_in_thread(device_info.collect, on_done=self._device_done,
                          on_error=self._device_failed, name="device-info")
        if not self._net_busy:
            self._net_busy = True
            if self._backend is None:
                from calpi.widgets.settings.network import make_status_backend
                self._backend = make_status_backend()
            run_in_thread(self._backend.status, on_done=self._net_done,
                          on_error=self._net_failed, name="status-net")

    def _device_done(self, info) -> None:
        self._device_busy = False
        self._device = info
        if self._visible:
            self._render()

    def _device_failed(self, e) -> None:
        self._device_busy = False
        log.warning("device probe failed: %s", e)

    def _net_done(self, info) -> None:
        self._net_busy = False
        self._net_info = info
        if self._visible:
            self._render()

    def _net_failed(self, e) -> None:
        self._net_busy = False
        log.warning("network probe failed: %s", e)

    # ---- actions ----
    def _goto(self, section: str | None) -> None:
        if section:
            self.ctx.window.navigator.show("settings", section=section)

    def _update_now(self) -> None:
        trig = getattr(self.app, "trigger_manual_refresh", None)
        if trig is not None:
            trig()

    # ---- rendering ----
    def _providers(self) -> dict[str, str]:
        f = getattr(self.app, "_provider_names", None)
        try:
            return f() if f else {}
        except Exception:
            return {}

    def _rebuild(self, box: Gtk.Box, key: str, sig: tuple, make) -> None:
        if self._keys.get(key) == sig:
            return
        self._keys[key] = sig
        while (c := box.get_first_child()) is not None:
            box.remove(c)
        for w in make():
            box.append(w)

    def _row(self, title: str, text: str, warn: bool = False) -> Gtk.Widget:
        r = InfoRow(title, text)
        set_class(r.value, "status-warn", warn)
        return r

    def _render(self) -> None:
        app = self.app
        now = timeutil.now()
        snap = getattr(app, "sync_status", None)
        eng = getattr(app, "sync", None)
        net = getattr(app, "network", None)
        ct = getattr(app, "clock_trust", None)
        dev = self._device
        prov = self._providers()
        accts = accounts_mod.list_accounts(app.settings) if getattr(app, "settings", None) else []
        notices = list(getattr(app, "startup_notices", []) or [])

        # --- network block ---
        info = self._net_info
        if info is not None:
            kind = info["kind"]
            if kind is None:
                self.net_kind.set_value("Not connected")
            else:
                self.net_kind.set_value("Ethernet" if kind == "ethernet"
                                        else f"Wi-Fi · {info['ssid']}" if info["ssid"] else "Wi-Fi")
            sig = info.get("signal")
            set_visible_if_changed(self.net_signal, kind == "wifi" and sig is not None)
            if sig is not None:
                self.net_signal.set_value(f"{wifi.signal_bars(sig)}  {sig}%")
            set_visible_if_changed(self.net_ip, kind is not None and bool(info.get("ip")))
            self.net_ip.set_value(info.get("ip") or "")
            if kind is None:
                inet = wifi.INTERNET_NONE
            else:
                last = getattr(eng, "last_result", None)
                ok_at = getattr(eng, "last_success_wall", None)
                age = max(0.0, (now - ok_at).total_seconds()) if ok_at else None
                inet, _h = wifi.internet_status(info.get("nm_state"), last, age, info.get("ssid") or None)
            self.net_inet.set_value(inet)
        else:
            for r in (self.net_signal, self.net_ip):
                r.set_visible(False)

        # --- calendar updates ---
        last_ok = getattr(eng, "last_success_wall", None)
        if last_ok is None and snap is not None:
            times = [a.last_success_at for a in snap.accounts if a.last_success_at]
            last_ok = max(times) if times else None
        self.last_row.set_value(formatting.relative_datetime(last_ok, now))
        if eng is not None:
            self.next_row.set_value(formatting.next_update_text(
                eng.next_run_in_seconds(), eng.is_running, offline=bool(getattr(eng, "offline", False)),
                safe_mode=bool(getattr(app, "safe_mode", False))))
        lines: list[tuple[str, str, bool]] = []
        auth_bad = False
        failing_since = None
        failing_prov = "iCloud"
        for a in accts:
            st = snap.account(a.id) if snap else None
            p = prov.get(a.id, "iCloud")
            bad = bool(st and st.last_error_code)
            lines.append((a.display_name or a.username, status_summary.account_line(st, now, p), bad))
            if bad and st.last_error_code in ("AUTH_FAILED", "CREDENTIALS_UNREADABLE"):
                auth_bad = True
                failing_prov = p
            elif bad and st.consecutive_failures >= status_summary.FAILING_MIN:
                t = st.last_success_at or st.last_error_at
                if failing_since is None or (t and t < failing_since):
                    failing_since, failing_prov = t, p
            if snap:
                for c in snap.calendars_of(a.id):
                    if c.last_error_code and not c.inherited:
                        lines.append((f"  {c.name}", messages.describe(c.last_error_code, provider=p).title, True))
        if not accts:
            lines = [("Accounts", "No calendar account yet", True)]
        self._rebuild(self.accounts_box, "accounts", tuple(lines),
                      lambda: [self._row(t, s, w) for t, s, w in lines])
        set_visible_if_changed(self.accounts_btn, auth_bad or not accts)

        # --- device ---
        synced = getattr(ct, "synced", None)
        self.clock_row.set_value("Set automatically" if synced is not False
                                 else messages.describe("CLOCK_UNSYNCED").title)
        power_now, power_past, temp_txt, disk_txt = [], [], "…", "…"
        if dev is not None:
            power_now, power_past = device_info.power_codes(dev.throttled)
            if not dev.power_known:
                self.power_row.set_value("Not available")
            elif power_now:
                self.power_row.set_value(messages.describe(power_now[0]).title)
            elif power_past:
                self.power_row.set_value(messages.describe(power_past[0]).title)
            else:
                self.power_row.set_value("OK")
            set_visible_if_changed(self.temp_row, dev.temp_c is not None)
            if dev.temp_c is not None:
                self.temp_row.set_value(f"{dev.temp_c:.0f} °C" +
                                        (" — " + messages.describe("TEMP_HIGH").title if dev.temp_high else ""))
            if dev.disk_free is not None:
                gb = dev.disk_free / 1024 ** 3
                self.disk_row.set_value((f"{gb:.1f} GB free" if gb >= 1 else f"{dev.disk_free // 1024 ** 2} MB free")
                                        + (" — " + messages.describe("DISK_LOW").title if dev.disk_low else ""))
        else:
            self.power_row.set_value("Checking…")
            self.temp_row.set_visible(False)
        nl = []
        for code in notices:
            m = messages.describe({"safe_mode": "SAFE_MODE", "db_reset": "DB_RESET",
                                   "credentials_unreadable": "CREDENTIALS_UNREADABLE"}.get(code, "UNKNOWN"))
            nl.append((m.title, m.detail or ""))
        self._rebuild(self.notices_box, "notices", tuple(nl), lambda: [self._row(t, d, True) for t, d in nl])
        dim = getattr(app, "dimming", None)
        night = getattr(dim, "state", None) if dim is not None else None
        set_visible_if_changed(self.dim_row, night in ("NIGHT", "NIGHT_AWAKE"))
        if night in ("NIGHT", "NIGHT_AWAKE"):
            self.dim_row.set_value("Active" if night == "NIGHT" else "Awake for now")
        wx = getattr(app, "weather", None)
        wtxt = ""
        try:
            wtxt = wx.status_text() if wx is not None and getattr(wx, "active", True) else ""
        except Exception:
            wtxt = ""
        set_visible_if_changed(self.weather_row, bool(wtxt))
        if wtxt:
            self.weather_row.set_value(wtxt)

        # --- runs ---
        runs = tuple(status_summary.run_line(r, now) for r in (snap.runs[:RUNS_SHOWN] if snap else ()))
        self._rebuild(self.runs_box, "runs", runs,
                      lambda: [_small(t) for t in runs] or [_small("No updates yet")])

        # --- verdict ---
        offline = bool(getattr(eng, "offline", False)) or (net is not None and net.state.name in ("OFFLINE", "LIMITED"))
        v = status_summary.summarize(StatusInputs(
            power_problem=bool(dev and dev.undervoltage_now),
            safe_mode=bool(getattr(app, "safe_mode", False)),
            credentials_unreadable="credentials_unreadable" in notices,
            auth_failed=auth_bad, no_accounts=not accts, offline=offline,
            clock_unsynced=synced is False, failing_since=failing_since, failing_provider=failing_prov,
            last_success=last_ok, has_accounts=bool(accts), db_reset="db_reset" in notices), now)
        set_text_if_changed(self.verdict_label, v.text)
        for lv in ("ok", "warn", "bad"):
            set_class(self.verdict, f"verdict-{lv}", lv == v.level)
        self._fix_section = v.fix_section
        set_visible_if_changed(self.verdict_fix, bool(v.fix_section))
        self.last_verdict = v


register_section(SectionSpec("status", "Status", 70, StatusSection))
