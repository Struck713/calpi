"""Device health probes for the Status screen (US-31). No gi imports; every probe tolerates absence."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field

log = logging.getLogger("calpi.device_info")

TEMP_WARN_C = 80.0
DISK_WARN_BYTES = 500 * 1024 * 1024

_THROTTLE_BITS = {
    0: "undervoltage_now", 1: "freq_capped_now", 2: "throttled_now", 3: "soft_temp_limit_now",
    16: "undervoltage_past", 17: "freq_capped_past", 18: "throttled_past", 19: "soft_temp_limit_past",
}


def decode_throttled(value) -> dict[str, bool]:
    """'0x50005' (or an int) -> {name: bool} for the D3 bits. Unparseable -> all False."""
    try:
        n = int(value, 16) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        n = 0
    return {name: bool(n >> bit & 1) for bit, name in _THROTTLE_BITS.items()}


def parse_throttled_output(text: str) -> int | None:
    m = re.search(r"throttled=(0x[0-9a-fA-F]+)", text or "")
    return int(m.group(1), 16) if m else None


def parse_measure_temp(text: str) -> float | None:
    m = re.search(r"temp=(-?[0-9.]+)", text or "")
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def disk_free_bytes(path: str = "/") -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def power_codes(flags: dict[str, bool]) -> tuple[list[str], list[str]]:
    """(problems now, notes since boot) as messages.py codes."""
    now = []
    if flags.get("undervoltage_now"):
        now.append("POWER_UNDERVOLTAGE")
    if flags.get("soft_temp_limit_now"):
        now.append("TEMP_HIGH")
    past = []
    if not now and any(flags.get(k) for k in ("undervoltage_past", "freq_capped_past", "throttled_past",
                                              "soft_temp_limit_past")):
        past.append("POWER_THROTTLED_PAST")
    return now, past


@dataclass(frozen=True)
class DeviceInfo:
    throttled: dict = field(default_factory=lambda: decode_throttled(0))
    power_known: bool = False                 # False when vcgencmd is unavailable
    temp_c: float | None = None
    disk_free: int | None = None

    @property
    def undervoltage_now(self) -> bool:
        return bool(self.throttled.get("undervoltage_now"))

    @property
    def temp_high(self) -> bool:
        return self.temp_c is not None and self.temp_c > TEMP_WARN_C

    @property
    def disk_low(self) -> bool:
        return self.disk_free is not None and self.disk_free < DISK_WARN_BYTES


_warned_missing = False


def _vcgencmd(*args) -> str | None:
    global _warned_missing
    try:
        r = subprocess.run(["vcgencmd", *args], capture_output=True, text=True, timeout=3)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        if not _warned_missing:
            _warned_missing = True
            log.info("vcgencmd not available; skipping power/temperature checks")
        return None


def collect(path: str = "/") -> DeviceInfo:
    """Blocking (subprocess + statvfs): call from a worker thread."""
    t = _vcgencmd("get_throttled")
    raw = parse_throttled_output(t) if t else None
    temp = parse_measure_temp(_vcgencmd("measure_temp") or "")
    return DeviceInfo(decode_throttled(raw or 0), raw is not None, temp, disk_free_bytes(path))
