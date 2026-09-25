"""About section: version, build, IP address(es), uptime, OS release, data folder (US-22)."""
from __future__ import annotations

import json
import logging
import subprocess

from gi.repository import Gtk

from calpi import __version__, paths
from calpi.tasks import run_in_thread
from calpi.widgets.settings.registry import SectionSpec, register_section
from calpi.widgets.settings.rows import InfoRow, SettingsGroup

log = logging.getLogger("calpi.settings.about")


def build_stamp() -> str:
    try:
        return (paths.app_dir() / "BUILD").read_text().strip() or "dev"
    except OSError:
        return "dev"


def os_pretty_name(path: str = "/etc/os-release") -> str:
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


def parse_ip_json(text: str) -> list[str]:
    """Non-loopback IPv4 addresses from `ip -j -4 addr` output."""
    out = []
    for iface in json.loads(text):
        if iface.get("ifname") == "lo":
            continue
        for a in iface.get("addr_info", []):
            if a.get("family") == "inet" and a.get("local"):
                out.append(f"{a['local']} ({iface.get('ifname', '?')})")
    return out


def format_uptime(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return f"{d} d {h} h {m} min"
    if h:
        return f"{h} h {m} min"
    return f"{m} min"


def _collect() -> tuple[str, str]:
    """Runs in a worker thread (blocking subprocess is fine here)."""
    try:
        r = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=5)
        ips = ", ".join(parse_ip_json(r.stdout)) or "not connected"
    except Exception as e:  # noqa: BLE001
        log.warning("ip lookup failed: %s", e)
        ips = "unknown"
    try:
        with open("/proc/uptime") as f:
            up = format_uptime(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        up = "unknown"
    return ips, up


class AboutSection:
    def __init__(self, ctx):
        self.ctx = ctx
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        g = SettingsGroup("About this calendar")
        g.add(InfoRow("Version", __version__))
        g.add(InfoRow("Build", build_stamp()))
        self.ip = g.add(InfoRow("IP address", "…"))
        self.uptime = g.add(InfoRow("Uptime", "…"))
        self.system = g.add(InfoRow("System", os_pretty_name()))
        g.add(InfoRow("Data folder", str(paths.state_dir())))
        self.widget.append(g)
        self._showing = False

    def _add_zone_rows(self, g) -> None:
        """US-28: show the system zone and display zone separately when they differ."""
        from calpi.data import timeutil
        from calpi.data.settings_store import K_TIMEZONE
        settings = getattr(self.ctx.app, "settings", None)
        chosen = settings.get(K_TIMEZONE) if settings else None
        system = timeutil.system_tz_name()
        if chosen and chosen != system:
            g.add(InfoRow("Display time zone", chosen))
            g.add(InfoRow("System time zone", system,
                          description="The system zone hasn't been changed to match."))
        else:
            g.add(InfoRow("Time zone", system))

    def on_show(self):
        self._showing = True
        run_in_thread(_collect, on_done=self._done, name="about-info")

    def on_hide(self):
        self._showing = False

    def _done(self, result):
        ips, up = result
        self.ip.set_value(ips)
        self.uptime.set_value(up)


register_section(SectionSpec("about", "About", 90, AboutSection))
