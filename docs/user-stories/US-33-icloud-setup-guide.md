# US-33 — iCloud setup guide

| | |
|---|---|
| **Epic** | 3. Setup and Settings |
| **Priority** | P1 |
| **Blocked by** | US-25 Account management |
| **Blocks** | — |
| **Phase** | 3. Setup and Settings (P1) |

## Story

> As a user, I want a short guide explaining how to create an app-specific password for the device.

## Context

Most people have never made an **app-specific password**. Without help, they type their normal Apple ID password into the sign-in form, which fails with "Apple didn't accept this Apple ID and app-specific password", and they get stuck. This story adds a short, friendly, **on-device guide** that US-25's sign-in form links to ("How do I get an app-specific password?"). It's also reachable from Settings → Accounts.

The guide explains:
1. why an app-specific password is used (the device never sees the real password, and the owner can revoke it at any time),
2. the requirement: **two-factor authentication** on the Apple ID,
3. the steps, on a phone or computer: sign in at **account.apple.com** → **Sign-In and Security** → **App-Specific Passwords** → **Generate** → name it "calpi" → the password is shown once, in the format `xxxx-xxxx-xxxx-xxxx`,
4. how to type it on the device, and that the hyphens can be left out (US-25 D4 normalises them),
5. how to revoke it later.

It includes a **QR code** for `https://account.apple.com`, so the owner can open the page on their phone straight away without typing the URL. The QR code is **pre-rendered as a PNG** at build time (it's a fixed URL, so there's no runtime QR library).

**Accuracy matters**: Apple renames menus now and then. **Check the current wording and URL against Apple's support article** before shipping, and record the date.

---

## Blockers

### Hard blockers

| Blocker | What it gives you | How to confirm it's done |
|---|---|---|
| **US-25** Account management | `SignInFlow` with the guide-link hook (it shows the link when the `icloud_guide` screen is registered), the Accounts section | `grep -n "icloud_guide" calpi/widgets/settings/accounts.py` finds the hook. Settings → Accounts → Add account shows the form on the Pi. |

### Soft dependencies
- **US-22** `SectionContext.push_page`: the guide opens as a sub-page inside Settings **or** the wizard (so the user returns to the half-filled form). Use `ctx.push_page`, not a separate navigator screen, **unless** the hook in US-25 was written for a navigator screen. Adapt the hook to `push_page` if needed (D1).
- **US-32**: the guide must work in wizard mode too (it follows from `push_page`).

### External blockers

| Blocker | What to do |
|---|---|
| **The current Apple instructions** | Check Apple's support article "Sign in to apps with your Apple Account using app-specific passwords" (search support.apple.com; the article id at the time of writing is believed to be 102654) and the `account.apple.com` page. **Use WebFetch/WebSearch, or ask the owner to look at their account page.** Record the date and the source URL in `docs/providers.md` (or `docs/icloud-guide.md`). |
| **A QR code generator in the devcontainer** | `sudo apt-get install -y qrencode` (the CLI) **or** `python3-qrcode`. **Devcontainer only.** The PNG is committed as an asset, and nothing is generated on the Pi. |

### Things that may block you mid-work

