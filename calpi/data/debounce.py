"""Pure debouncer with injectable scheduler (no gi). Used by StepperRow / list filtering.

schedule(delay_seconds, fn) -> handle;  cancel(handle) -> None.
"""
from __future__ import annotations

from typing import Any, Callable


class Debouncer:
    def __init__(self, delay: float, action: Callable[[Any], None],
                 schedule: Callable[[float, Callable[[], None]], Any],
                 cancel: Callable[[Any], None]):
        self.delay = delay
        self._action = action
        self._schedule = schedule
        self._cancel = cancel
        self._handle: Any = None
        self._pending = False
        self._value: Any = None

    @property
    def pending(self) -> bool:
        return self._pending

    def call(self, value: Any) -> None:
        """Remember value and (re)arm the timer."""
        if self._handle is not None:
            self._cancel(self._handle)
        self._value = value
        self._pending = True
        self._handle = self._schedule(self.delay, self._fire)

    def _fire(self) -> None:
        self._handle = None
        self.flush()

    def flush(self) -> None:
        """Run the pending action now (if any)."""
        if self._handle is not None:
            self._cancel(self._handle)
            self._handle = None
        if self._pending:
            self._pending = False
            value, self._value = self._value, None
            self._action(value)

    def cancel(self) -> None:
        if self._handle is not None:
            self._cancel(self._handle)
            self._handle = None
        self._pending = False
        self._value = None
