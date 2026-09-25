"""Account records (settings, no secrets) + secrets (CredentialStore). No gi imports.

Call add_or_update_account/remove_account from the main thread in the UI process (settings rule).
"""
from __future__ import annotations

import secrets as _secrets
from dataclasses import asdict, fields
from datetime import datetime, timezone

from calpi.data.credentials import CredentialStore, Secret
from calpi.data.models import Account
from calpi.data.settings_store import K_ACCOUNTS, SettingsStore

ICLOUD_SERVER = "https://caldav.icloud.com/"
_FIELDS = {f.name for f in fields(Account)}


def list_accounts(settings: SettingsStore) -> list[Account]:
    return [Account(**{k: v for k, v in d.items() if k in _FIELDS}) for d in settings.get(K_ACCOUNTS)]


def get_account(settings, account_id: str) -> Account | None:
    return next((a for a in list_accounts(settings) if a.id == account_id), None)


def find_account(settings, provider: str, username: str) -> Account | None:
    u = username.strip().casefold()
    return next((a for a in list_accounts(settings)
                 if a.provider == provider and a.username.casefold() == u), None)


def add_or_update_account(settings: SettingsStore, credentials: CredentialStore, provider: str,
                          username: str, secret: Secret, discovery,
                          server_url: str = ICLOUD_SERVER) -> Account:
    username = username.strip()
    existing = find_account(settings, provider, username)
    acc = Account(
        id=existing.id if existing else f"{provider}-{_secrets.token_hex(4)}",
        provider=provider, username=username,
        display_name=discovery.display_name or username,
        server_url=server_url, principal_url=discovery.principal_url,
        calendar_home_url=discovery.calendar_home_url,
        created_at=existing.created_at if existing
        else datetime.now(timezone.utc).isoformat(timespec="seconds"))
    old_secret = credentials.get(acc.id) if existing else None
    credentials.set(acc.id, secret)
    try:
        others = [a for a in list_accounts(settings) if a.id != acc.id]
        settings.set(K_ACCOUNTS, [asdict(a) for a in others + [acc]])
    except Exception:
        if old_secret is not None:
            credentials.set(acc.id, old_secret)
        else:
            credentials.delete(acc.id)
        raise
    return acc


def remove_account(settings, credentials, account_id: str) -> bool:
    accs = list_accounts(settings)
    if not any(a.id == account_id for a in accs):
        return False
    settings.set(K_ACCOUNTS, [asdict(a) for a in accs if a.id != account_id])
    credentials.delete(account_id)
    return True