| Problem | What to do |
|---|---|
| The QR code is too small, or blurry | Render it at the exact display size (about 360 × 360 px), with an integer module size (`qrencode -s 10 -m 2`). Display it with `Gtk.Picture` at its natural size, `can_shrink=False` (the skill's image rule). |
| The guide text doesn't fit on one screen | Split it into 2 short pages ("Before you start" / "Create the password") with Next and Back, or make it scrollable. **Keep it short**: at most 6 numbered steps. |

---

## Scope

### In scope
- `calpi/widgets/icloud_guide.py`: `IcloudGuidePage(ctx)` (one scrollable page, or 2 pages).
- `calpi/assets/qr-account-apple-com.png` (pre-rendered) + `scripts/make-assets.sh` to regenerate it.
- The links: from `SignInFlow`'s form ("How do I get an app-specific password?") and from the Accounts section ("Help with iCloud sign-in").
- A source/date note in the docs.

### Out of scope
- Guides for other providers (US-20 adds its own, in the same pattern).
- Videos or animations (no animations on the Pi).

---

## Acceptance criteria

1. The link "How do I get an app-specific password?" (≥ 72 px tall) on US-25's sign-in form opens the guide **as a sub-page**. Back returns to the form, **with the typed Apple ID kept**.
2. Content, in plain language, with a large readable font (≥ 26 px body):
   - **Why**: "calpi uses an app-specific password so it never sees your real Apple ID password. You can revoke it at any time."
   - **Before you start**: "Your Apple ID needs two-factor authentication turned on."
   - **Steps** (numbered, at most 6): open account.apple.com on your phone or computer (scan the QR code) → sign in → Sign-In and Security → App-Specific Passwords → Generate an app-specific password, name it "calpi" → the password appears (four groups of four letters). Type it into calpi (you can leave out the hyphens).
   - **Later**: "To disconnect calpi, revoke the password on the same page, or remove the account in Settings → Accounts."
3. The QR code (≥ 320 px, crisp at its natural pixel size) encodes exactly `https://account.apple.com`, and there's a caption "Scan to open account.apple.com".
4. The wording has been checked against Apple's current instructions, and the date and source are recorded in the docs.
5. It works in Settings **and** the wizard (US-32) with the same component.
6. Also reachable from Settings → Accounts ("Help with iCloud sign-in").
7. The page loads in under 150 ms on the Pi (the PNG is small, and loaded once).
8. No network access is needed to show the guide.

---

## Design decisions (already made)

- **D1. A sub-page, not a screen**: `ctx.push_page(IcloudGuidePage(ctx).widget, "App-specific passwords")`. If US-25 checks `navigator.get("icloud_guide")` to decide whether to show the link, change it to check a module-level flag, `icloud_guide.AVAILABLE = True` (set when the module is imported), and call `open_guide(ctx)`.
- **D2. The QR code** is a committed PNG generated by `scripts/make-assets.sh` (`qrencode -o calpi/assets/qr-account-apple-com.png -s 10 -m 2 -l M 'https://account.apple.com'`). Size it about 330–370 px. The asset is loaded with `Gdk.Texture.new_from_filename` (GTK ≥ 4.6) or `GdkPixbuf.Pixbuf.new_from_file` → `Gdk.Texture.new_for_pixbuf`, and cached.
- **D3. The text lives in one place** (`calpi/data/guides.py`, a plain list of `(heading, paragraphs)`), so it's easy to update when Apple changes the wording, and it can be checked in a test (length limits, no leftover placeholders).

---

## Implementation plan

1. **Research** the current Apple wording (external blockers). Write it down with the date.
2. **The asset**: install `qrencode` in the devcontainer, write `scripts/make-assets.sh`, generate the PNG, and check it by decoding it (`zbarimg` from `zbar-tools`, if available, or by scanning it with a phone: ask the owner).
3. **`calpi/data/guides.py`**: `ICLOUD_APP_PASSWORD_GUIDE = [...]` sections, plus `GUIDE_SOURCE = {"url": "...", "checked": "2026-09-25"}`.
4. **`calpi/widgets/icloud_guide.py`**:
   ```python
   AVAILABLE = True
   def open_guide(ctx): ctx.push_page(IcloudGuidePage(ctx).widget, "App-specific passwords")
   class IcloudGuidePage:
       def __init__(self, ctx):
           # Gtk.ScrolledWindow → Box: two columns at 1920 wide — left: text sections (wrap, max width ~900px); right: QR Picture + caption
   ```
   Numbered steps: labels with a large number bubble (`.guide-step-number`). Body 26 px, headings 34 px.
5. **Links**: in `SignInFlow`'s form, `ButtonRow`-style link → `icloud_guide.open_guide(self.ctx)` (only if `AVAILABLE`). In the Accounts section, a "Help with iCloud sign-in" row.
6. **Tests**: guide data sanity (at most 6 steps, no empty strings, contains "account.apple.com"), the asset exists and is a PNG of the expected size (read the PNG header with `struct`, no gi needed), `open_guide` calls `push_page` (a fake ctx).
7. **Pi check**: take a screenshot of the guide from the sign-in form. Ask the owner to scan the QR code from the physical screen with their phone: it must open account.apple.com. Back to the form, with the Apple ID still there.

---

## Files

| File | Change |
|---|---|
| `calpi/data/guides.py` | New |
| `calpi/widgets/icloud_guide.py` | New |
| `calpi/assets/qr-account-apple-com.png` | New (generated) |
| `scripts/make-assets.sh` | New |
| `calpi/widgets/settings/accounts.py` | The links (D1 hook) |
| `calpi/style.css` | Guide styles |
| `docs/providers.md` or `docs/icloud-guide.md` | The source and date |
| `tests/test_guides.py` | New |

---

## Pitfalls

- **Out-of-date Apple menu names.** Check them, and record the date.
- **Scaling the QR code in GTK** (it goes blurry and may not scan). Use the natural size.
- **Opening the guide as a navigator screen**: Back would leave the half-filled form.
- **Generating the QR code on the Pi.** It's committed.

---

## Definition of done

- [ ] All acceptance criteria met. Tests pass.
- [ ] The QR code scanned with a real phone from the Pi's screen.
- [ ] Apple wording checked and recorded with the date.

---

## Contracts for later stories

| Contract | Used by |
|---|---|
| The guide pattern (`guides.py` data + a page using `push_page` + a pre-rendered QR asset) | US-20 (Google ICS link guide, CalDAV app-password guide) |
| `scripts/make-assets.sh` | any story adding pre-rendered assets (US-41 weather icons) |
