"""NetworkManager state mapping (US-17). No gi."""
from __future__ import annotations

import enum


class NetState(enum.Enum):
    ONLINE = "online"
    LIMITED = "limited"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


def map_state(nm_state: int) -> NetState:
    if nm_state == 70:
        return NetState.ONLINE
    if nm_state in (50, 60):
        return NetState.LIMITED
    if nm_state == 0:
        return NetState.UNKNOWN
    return NetState.OFFLINE
