"""iCloud provider: CalDAV with a fixed server and allowed host icloud.com. No gi imports."""
from __future__ import annotations

from calpi.sync import icloud


class ICloudProvider:
    name = "icloud"
    display_name = "iCloud"
    exact_auth_hosts = False

    def auth_hosts(self, account=None):
        return icloud.ALLOWED

    def discover(self, fields, secret, client=None):
        return icloud.discover(fields["username"], secret, client)

    def sync(self, account, secret, store, window, force=False, client=None, tz=None):
        from calpi.sync import fetch
        return fetch.sync_caldav_account(account, secret, store, window, force=force,
                                         client=client, tz=tz)


PROVIDER = ICloudProvider()
