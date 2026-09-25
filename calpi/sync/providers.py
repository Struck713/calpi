"""Provider registry (US-20). No gi imports.

A provider has: name, display_name, auth_hosts(account), discover(fields, secret, client) ->
Discovery, sync(account, secret, store, window, force, client, tz) -> AccountResult.
Modules load lazily so importing this stays cheap and fetch.py <-> providers has no import cycle.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
import secrets as _secrets
from typing import Protocol
from urllib.parse import urlsplit

from calpi.data.credentials import CredentialStore, Secret
from calpi.data.models import Account
from calpi.data.settings_store import K_ACCOUNTS, SettingsStore
from calpi.sync.errors import ErrorCode, SyncError
from calpi.sync.http import HttpClient

_MODULES = {"icloud": "calpi.sync.provider_icloud", "caldav": "calpi.sync.provider_caldav",
            "ics": "calpi.sync.provider_ics"}


class Provider(Protocol):
    name: str
    display_name: str

    def auth_hosts(self, account: Account | None) -> tuple[str, ...]: ...
    def discover(self, fields: dict, secret: Secret, client: HttpClient | None = None): ...
    def sync(self, account, secret, store, window, force=False, client=None, tz=None): ...


def get(name: str) -> Provider:
    mod = _MODULES.get(name)
    if mod is None:
        raise SyncError(ErrorCode.UNKNOWN, f"unsupported provider {name!r}")
    return importlib.import_module(mod).PROVIDER


def all() -> list[tuple[str, str]]:            # noqa: A001
    """[(name, display_name)] in UI order."""
    return [(n, get(n).display_name) for n in _MODULES]


def make_client(account: Account, transport=None, **kw) -> HttpClient:
    p = get(account.provider)
    return HttpClient(allowed_auth_hosts=p.auth_hosts(account),
                      exact_auth_hosts=getattr(p, "exact_auth_hosts", False),
                      transport=transport, **kw)


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def save_account(settings: SettingsStore, credentials: CredentialStore, provider: str,
                 username: str, secret: Secret, discovery, server_url: str,
                 options: dict | None = None) -> Account:
    """Store a caldav/ics account. caldav is keyed by (server host, username); ics always new."""
    username = username.strip()
    existing = None
    if provider == "caldav":
        for d in settings.get(K_ACCOUNTS):
            if (d.get("provider") == provider and d.get("username", "").casefold() == username.casefold()
                    and host_of(d.get("server_url", "")) == host_of(server_url)):
                existing = Account(**{k: v for k, v in d.items() if k in Account.__dataclass_fields__})
    acc = Account(
        id=existing.id if existing else f"{provider}-{_secrets.token_hex(4)}",
        provider=provider, username=username,
        display_name=discovery.display_name or username, server_url=server_url,
        principal_url=discovery.principal_url, calendar_home_url=discovery.calendar_home_url,
        created_at=existing.created_at if existing
        else datetime.now(timezone.utc).isoformat(timespec="seconds"),
        options=dict(options or {}))
    old = credentials.get(acc.id) if existing else None
    credentials.set(acc.id, secret)
    try:
        others = [d for d in settings.get(K_ACCOUNTS) if d.get("id") != acc.id]
        settings.set(K_ACCOUNTS, others + [json.loads(json.dumps(asdict(acc)))])
    except Exception:
        if old is not None:
            credentials.set(acc.id, old)
        else:
            credentials.delete(acc.id)
        raise
    return acc
