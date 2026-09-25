"""Minimal sd_notify with the stdlib (no python3-systemd). No gi imports.

Every call is a no-op when NOTIFY_SOCKET is unset (dev). Pings must only ever come from the
main loop (US-12 D3): a thread would keep pinging while the UI is frozen.
"""
from __future__ import annotations

import logging
import os
import socket

log = logging.getLogger("calpi.watchdog")

DEFAULT_PING_SECONDS = 10


def _addr() -> str | None:
    a = os.environ.get("NOTIFY_SOCKET")
    if not a:
        return None
    return "\0" + a[1:] if a.startswith("@") else a


def notify(msg: str) -> bool:
    addr = _addr()
    if addr is None:
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as s:
            s.connect(addr)
            s.sendall(msg.encode())
        return True
    except OSError as e:
        log.warning("sd_notify failed: %s", e)
        return False


def ready(status: str = "running") -> bool:
    return notify(f"READY=1\nSTATUS={status}")


def ping() -> bool:
    return notify("WATCHDOG=1")


def stopping() -> bool:
    return notify("STOPPING=1")


def status(text: str) -> bool:
    return notify(f"STATUS={text}")


def watchdog_interval_s() -> float | None:
    """WATCHDOG_USEC as seconds, if systemd passed it to us (it may not reach a child of cage)."""
    try:
        return int(os.environ["WATCHDOG_USEC"]) / 1e6
    except (KeyError, ValueError):
        return None
