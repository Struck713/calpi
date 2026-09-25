"""Ways to turn the display output off and on (US-30). No gi imports.

Preference order (D3): wlopm (DPMS, keeps the mode) > backlight bl_power > DDC VCP D6 >
wlr-randr > black overlay. `probe()` blocks (subprocesses): call it off the main thread.

Each method has `name`, `trusted`, `off()` and `on()`. Untrusted methods (DDC D6, wlr-randr) can
leave a screen that cannot be woken, so they are only used automatically once the owner has
confirmed a working off/on cycle with Preview (`confirmed_method` in the dim_schedule setting).
`main_thread = True` methods (the black overlay) must be called on the main thread; all others
block and belong in a worker.
"""
from __future__ import annotations

import logging
import re
import subprocess
from typing import Callable

log = logging.getLogger("calpi.display_power")

CMD_TIMEOUT_S = 5
DEFAULT_OUTPUT = "HDMI-A-1"        # recorded in US-01 for the target monitor


def _run(cmd: list[str], timeout: float = CMD_TIMEOUT_S) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise OSError(f"{cmd[0]} exited {r.returncode}: {(r.stderr or r.stdout).strip()[:200]}")
    return r.stdout


def parse_wlopm(stdout: str) -> list[str]:
    """`wlopm` prints `<output> on|off` lines. Returns the output names."""
    out = []
    for line in (stdout or "").splitlines():
        m = re.match(r"^\s*(\S+)\s+(on|off|standby|suspend)\s*$", line, re.I)
        if m:
            out.append(m.group(1))
    return out


def parse_wlr_randr(stdout: str) -> list[str]:
    """`wlr-randr` prints each output as an unindented `NAME "description"` line."""
    return [line.split()[0] for line in (stdout or "").splitlines()
            if line and not line[0].isspace()]


class Wlopm:
    name, trusted, main_thread = "wlopm", True, False

    def __init__(self, output: str, run: Callable = _run):
        self.output, self._run = output, run

    def off(self) -> None:
        self._run(["wlopm", "--off", self.output])

    def on(self) -> None:
        self._run(["wlopm", "--on", self.output])


class BacklightPower:
    name, trusted, main_thread = "backlight", True, False

    def __init__(self, backend):
        self._backend = backend

    def off(self) -> None:
        self._backend.power(False)

    def on(self) -> None:
        self._backend.power(True)


class DdcPower:
    name, trusted, main_thread = "ddc", False, False

    def __init__(self, backend):
        self._backend = backend

    def off(self) -> None:
        self._backend.power(False)

    def on(self) -> None:
        self._backend.power(True)


class WlrRandr:
    name, trusted, main_thread = "wlr-randr", False, False

    def __init__(self, output: str, run: Callable = _run):
        self.output, self._run = output, run

    def off(self) -> None:
        self._run(["wlr-randr", "--output", self.output, "--off"])

    def on(self) -> None:
        self._run(["wlr-randr", "--output", self.output, "--on"])


class BlackOverlay:
    """Fills the screen with black through the dim layer. The backlight stays on."""
    name, trusted, main_thread = "overlay", True, True

    def __init__(self, apply_alpha: Callable[[float], None], restore: Callable[[], None]):
        self._apply_alpha, self._restore = apply_alpha, restore

    def off(self) -> None:
        self._apply_alpha(1.0)

    def on(self) -> None:
        self._apply_alpha(0.0)
        self._restore()          # a software-dim backend repaints its own alpha


def probe(brightness_backend, black_overlay: BlackOverlay, *, run: Callable = _run) -> list:
    """The ordered list of candidate methods, always ending with `black_overlay`."""
    methods: list = []
    output = None
    try:
        outputs = parse_wlopm(run(["wlopm"]))
        if outputs:
            output = outputs[0]
            methods.append(Wlopm(output, run))
    except (OSError, subprocess.SubprocessError) as e:
        log.info("display power: wlopm unavailable (%s)", e)
    if getattr(brightness_backend, "supports_power_off", False):
        if brightness_backend.name == "backlight":
            methods.append(BacklightPower(brightness_backend))
        elif brightness_backend.name == "ddc":
            methods.append(DdcPower(brightness_backend))
    try:
        outputs = parse_wlr_randr(run(["wlr-randr"]))
        if outputs:
            methods.append(WlrRandr(output or outputs[0], run))
    except (OSError, subprocess.SubprocessError) as e:
        log.info("display power: wlr-randr unavailable (%s)", e)
    methods.append(black_overlay)
    log.info("display power: methods=%s", ",".join(m.name for m in methods))
    return methods


def output_name(methods: list) -> str:
    for m in methods:
        if getattr(m, "output", None):
            return m.output
    return DEFAULT_OUTPUT
