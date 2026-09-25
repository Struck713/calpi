"""Filesystem locations. No gi imports: used by the UI and the sync process."""
from __future__ import annotations
import os
from pathlib import Path

_override: Path | None = None


def set_state_dir_override(path: str | os.PathLike | None) -> None:
    """Set from --state-dir. Tests use it too."""
    global _override
    _override = Path(path) if path else None


def state_dir() -> Path:
    """Persistent state directory, created 0700 if missing.

    Precedence: --state-dir override > $STATE_DIRECTORY (systemd) > $CALPI_STATE_DIR > ~/.local/state/calpi
    """
    if _override is not None:
        p = _override
    elif os.environ.get("STATE_DIRECTORY"):
        # systemd may pass several colon-separated dirs; we only declare one.
        p = Path(os.environ["STATE_DIRECTORY"].split(":")[0])
    elif os.environ.get("CALPI_STATE_DIR"):
        p = Path(os.environ["CALPI_STATE_DIR"])
    else:
        p = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "calpi"
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p


def runtime_dir() -> Path:
    """Non-persistent scratch (tmpfs on the Pi). $RUNTIME_DIRECTORY > $XDG_RUNTIME_DIR/calpi > <state>/run"""
    if os.environ.get("RUNTIME_DIRECTORY"):
        p = Path(os.environ["RUNTIME_DIRECTORY"].split(":")[0])
    elif os.environ.get("XDG_RUNTIME_DIR"):
        p = Path(os.environ["XDG_RUNTIME_DIR"]) / "calpi"
    else:
        p = state_dir() / "run"
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p


def app_dir() -> Path:
    """Directory containing the calpi package (read-only on the Pi)."""
    return Path(__file__).resolve().parent


def asset(name: str) -> Path:
    return app_dir() / "assets" / name
