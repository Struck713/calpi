"""Guide texts (no gi). Update here when Apple renames its menus."""
from __future__ import annotations

# The wording follows Apple's "Sign in to apps with your Apple Account using
# app-specific passwords" article. `checked` is the date it was last compared.
GUIDE_SOURCE = {
    "url": "https://support.apple.com/en-us/102654",
    "page": "https://account.apple.com",
    "checked": "2026-09-25",
    "verified_against_live_article": False,
}

GUIDE_URL = "https://account.apple.com"
GUIDE_URL_LABEL = "account.apple.com"
QR_ASSET = "qr-account-apple-com.png"
QR_CAPTION = "Scan to open account.apple.com"

# (heading, paragraphs). A section whose heading is STEPS_HEADING is a numbered list.
STEPS_HEADING = "Create the password"

ICLOUD_APP_PASSWORD_GUIDE: list[tuple[str, list[str]]] = [
    ("Why an app-specific password?", [
        "calpi uses an app-specific password so it never sees your real Apple ID password. "
        "You can revoke it at any time.",
    ]),
    ("Before you start", [
        "Your Apple ID needs two-factor authentication turned on.",
    ]),
    (STEPS_HEADING, [
        "On your phone or computer, open account.apple.com (scan the QR code).",
        "Sign in with your Apple ID.",
        "Choose Sign-In and Security.",
        "Choose App-Specific Passwords.",
        "Generate an app-specific password and name it \"calpi\".",
        "The password appears once, as four groups of four letters. "
        "Type it into calpi (you can leave out the hyphens).",
    ]),
    ("Later", [
        "To disconnect calpi, revoke the password on the same page, "
        "or remove the account in Settings → Accounts.",
    ]),
]


def steps() -> list[str]:
    return next(p for h, p in ICLOUD_APP_PASSWORD_GUIDE if h == STEPS_HEADING)
