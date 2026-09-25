"""Screen brightness (US-29): kernel backlight, DDC/CI (ddcutil) or software dimming.

No gi imports: the UI-specific bits (main-thread hop, thread start, the dim layer) are injected,
so everything here is unit-testable with fakes. Backend I/O runs in ONE worker (serialised,
"latest value wins" coalescing); `probe()` also runs off the main thread.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("calpi.brightness")

MIN_PERCENT = 10
MAX_PERCENT = 100
SOFTWARE_MAX_ALPHA = 0.75
MAX_FAILURES = 3
DDC_TIMEOUT_S = 5
BACKLIGHT_ROOT = Path("/sys/class/backlight")

NOTES = {
    "probing": "Checking what this screen supports…",
    "backlight": "Screen backlight",
    "ddc": "Controlled through the monitor (DDC/CI)",
    "software": ("This screen can't be dimmed directly, so calpi darkens the picture instead. "
                 "For deeper dimming, use the monitor's own buttons."),
}


# ---------- pure helpers ----------

def clamp_percent(percent: int) -> int:
    return max(MIN_PERCENT, min(MAX_PERCENT, int(percent)))


def percent_to_raw(percent: int, raw_max: int, raw_min: int = 0) -> int:
    p = clamp_percent(percent)
    raw = raw_min + int(round(p / 100 * (raw_max - raw_min)))
    return max(raw_min, min(raw_max, raw))


def software_alpha(percent: int) -> float:
    """Overlay opacity: 0 at 100 %, SOFTWARE_MAX_ALPHA at 10 %."""
    p = clamp_percent(percent)
    return SOFTWARE_MAX_ALPHA * (MAX_PERCENT - p) / (MAX_PERCENT - MIN_PERCENT)


_VCP_RE = re.compile(r"^\s*VCP\s+([0-9A-Fa-f]{2})\s+C\s+(\d+)\s+(\d+)", re.M)


def parse_getvcp_terse(stdout: str) -> tuple[int, int] | None:
    """'VCP 10 C 50 100' -> (50, 100) (current, max)."""
    m = _VCP_RE.search(stdout or "")
    return (int(m.group(2)), int(m.group(3))) if m else None


def parse_detect_terse(stdout: str) -> list[dict]:
    """`ddcutil detect --terse` -> [{"bus": 2, "model": "..."}]. 'Invalid display' blocks are skipped."""
    out: list[dict] = []
    cur: dict | None = None
    for line in (stdout or "").splitlines():
        if re.match(r"^Display\s+\d+", line):
            cur = {"bus": None, "model": ""}
            out.append(cur)
        elif re.match(r"^\S", line):
            cur = None                                  # Invalid display / other header
        elif cur is not None:
            m = re.search(r"I2C bus:\s*/dev/i2c-(\d+)", line)
            if m:
                cur["bus"] = int(m.group(1))
            m = re.search(r"Monitor:\s*(.*\S)", line)
            if m:
                cur["model"] = m.group(1)
    return [d for d in out if d["bus"] is not None]


class Coalescer:
    """At most one job in flight; while busy only the latest submitted value is kept."""

    def __init__(self):
        self._lock = threading.Lock()
        self._busy = False
        self._pending: Any = None
        self._has_pending = False

    def submit(self, value) -> bool:
        """True: caller must start work with `value` now. False: queued (replacing older)."""
        with self._lock:
            if not self._busy:
                self._busy = True
                return True
            self._pending, self._has_pending = value, True
            return False

    def done(self):
        """Job finished: the next value to send, or None (and go idle)."""
        with self._lock:
            if self._has_pending:
                v, self._pending, self._has_pending = self._pending, None, False
                return v
            self._busy = False
            return None


# ---------- backends (I/O methods run in the worker thread) ----------

def _run(cmd: list[str], timeout: float = DDC_TIMEOUT_S) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise OSError(f"{cmd[0]} exited {r.returncode}: {(r.stderr or r.stdout).strip()[:200]}")
    return r.stdout


class BacklightSysfs:
    name = "backlight"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.max = int((self.path / "max_brightness").read_text())
        self.label = self.path.name

    @property
    def supports_power_off(self) -> bool:
        p = self.path / "bl_power"
        return p.exists() and _writable(p)

    def set(self, percent: int) -> None:
        (self.path / "brightness").write_text(str(percent_to_raw(percent, self.max, 1)))

    def power(self, on: bool) -> None:
        (self.path / "bl_power").write_text("0" if on else "4")


class DdcCi:
    name = "ddc"

    def __init__(self, bus: int, raw_max: int, label: str = "", run: Callable = _run,
                 supports_power_off: bool = False):
        self.bus, self.raw_max, self.label, self._run = bus, raw_max, label, run
        self.supports_power_off = supports_power_off

    def _base(self) -> list[str]:
        return ["ddcutil", "--bus", str(self.bus), "--noverify", "--sleep-multiplier", "0.5"]

    def set(self, percent: int) -> None:
        cmd = self._base() + ["setvcp", "10", str(percent_to_raw(percent, self.raw_max))]
        try:
            self._run(cmd)
        except (OSError, subprocess.SubprocessError):
            self._run(cmd)                       # DDC is flaky: retry once

    def power(self, on: bool) -> None:
        self._run(self._base() + ["setvcp", "d6", "1" if on else "4"])


class SoftwareDim:
    name = "software"
    supports_power_off = False
    label = ""

    def __init__(self, apply_alpha: Callable[[float], None],
                 call_on_main: Callable[..., None]):
        self._apply_alpha, self._call_on_main = apply_alpha, call_on_main

    def set(self, percent: int) -> None:
        self._call_on_main(self._apply_alpha, software_alpha(percent))

    def power(self, on: bool) -> None:           # never called (supports_power_off is False)
        raise OSError("software dimming cannot power the display off")


def _writable(path: Path) -> bool:
    import os
    return os.access(path, os.W_OK)


def probe(software_factory: Callable[[], SoftwareDim], *, backlight_root: Path = BACKLIGHT_ROOT,
          run: Callable = _run):
    """Pick the best backend. Blocking (ddcutil detect can take seconds): call off the main thread."""
    try:
        for dev in sorted(Path(backlight_root).glob("*")):
            if _writable(dev / "brightness") and (dev / "max_brightness").exists():
                b = BacklightSysfs(dev)
                log.info("brightness: backend=backlight (%s, max=%d)", dev.name, b.max)
                return b
    except (OSError, ValueError) as e:
        log.warning("brightness: backlight probe failed (%s)", e)
    try:
        displays = parse_detect_terse(run(["ddcutil", "detect", "--terse"], 15))
        for d in displays:
            vcp = parse_getvcp_terse(run(["ddcutil", "--bus", str(d["bus"]), "--terse", "getvcp", "10"]))
            if vcp is None or vcp[1] <= 0:
                continue
            try:
                run(["ddcutil", "--bus", str(d["bus"]), "--terse", "getvcp", "d6"])
                power = True
            except (OSError, subprocess.SubprocessError):
                power = False
            b = DdcCi(d["bus"], vcp[1], d["model"], run, power)
            log.info('brightness: backend=ddc (display "%s", max=%d)', d["model"], vcp[1])
            return b
    except (OSError, subprocess.SubprocessError) as e:
        log.info("brightness: ddcutil unavailable or no DDC display (%s)", e)
    log.info("brightness: backend=software")
    return software_factory()


# ---------- controller (main thread API) ----------

class CallbackList:
    def __init__(self):
        self._cbs: list[Callable[[], None]] = []

    def add(self, cb: Callable[[], None]) -> None:
        self._cbs.append(cb)

    def remove(self, cb) -> None:
        if cb in self._cbs:
            self._cbs.remove(cb)

    def fire(self) -> None:
        for cb in list(self._cbs):
            try:
                cb()
            except Exception:
                log.exception("brightness callback failed")


class BrightnessController:
    """Owns the backend. `settings` needs get/subscribe; `key` is K_BRIGHTNESS.

    Injected (defaults are the real thing, set by app.py): apply_alpha (paints the dim layer),
    call_on_main, run_async(fn) (starts fn in a worker), probe_async(work, on_done, on_error).
    """

    def __init__(self, settings, key: str, apply_alpha: Callable[[float], None], *,
                 call_on_main: Callable[..., None], run_async: Callable[[Callable], None],
                 probe_async: Callable[..., None], probe_fn: Callable = probe):
        self.settings, self._key = settings, key
        self._apply_alpha, self._call_on_main, self._run_async = apply_alpha, call_on_main, run_async
        self.backend = None
        self.override: int | None = None
        self.preview: int | None = None
        self._failures = 0
        self._coalescer = Coalescer()
        self.ready_callbacks = CallbackList()
        self._token = settings.subscribe(key, self._on_setting)
        soft = lambda: SoftwareDim(self._apply_alpha, self._call_on_main)  # noqa: E731
        probe_async(lambda: probe_fn(soft), self._on_probed, self._probe_failed)

    # ---- API (main thread) ----
    def level(self) -> int:
        if self.override is not None:
            return clamp_percent(self.override)
        if self.preview is not None:
            return clamp_percent(self.preview)
        return clamp_percent(self.settings.get(self._key))

    @property
    def backend_name(self) -> str:
        return self.backend.name if self.backend else "probing"

    @property
    def supports_power_off(self) -> bool:
        return bool(self.backend and self.backend.supports_power_off)

    def note(self) -> str:
        return NOTES[self.backend_name]

    def set_override(self, percent: int | None) -> None:
        """Temporary level (US-30); None returns to the saved value. Never written to settings."""
        self.override = percent
        self.apply()

    def set_preview(self, percent: int | None) -> None:
        """Live feedback while a stepper is debounced; dropped when the setting is written."""
        self.preview = percent
        self.apply()

    def apply(self) -> None:
        if self.backend is None:            # still probing: applied when the probe finishes
            return
        value = self.level()
        if self._coalescer.submit(value):
            self._run_async(lambda: self._worker(value))

    # ---- internals ----
    def _on_setting(self, *_):
        self.preview = None
        self.apply()

    def _on_probed(self, backend) -> None:
        self.backend = backend
        self.apply()
        self.ready_callbacks.fire()

    def _probe_failed(self, exc) -> None:
        log.warning("brightness: probe failed (%s), using software dimming", exc)
        self._on_probed(SoftwareDim(self._apply_alpha, self._call_on_main))

    def _worker(self, value: int) -> None:
        while True:
            backend = self.backend
            try:
                backend.set(value)
                self._failures = 0
            except Exception as e:  # noqa: BLE001
                log.warning("brightness: %s set failed: %s", backend.name, e)
                self._failures += 1
                if self._failures >= MAX_FAILURES and backend.name != "software":
                    self._call_on_main(self._fall_back_to_software)
            value = self._coalescer.done()
            if value is None:
                return

    def _fall_back_to_software(self) -> None:
        if self.backend is not None and self.backend.name == "software":
            return
        log.warning("brightness: %d failures in a row, falling back to software dimming",
                    MAX_FAILURES)
        self._failures = 0
        self.backend = SoftwareDim(self._apply_alpha, self._call_on_main)
        self.apply()
        self.ready_callbacks.fire()
