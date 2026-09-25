"""First-time setup wizard: pure decisions and step arithmetic (US-32). No gi imports."""
from __future__ import annotations


def decide_start_screen(setup_completed: bool, accounts: int,
                        safe_mode: bool) -> tuple[str, dict]:
    """Which screen to show at startup, plus settings migrations to apply.

    Safe mode never starts the wizard. A device set up before the wizard existed (accounts but no
    `setup_completed`) is silently marked complete.
    """
    if safe_mode:
        return "calendar", {}
    if not setup_completed and accounts > 0:
        return "calendar", {"setup_completed": True}
    return ("wizard" if not setup_completed else "calendar"), {}


def next_step(steps: list[str], current: str) -> str | None:
    if current not in steps:
        return None
    i = steps.index(current)
    return steps[i + 1] if i + 1 < len(steps) else None


def prev_step(steps: list[str], current: str) -> str | None:
    if current not in steps:
        return None
    i = steps.index(current)
    return steps[i - 1] if i > 0 else None


def resume_step(steps: list[str], saved: str | None) -> str:
    """The step to open: the saved one if it still exists, otherwise the first."""
    if saved in steps:
        return saved
    return steps[0]


def progress(steps_counted: list[str], current: str) -> tuple[int, int] | None:
    """(n, total) for a counted step, None for steps that don't count (Welcome, Done)."""
    if current not in steps_counted:
        return None
    return steps_counted.index(current) + 1, len(steps_counted)
