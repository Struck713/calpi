"""Account records (settings, no secrets) + secrets (CredentialStore). No gi imports.

Call add_or_update_account/remove_account from the main thread in the UI process (settings rule).
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets as _secrets
from dataclasses import asdict, fields
from datetime import datetime, timezone

from calpi.data.credentials import CredentialStore, Secret
from calpi.data.models import Account, Calendar
from calpi.data.settings_store import K_ACCOUNTS, SettingsStore

log = logging.getLogger("calpi.accounts")
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


def remove_account(settings, credentials, account_id: str, store=None, forget_status=None) -> bool:
    """Remove the record, the secret, the calendars (events cascade) and the sync status.

    Every step is isolated, so a failure part-way still lets reconcile_calendars finish the job.
    Returns False when the account wasn't in settings.
    """
    accs = list_accounts(settings)
    known = any(a.id == account_id for a in accs)
    steps = []
    if known:
        steps.append(("settings", lambda: settings.set(
            K_ACCOUNTS, [asdict(a) for a in accs if a.id != account_id])))
    steps.append(("credentials", lambda: credentials.delete(account_id)))
    if store is not None:
        steps.append(("calendars", lambda: store.delete_calendars_for_account(account_id)))
    if forget_status is not None:
        steps.append(("status", forget_status))
    for name, fn in steps:
        try:
            fn()
        except Exception:
            log.exception("remove_account %s: step %s failed", account_id, name)
    return known


def reconcile_calendars(settings, store) -> int:
    """Delete calendars whose account is no longer configured (sample calendars are kept)."""
    ids = {a.id for a in list_accounts(settings)}
    n = 0
    for cal in store.list_calendars():
        if cal.account_id is None or cal.id.startswith("sample:") or cal.account_id in ids:
            continue
        log.info("reconcile: removing orphaned calendar %s (account %s)", cal.id, cal.account_id)
        store.delete_calendar(cal.id)
        n += 1
    return n


def calendar_id_for(account_id: str, href: str) -> str:
    try:
        from calpi.sync.fetch import calendar_id_for as real      # US-15 owns the id scheme
        return real(account_id, href)
    except ImportError:
        return f"{account_id}:{hashlib.sha1(href.encode()).hexdigest()[:12]}"


def apply_calendar_selection(store, account_id: str, remotes, selected_hrefs=None) -> None:
    """Upsert the discovered calendars. selected_hrefs=None: leave existing rows' flags alone and
    show new rows; otherwise (new sign-in) hidden = href not selected for every row."""
    for i, rc in enumerate(remotes):
        cid = calendar_id_for(account_id, rc.href)
        existed = store.get_calendar(cid) is not None
        store.upsert_calendar(Calendar(id=cid, remote_name=rc.name, account_id=account_id,
                                       remote_href=rc.href, remote_color=rc.color,
                                       sort_order=rc.order or 0))
        if selected_hrefs is not None:
            store.set_calendar_overrides(cid, hidden=rc.href not in selected_hrefs)
        elif not existed:
            store.set_calendar_overrides(cid, hidden=False)


_APPLE_ID_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_APP_PW_RE = re.compile(r"^[a-z]{4}-[a-z]{4}-[a-z]{4}-[a-z]{4}$")
_PW_RAW_RE = re.compile(r"^[a-z]{4}(-?[a-z]{4}){3}$")


def normalize_apple_id(s: str) -> str:
    s = s.strip()
    if "@" in s:
        local, _, domain = s.rpartition("@")
        return f"{local}@{domain.lower()}"
    return s


def normalize_app_password(s: str) -> str:
    t = re.sub(r"\s+", "", s)
    low = t.lower()
    if _PW_RAW_RE.match(low):
        flat = low.replace("-", "")
        return "-".join(flat[i:i + 4] for i in range(0, 16, 4))
    return t


def validate_apple_id(s: str) -> str | None:
    if not _APPLE_ID_RE.match(s or ""):
        return "Enter your Apple ID, which looks like name@icloud.com."
    return None


def validate_app_password(s: str) -> tuple[str | None, bool]:
    """(error, warn_only). Unusual but long-enough passwords are allowed with a warning."""
    if _APP_PW_RE.match(s or ""):
        return None, False
    if len(s or "") >= 8:
        return "This doesn't look like an app-specific password (abcd-efgh-ijkl-mnop).", True
    return "Enter the app-specific password. It looks like abcd-efgh-ijkl-mnop.", False
