"""User-facing problem messages (US-38): the single source of plain-language problem text. No gi imports.

`describe(code, context=..., provider=..., account=..., ssid=..., last_update=...)` -> `Message`.
Contexts: header (indicator, <= 32 chars), banner (title <= 60, detail <= 160), form (inline in a
form), toast (<= 60), status (Status screen: title + full detail + fix).

Wording rules (the texts are the product):
* Say what is wrong in everyday words, what the device is still doing, and what to do.
* No blame, no exclamation marks, no jargon (protocol names, status numbers, "exception").
  A code and a short technical detail may appear only in the Status screen's small technical line,
  which is built by the widget, not here.
* Use {provider} ("iCloud", or the provider's display name), {account}, {ssid}, {last_update}.
* New problems = a new CATALOGUE entry plus a producer. Never inline problem text elsewhere.

Compatible with the US-31 interface: Message(title, detail, fix_label, fix_section) (fix_section is an
alias of fix_target).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

CONTEXTS = ("header", "banner", "form", "toast", "status")


@dataclass(frozen=True)
class Message:
    title: str
    detail: str | None = None
    fix_label: str | None = None
    fix_target: str | None = None          # settings section id, or "update_password"
    severity: str = "warning"              # info | warning | error

    @property
    def fix_section(self) -> str | None:   # US-31 D2 name
        return self.fix_target


@dataclass(frozen=True)
class Entry:
    severity: str
    banner_title: str
    detail: str
    header: str | None = None
    banner_detail: str | None = None       # short one-line version of `detail` (default: detail)
    form: str | None = None
    toast: str | None = None
    fix_label: str | None = None
    fix_target: str | None = None
    grace_s: int = 0


_OFF = "Couldn't update: offline"
_SIGN = "Couldn't update: sign-in problem"
_NORESP = "Couldn't update: {provider} not responding"
_GENERIC = "Couldn't update"
_LATER = "{provider} isn't responding right now. Try again in a few minutes."
_SECURE = ("calpi's clock or security settings are wrong, so it can't connect securely. "
           "Make sure it's online so the clock can set itself, then try again.")
_NONET = "calpi isn't connected to the internet. Check Wi-Fi in Settings → Network."

_OFFLINE_DETAIL = ("It can't reach the internet, so it's showing the events it saved at {last_update}. "
                   "It will update by itself when the connection is back.")
_OFFLINE_SHORT = "It's showing the events it saved. It will update when the connection is back."
_REVOKED_DETAIL = ("{provider} stopped accepting calpi's password for {account}. This happens when you "
                   "change your Apple ID password or revoke the app-specific password. Create a new "
                   "app-specific password and enter it.")


def _offline() -> Entry:
    return Entry("warning", "calpi is offline", _OFFLINE_DETAIL, header="Offline", banner_detail=_OFFLINE_SHORT,
                 form=_NONET, toast=_OFF, fix_label="Network settings", fix_target="network", grace_s=1800)


CATALOGUE: dict[str, Entry] = {
    "OFFLINE": _offline(),
    "NETWORK_DOWN": _offline(),
    "DNS_FAILED": _offline(),
    "TIMEOUT": Entry("warning", "{provider} isn't responding",
                     "{provider} is slow or not answering, so calpi is showing the events it saved at "
                     "{last_update}. It will keep trying.",
                     banner_detail="calpi is showing the events it saved. It will keep trying.",
                     form=_LATER, toast=_NORESP, grace_s=1800),
    "SERVER_ERROR": Entry("warning", "{provider} isn't responding",
                          "{provider} is having trouble, so calpi is showing the events it saved at "
                          "{last_update}. It will keep trying.",
                          banner_detail="calpi is showing the events it saved. It will keep trying.",
                          form=_LATER, toast=_NORESP, grace_s=3600),
    "RATE_LIMITED": Entry("warning", "{provider} asked calpi to slow down",
                          "{provider} received too many requests, so calpi is waiting before it tries "
                          "again. Saved events are still shown.",
                          banner_detail="calpi is waiting before it tries again. Saved events are still shown.",
                          form=_LATER, toast=_NORESP, grace_s=3600),
    "AUTH_FAILED": Entry("error", "{provider} needs you to sign in",
                         "{provider} didn't accept the username and password for {account}. Check both "
                         "and sign in again.",
                         banner_detail="It didn't accept the saved username and password. Sign in again.",
                         header="Sign-in problem",
                         form="{provider} didn't accept this username and password. Check both.",
                         toast=_SIGN, fix_label="Update password", fix_target="update_password"),
    "AUTH_REVOKED": Entry("error", "{provider} needs you to sign in again", _REVOKED_DETAIL,
                          header="Sign-in problem",
                          banner_detail="It stopped accepting calpi's password. Create a new app-specific password.",
                          form="{provider} stopped accepting calpi's password. Create a new app-specific "
                               "password and enter it.",
                          toast=_SIGN, fix_label="Update password", fix_target="update_password"),
    "TLS_ERROR": Entry("warning", "calpi can't connect securely",
                       "calpi couldn't make a secure connection to {provider}. Check that the clock is "
                       "right and that this is a normal home network.",
                       banner_detail="Check that the clock is right and that this is a normal network.",
                       form=_SECURE, toast=_GENERIC, fix_label="Network settings", fix_target="network",
                       grace_s=1800),
    "CLOCK_WRONG": Entry("warning", "calpi's clock is wrong",
                         "It can't connect securely until the clock is set. Make sure it's connected to the "
                         "internet. The clock sets itself.",
                         banner_detail="Make sure it's connected to the internet. The clock sets itself.",
                         form=_SECURE, toast=_GENERIC, fix_label="Network settings", fix_target="network",
                         grace_s=900),
    "CLOCK_UNSYNCED": Entry("error", "calpi's clock isn't set",
                            "The date and time may be wrong until calpi can reach the internet. Make sure "
                            "it's connected to the internet. The clock sets itself.",
                            header="Clock not set",
                            banner_detail="Make sure it's connected to the internet. The clock sets itself.",
                            toast=_GENERIC, fix_label="Network settings", fix_target="network", grace_s=900),
    "NOT_FOUND": Entry("warning", "A calendar couldn't be found",
                       "{provider} says a calendar or address doesn't exist any more. Check the account "
                       "in Settings.",
                       banner_detail="Check the account in Settings.",
                       form="Nothing was found at that address. Check it and try again.", toast=_GENERIC,
                       fix_label="Accounts", fix_target="accounts", grace_s=3600),
    "PARSE_ERROR": Entry("warning", "Some events couldn't be read",
                         "{provider} sent data calpi couldn't understand. The rest of the calendar is "
                         "still shown.",
                         form="That didn't look like a calendar. Check the address and try again.",
                         toast=_GENERIC, grace_s=3600),
    "CREDENTIALS_UNREADABLE": Entry("error", "calpi can't read its saved sign-in details",
                                    "The memory card may have moved to another device, so calpi can't read "
                                    "the saved passwords. Sign in again.",
                                    header="Sign-in problem",
                                    banner_detail="The memory card may have moved to another device. Sign in again.",
                                    form="calpi can't read its saved sign-in details. Sign in again.",
                                    toast=_SIGN, fix_label="Accounts", fix_target="accounts"),
    "DISK_FULL": Entry("warning", "calpi's storage is full",
                       "There's no room left to save calendar data. Free some space or use a larger "
                       "memory card.", toast=_GENERIC),
    "UNKNOWN": Entry("warning", "Something went wrong while updating",
                     "calpi will keep trying. If this keeps happening, restart it.",
                     form="Something went wrong. Try again.", toast=_GENERIC, grace_s=3600),
    "NO_ACCOUNTS": Entry("info", "No calendar account yet",
                         "Add an account to see your events.", fix_label="Add account", fix_target="accounts"),
    "SAFE_MODE": Entry("error", "calpi is in safe mode",
                       "calpi restarted several times in a row, so syncing and extras are paused. Restart "
                       "it. If this keeps happening, see Status.",
                       header="Safe mode", banner_detail="Syncing and extras are paused. Restart calpi.",
                       fix_label="Status", fix_target="status"),
    "DB_RESET": Entry("info", "Calendar data was reset and is downloading again",
                      "calpi's saved calendar data was damaged and has been cleared. Events will come back "
                      "after the next update.", banner_detail="Events will come back after the next update."),
    "POWER_UNDERVOLTAGE": Entry("error", "The power supply is too weak",
                                "This can make calpi slow or unreliable. Use the official Raspberry Pi power "
                                "supply (5.1 V, 2.5 A).", header="Power problem"),
    "POWER_THROTTLED_PAST": Entry("warning", "The power supply was too weak earlier",
                                  "calpi slowed down since it started because of low power. Use the official "
                                  "Raspberry Pi power supply (5.1 V, 2.5 A)."),
    "TEMP_HIGH": Entry("warning", "calpi is running hot",
                       "Make sure the vents aren't covered and it isn't in direct sun."),
    "DISK_LOW": Entry("warning", "calpi's storage is almost full",
                      "There's little room left on the memory card. Free some space or use a larger card."),
    "WIFI_WRONG_PASSWORD": Entry("warning", "Wrong Wi-Fi password",
                                 "The password for {ssid} wasn't accepted.",
                                 form="Wrong password for {ssid}. Check it and try again.",
                                 toast="Wrong password for {ssid}"),
    "WIFI_NOT_REACHABLE": Entry("warning", "Can't reach the Wi-Fi network",
                                "calpi couldn't connect to {ssid}.",
                                form="Couldn't connect to {ssid}. Move closer to the router or try again.",
                                toast="Couldn't connect to {ssid}"),
    "WIFI_UNSUPPORTED": Entry("warning", "Wi-Fi security not supported",
                              "This network uses a newer security type that this device may not support.",
                              form="This network uses WPA3, which this device may not support.",
                              toast="This network may not be supported"),
    "WIFI_FAILED": Entry("warning", "Couldn't connect to Wi-Fi", "calpi couldn't connect to {ssid}.",
                         form="Couldn't connect to {ssid}.", toast="Couldn't connect to {ssid}"),
}

# Provider-specific inline (form) wording. Fixed texts only: never a URL, host or server detail.
_SERVER_DOWN = ("That server isn't responding, or didn't answer like a calendar server. "
                "Check the address and try again.")
_LINK_DOWN = "That link isn't responding. Try again in a few minutes."
PROVIDER_FORM: dict[str, dict[str, str]] = {
    "icloud": {
        "AUTH_FAILED": "Apple didn't accept this Apple ID and app-specific password. Check both. "
                       "App-specific passwords look like abcd-efgh-ijkl-mnop.",
    },
    "caldav": {
        "AUTH_FAILED": "The server didn't accept this username and password. Many servers need an app password.",
        "TIMEOUT": _SERVER_DOWN, "SERVER_ERROR": _SERVER_DOWN, "NOT_FOUND": _SERVER_DOWN,
        "PARSE_ERROR": _SERVER_DOWN, "RATE_LIMITED": _SERVER_DOWN,
    },
    "ics": {
        "AUTH_FAILED": "That link isn't accepted. Copy the secret address again.",
        "NOT_FOUND": "Nothing was found at that link. Copy the secret address again.",
        "PARSE_ERROR": "That link didn't return a calendar. Use the secret address in iCal format "
                       "(ending in .ics).",
        "TIMEOUT": _LINK_DOWN, "SERVER_ERROR": _LINK_DOWN, "RATE_LIMITED": _LINK_DOWN,
        "UNKNOWN": "Enter a link starting with https:// or webcal://.",
    },
}

# Other inline messages of the account forms.
FORM_EXTRA = {"no_calendars": "Signed in, but this account has no calendars.",
              "save_failed": "Couldn't save the account."}

# Display priority, most important first (US-31 verdict and the banner slot use this order).
PRIORITY = ["SAFE_MODE", "CREDENTIALS_UNREADABLE", "AUTH_REVOKED", "AUTH_FAILED", "POWER_UNDERVOLTAGE",
            "DISK_FULL", "CLOCK_UNSYNCED", "CLOCK_WRONG", "TLS_ERROR", "NOT_FOUND", "PARSE_ERROR",
            "UNKNOWN", "SERVER_ERROR", "RATE_LIMITED", "TIMEOUT", "DNS_FAILED", "NETWORK_DOWN", "OFFLINE",
            "TEMP_HIGH", "DISK_LOW", "POWER_THROTTLED_PAST", "DB_RESET", "NO_ACCOUNTS"]


def priority_rank(code: str) -> int:
    return PRIORITY.index(code) if code in PRIORITY else len(PRIORITY)


class _Fmt(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _fill(text: str | None, vars: dict) -> str | None:
    return text.format_map(_Fmt(vars)) if text else text


def entry_for(code) -> Entry:
    code = str(getattr(code, "value", code))
    return CATALOGUE.get(code) or CATALOGUE["UNKNOWN"]


def describe(code, *, context: str = "status", provider: str = "iCloud", account: str = "",
             ssid: str = "", last_update: str = "its last update", provider_key: str | None = None) -> Message:
    """The user-facing text of a problem code for one context. Unknown codes read as UNKNOWN.

    `provider` is the display name used in the text; `provider_key` ('icloud'|'caldav'|'ics') selects
    provider-specific form wording (defaults to 'icloud' when the display name is iCloud)."""
    if context not in CONTEXTS:
        raise ValueError(f"unknown context {context!r}")
    code = str(getattr(code, "value", code) or "UNKNOWN")
    e = entry_for(code)
    v = {"provider": provider, "account": account or "this account", "ssid": ssid or "the network",
         "last_update": last_update}
    fix = dict(fix_label=e.fix_label, fix_target=e.fix_target, severity=e.severity)
    if context == "header":
        return Message(_fill(e.header or e.banner_title, v), None, **fix)
    if context == "banner":
        return Message(_fill(e.banner_title, v), _fill(e.banner_detail or e.detail, v), **fix)
    if context == "form":
        key = provider_key or ("icloud" if provider == "iCloud" else None)
        text = (PROVIDER_FORM.get(key, {}).get(code) if key else None) or e.form or e.banner_title
        return Message(_fill(text, v), None, **fix)
    if context == "toast":
        return Message(_fill(e.toast or e.banner_title, v), None, **fix)
    return Message(_fill(e.banner_title, v), _fill(e.detail, v), **fix)


def form_text(key: str) -> str:
    """Inline text for the non-code form messages ('no_calendars', 'save_failed')."""
    return FORM_EXTRA[key]


def classify_account_problem(status) -> str | None:
    """Account status (US-18 AccountStatus) -> problem code, or None. An authentication failure on an
    account that synced successfully before means the password was revoked or expired."""
    code = getattr(status, "last_error_code", None)
    if not code:
        return None
    if code == "AUTH_FAILED" and getattr(status, "last_success_at", None) is not None:
        return "AUTH_REVOKED"
    return code


def toast_for_result(result: dict, provider_names: dict[str, str] | None = None) -> str:
    """Toast text for a failed manual refresh: the most relevant code of the failing accounts."""
    errs = [(a.get("account_id"), a.get("error")) for a in result.get("accounts", []) if a.get("error")]
    if not errs:
        return describe("UNKNOWN", context="toast").title
    codes = {str(getattr(e, "value", e)) for _i, e in errs}
    if codes <= {"NETWORK_DOWN", "DNS_FAILED"}:
        return describe("NETWORK_DOWN", context="toast").title
    if codes & {"AUTH_FAILED", "CREDENTIALS_UNREADABLE"}:
        return describe("AUTH_FAILED", context="toast").title
    slow = {"SERVER_ERROR", "RATE_LIMITED", "TIMEOUT"}
    if codes & slow:
        names = {(provider_names or {}).get(i) for i, e in errs if e in slow}
        names.discard(None)
        who = next(iter(names)) if len(names) == 1 else "server"
        return describe("SERVER_ERROR", context="toast", provider=who).title
    return describe("UNKNOWN", context="toast").title


def review_markdown() -> str:
    """Every message in every context with sample values (for the owner's wording review)."""
    out = ["# calpi problem messages", ""]
    for code, e in CATALOGUE.items():
        out += [f"## {code}  ({e.severity}, show after {e.grace_s // 60} min)", "",
                "| Context | Title | Detail |", "|---|---|---|"]
        for ctx in CONTEXTS:
            m = describe(code, context=ctx, account="me@icloud.com", ssid="HomeWiFi",
                         last_update="Today 14:05")
            out.append(f"| {ctx} | {m.title} | {m.detail or ''} |")
        if e.fix_label:
            out += ["", f"Fix button: **{e.fix_label}** -> `{e.fix_target}`"]
        out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m calpi.data.messages")
    ap.add_argument("--review", action="store_true", help="print every message for the wording review")
    a = ap.parse_args(argv)
    if a.review:
        print(review_markdown())
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
