"""Developer CLI: discover / add-account / list-accounts / remove-account. No gi.

The password is never taken from argv: it is prompted with getpass, or (dev only, for automated
local tests) read from the environment variable named by --password-env.

NOTE: this process writes settings.json itself. Stop the kiosk (`sudo systemctl stop calpi-kiosk`)
or restart it afterwards; the running app will not see CLI-added accounts until restarted.
"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from datetime import date
from pathlib import Path

from calpi.data.accounts import (list_accounts, remove_account, add_or_update_account)
from calpi.data.credentials import CredentialStore, Secret, install_log_redaction
from calpi.data.settings_store import SettingsStore
from calpi.sync import icloud
from calpi.sync.errors import ErrorCode, SyncError
from calpi.sync.http import HttpClient


def _password(args) -> Secret:
    if args.password_env:
        v = os.environ.get(args.password_env)
        if not v:
            raise SystemExit(f"environment variable {args.password_env} is not set")
        return Secret(v)
    return Secret(getpass.getpass("App-specific password: "))


def _print_discovery(d) -> None:
    print(f"principal: {d.principal_url}")
    print(f"home:      {d.calendar_home_url}")
    print(f"name:      {d.display_name or '-'}")
    print(f"calendars ({len(d.calendars)}):")
    for c in d.calendars:
        print(f"  {c.name}  {c.color or '-'}  {c.href}{'  (read-only)' if c.read_only else ''}")


def _client(args) -> HttpClient:
    c = HttpClient(allowed_auth_hosts=icloud.ALLOWED)
    if getattr(args, "dump_dir", None):
        out = Path(args.dump_dir)
        out.mkdir(parents=True, exist_ok=True)
        inner, n = c._transport, [0]

        def dumping(method, url, headers, body):
            status, rh, rb = inner(method, url, headers, body)
            n[0] += 1
            (out / f"{n[0]:02d}-{method}-{status}.xml").write_bytes(rb)   # anonymise before sharing
            return status, rh, rb
        c._transport = dumping
    return c


def _exit_code(e: SyncError) -> int:
    if e.code is ErrorCode.AUTH_FAILED:
        return 2
    if e.code in (ErrorCode.NETWORK_DOWN, ErrorCode.DNS_FAILED, ErrorCode.TIMEOUT,
                  ErrorCode.TLS_ERROR, ErrorCode.CLOCK_WRONG):
        return 3
    return 1


def _month(s: str | None):
    if not s:
        return None
    y, m = s.split("-")
    return int(y), int(m)


def _fetch(args, settings, credentials, state, client) -> int:
    from calpi.data import db, timeutil
    from calpi.data.accounts import get_account
    from calpi.data.event_store import EventStore
    from calpi.data.settings_store import K_SYNC_WINDOW_BACK, K_SYNC_WINDOW_FORWARD, REGISTRY, K_TIMEZONE
    from calpi.sync import fetch

    acc = get_account(settings, args.account)
    if acc is None:
        print("no such account", file=sys.stderr)
        return 1
    secret = credentials.get(acc.id)
    if secret is None:
        print("error: no stored password for this account", file=sys.stderr)
        return 2
    if K_TIMEZONE in REGISTRY:
        timeutil.set_display_tz(settings.get(K_TIMEZONE))
    tz = timeutil.display_tz()
    extra = None
    a, b = _month(args.from_month), _month(args.to_month)
    if a or b:
        today = timeutil.today()
        a = a or (today.year, today.month)
        b = b or a
        ey, em = fetch._add_months(b[0], b[1], 1)
        extra = (date(a[0], a[1], 1), date(ey, em, 1))
    window = fetch.compute_window(timeutil.today(), tz, settings.get(K_SYNC_WINDOW_BACK),
                                  settings.get(K_SYNC_WINDOW_FORWARD), extra)
    client = client or _client(args)
    if args.dry_run:
        return _dry_run(acc, secret, client, window, tz)
    store = EventStore(Path(state) / db.DB_NAME if state else None)
    if args.clear_sample:
        store.delete_sample_data()
    res = fetch.sync_account(acc, secret, store, window, force=args.force, client=client, tz=tz)
    if res.error:
        print(f"error: {res.error.value}: {res.detail}", file=sys.stderr)
        return 2 if res.error is ErrorCode.AUTH_FAILED else 1
    for c in res.calendars:
        extra_txt = f" {c.error.value}: {c.detail}" if c.error else ""
        print(f"{c.name}: {c.status} events={c.events} {c.duration_ms}ms{extra_txt}")
    return 0 if all(c.status != "error" for c in res.calendars) else 1


def _dry_run(acc, secret, client, window, tz) -> int:
    from calpi.sync import fetch
    from calpi.sync.ical_parse import parse_resources
    auth = (acc.username, secret)
    for rc in fetch.list_calendars(client, acc, auth):
        href = fetch.urljoin(acc.calendar_home_url, rc.href)
        cid = fetch.calendar_id_for(acc.id, href)
        try:
            events, st = parse_resources(fetch._fetch_blobs(client, auth, href, window), cid, window, tz)
        except SyncError as e:
            print(f"{rc.name}: error {e.code.value}: {e.detail}")
            continue
        print(f"{rc.name}: {len(events)} occurrences from {st.resources} resources ({st})")
        for e in sorted(events, key=lambda e: str(e.start))[:10]:
            when = e.start.isoformat() if e.all_day else e.start.astimezone(tz).isoformat(sep=" ")
            print(f"    {when}  {e.summary}")
    return 0


def main(argv=None, settings: SettingsStore | None = None,
         credentials: CredentialStore | None = None, client: HttpClient | None = None) -> int:
    ap = argparse.ArgumentParser(prog="calpi.sync.cli", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state-dir", help="state directory (default: the app's)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("discover", "add-account"):
        p = sub.add_parser(name)
        if name == "add-account":
            p.add_argument("--provider", default="icloud", choices=["icloud"])
        p.add_argument("--username", required=True)
        p.add_argument("--password-env", metavar="VAR", help="DEV ONLY: read the password from this env var")
        p.add_argument("--dump-dir", help="DEV ONLY: save raw response bodies here (anonymise before sharing)")
    sub.add_parser("list-accounts")
    f = sub.add_parser("fetch", help="download and store events (or --dry-run to print them)")
    f.add_argument("--account", required=True)
    f.add_argument("--force", action="store_true", help="ignore ctags")
    f.add_argument("--dry-run", action="store_true", help="fetch and parse, do not write")
    f.add_argument("--from", dest="from_month", metavar="YYYY-MM")
    f.add_argument("--to", dest="to_month", metavar="YYYY-MM")
    f.add_argument("--clear-sample", action="store_true", help="delete sample data first")
    f.add_argument("--dump-dir", help="DEV ONLY: save raw response bodies here")
    r = sub.add_parser("remove-account")
    r.add_argument("--id", required=True)
    args = ap.parse_args(argv)

    logging.basicConfig(level=os.environ.get("CALPI_LOG_LEVEL", "WARNING"))
    install_log_redaction()
    state = Path(args.state_dir) if args.state_dir else None
    settings = settings or SettingsStore(state)
    credentials = credentials or CredentialStore(state)

    try:
        if args.cmd == "list-accounts":
            for a in list_accounts(settings):
                print(f"{a.id}  {a.provider}  {a.username}  {a.display_name}  {a.calendar_home_url}")
            return 0
        if args.cmd == "remove-account":
            ok = remove_account(settings, credentials, args.id)
            print("removed" if ok else "no such account")
            return 0 if ok else 1
        if args.cmd == "fetch":
            return _fetch(args, settings, credentials, state, client)
        secret = _password(args)
        d = icloud.discover(args.username, secret, client or _client(args))
        _print_discovery(d)
        if args.cmd == "add-account":
            acc = add_or_update_account(settings, credentials, args.provider, args.username, secret, d)
            print(f"saved account {acc.id}")
        return 0
    except SyncError as e:
        print(f"error: {e.code.value}: {e.detail}", file=sys.stderr)
        return _exit_code(e)


if __name__ == "__main__":
    sys.exit(main())
