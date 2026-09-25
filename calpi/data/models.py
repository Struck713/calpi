"""Plain data types for the event store. No gi imports."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

DEFAULT_CALENDAR_COLOR = "#9aa4ae"


@dataclass(frozen=True, slots=True)
class Calendar:
    id: str
    remote_name: str
    account_id: str | None = None
    remote_href: str | None = None
    remote_color: str | None = None
    user_name: str | None = None
    user_color: str | None = None
    hidden: bool = False
    sort_order: int = 0

    @property
    def name(self) -> str:
        return self.user_name or self.remote_name

    @property
    def color(self) -> str:
        return self.user_color or self.remote_color or DEFAULT_CALENDAR_COLOR


@dataclass(frozen=True, slots=True)
class Event:
    calendar_id: str
    uid: str
    summary: str
    all_day: bool
    start: datetime | date      # aware UTC datetime if timed, date if all-day
    end: datetime | date        # exclusive
    recurrence_id: str = ""
    location: str = ""
    description: str = ""
    status: str = "CONFIRMED"   # CONFIRMED | TENTATIVE (CANCELLED is never stored)
    tzid: str | None = None

    def __post_init__(self):
        # datetime is a subclass of date: always check datetime first.
        if self.all_day:
            if isinstance(self.start, datetime) or isinstance(self.end, datetime):
                raise ValueError("all-day events use date, not datetime")
            if not isinstance(self.start, date) or not isinstance(self.end, date):
                raise ValueError("all-day events need dates")
        else:
            for v in (self.start, self.end):
                if not isinstance(v, datetime) or v.tzinfo is None:
                    raise ValueError("timed events need aware datetimes")
        if self.end < self.start:
            raise ValueError("end before start")


@dataclass(frozen=True, slots=True)
class Account:
    """A calendar account. Never holds the secret (that lives in CredentialStore under `id`)."""
    id: str
    provider: str
    username: str
    display_name: str
    server_url: str
    principal_url: str
    calendar_home_url: str
    created_at: str          # ISO UTC
    options: dict = field(default_factory=dict)   # US-20: provider options, e.g. {"color": "#ff8800"}


@dataclass(frozen=True, slots=True)
class RemoteCalendar:
    href: str
    name: str
    color: str | None = None
    ctag: str | None = None
    sync_token: str | None = None
    order: int | None = None
    read_only: bool = False
