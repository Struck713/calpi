"""Accounts section (US-25): list, add (sign-in flow), update password, remove.

SignInFlow(ctx, on_finished, existing=None) is reusable by the setup wizard (ctx.mode == "wizard").
All settings/credentials/store writes happen on the main thread; only discovery runs in a thread.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from gi.repository import GLib, Gtk

from calpi.data import accounts
from calpi.data.credentials import Secret
from calpi.data.models import Account
from calpi.sync import icloud
from calpi.sync.errors import ErrorCode, SyncError
from calpi.tasks import run_in_thread
from calpi.widgets import icloud_guide
from calpi.widgets.keyboard import make_password_field
from calpi.widgets.settings.registry import SectionSpec, register_section
from calpi.widgets.settings.rows import ButtonRow, InfoRow, ListPickerRow, SettingsGroup, SwitchRow
from calpi.widgets.util import set_text_if_changed

log = logging.getLogger("calpi.settings.accounts")

# US-38 will move these into the shared catalogue.
SIGNIN_MESSAGES = {
    ErrorCode.AUTH_FAILED: "Apple didn't accept this Apple ID and app-specific password. Check both. "
                           "App-specific passwords look like abcd-efgh-ijkl-mnop.",
    ErrorCode.NETWORK_DOWN: "calpi isn't connected to the internet. Check Wi-Fi in Settings → Network.",
    ErrorCode.DNS_FAILED: "calpi isn't connected to the internet. Check Wi-Fi in Settings → Network.",
    ErrorCode.TIMEOUT: "iCloud isn't responding right now. Try again in a few minutes.",
    ErrorCode.SERVER_ERROR: "iCloud isn't responding right now. Try again in a few minutes.",
    ErrorCode.RATE_LIMITED: "iCloud isn't responding right now. Try again in a few minutes.",
    ErrorCode.CLOCK_WRONG: "calpi's clock or security settings are wrong, so it can't connect securely. "
                           "Make sure it's online so the clock can set itself, then try again.",
    ErrorCode.TLS_ERROR: "calpi's clock or security settings are wrong, so it can't connect securely. "
                         "Make sure it's online so the clock can set itself, then try again.",
    "no_calendars": "Signed in, but this account has no calendars.",
    "save_failed": "Couldn't save the account.",
}
NETWORK_CODES = (ErrorCode.NETWORK_DOWN, ErrorCode.DNS_FAILED)
PROVIDER_NAMES = {"icloud": "iCloud", "caldav": "CalDAV", "ics": "Subscription"}

# US-20: provider-specific overrides. Fixed texts only: never a URL, host or server detail.
_SERVER_DOWN = "That server isn't responding, or didn't answer like a calendar server. " \
               "Check the address and try again."
PROVIDER_MESSAGES = {
    "caldav": {
        ErrorCode.AUTH_FAILED: "The server didn't accept this username and password. "
                               "Many servers need an app password.",
        ErrorCode.TIMEOUT: _SERVER_DOWN, ErrorCode.SERVER_ERROR: _SERVER_DOWN,
        ErrorCode.NOT_FOUND: _SERVER_DOWN, ErrorCode.PARSE_ERROR: _SERVER_DOWN,
        ErrorCode.RATE_LIMITED: _SERVER_DOWN,
    },
    "ics": {
        ErrorCode.AUTH_FAILED: "That link isn't accepted. Copy the secret address again.",
        ErrorCode.NOT_FOUND: "Nothing was found at that link. Copy the secret address again.",
        ErrorCode.PARSE_ERROR: "That link didn't return a calendar. Use the secret address "
                               "in iCal format (ending in .ics).",
        ErrorCode.TIMEOUT: "That link isn't responding. Try again in a few minutes.",
        ErrorCode.SERVER_ERROR: "That link isn't responding. Try again in a few minutes.",
        ErrorCode.RATE_LIMITED: "That link isn't responding. Try again in a few minutes.",
        ErrorCode.UNKNOWN: "Enter a link starting with https:// or webcal://.",
    },
}
ICS_NOTE = ("Google updates these links only every few hours, so new events can take a while "
            "to appear. The link is a secret: anyone with it can read the calendar. calpi keeps "
            "it in its credential store and never shows it again.")
ICS_COLORS = ("#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6")


def signin_message(e: BaseException, provider: str = "icloud") -> str:
    if isinstance(e, SyncError):
        return (PROVIDER_MESSAGES.get(provider, {}).get(e.code) or SIGNIN_MESSAGES.get(e.code)
                or f"Couldn't sign in ({e.code.value}).")
    return "Couldn't sign in (UNKNOWN)."


def _notify_changed(app) -> None:
    fn = getattr(app, "on_data_changed", None) or getattr(app.window, "on_data_changed", None)
    if fn:
        fn()
        return
    mv = getattr(getattr(app, "window", None), "month_view", None)
    if mv is not None and hasattr(mv, "reload"):
        mv.reload(force=True)


def _request_sync(app, reason: str) -> None:
    sync = getattr(app, "sync", None)
    if sync is not None:
        sync.request_sync(reason)
    else:
        log.info("no sync engine yet; not requesting sync (%s)", reason)


class SignInFlow:
    """Provider form -> discovery -> calendar selection -> save. `existing` = update password."""

    def __init__(self, ctx, *, on_finished: Callable[[Account], None], existing: Account | None = None,
                 provider: str = "icloud", choose: bool = False):
        self.ctx, self.on_finished, self.existing = ctx, on_finished, existing
        self.provider = existing.provider if existing else provider
        self.choose = choose and existing is None        # US-20: show the provider chooser first
        self._server_url = ""
        self._options: dict = {}
        self.server_entry = self.principal_entry = self.color = None
        self._cancelled = False
        self._keep_entries = False
        self._pages = 0
        self.user_entry = self.pw_entry = self.error_label = self.signin_btn = None

    # ---- pages ----
    def start(self) -> None:
        if self.choose:
            self._push(self._chooser(), "Add account")
            return
        self._push_form()

    def _push_form(self) -> None:
        if self.existing:
            title = "Update password"
        else:
            title = {"icloud": "Add iCloud account", "caldav": "Add CalDAV account",
                     "ics": "Add subscription"}.get(self.provider, "Add account")
        self._push(self._form(), title)

    def _chooser(self) -> Gtk.Widget:
        """iCloud first (the default path), then the other providers from the registry."""
        from calpi.sync import providers
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        group = SettingsGroup("Where is your calendar?")
        descs = {"icloud": "Sign in with your Apple ID and an app-specific password.",
                 "caldav": "Fastmail, Nextcloud, mailbox.org, Synology and other CalDAV servers.",
                 "ics": "A read-only link, such as Google's secret address in iCal format."}
        names = providers.all()
        names.sort(key=lambda t: t[0] != "icloud")
        self.chooser_rows = {}
        for name, label in names:
            row = ListPickerRow(PROVIDER_NAMES.get(name, label) if name == "icloud" else label, "",
                                lambda n=name: self._chosen(n), description=descs.get(name))
            self.chooser_rows[name] = row
            group.add(row)
        page.append(group)
        return page

    def _chosen(self, name: str) -> None:
        self.provider = name
        self._push_form()

    def _push(self, widget, title) -> None:
        self._pages += 1
        self.ctx.push_page(widget, title)

    def _pop_all(self) -> None:
        while self._pages > 0:
            self._pages -= 1
            self.ctx.pop_page()

    def _form(self) -> Gtk.Widget:
        if self.provider == "caldav":
            return self._form_caldav()
        if self.provider == "ics":
            return self._form_ics()
        return self._form_icloud()

    def _common_tail(self, page, kb_done_label: str, button_label: str) -> None:
        self.error_label = Gtk.Label(xalign=0, wrap=True, css_classes=["signin-error"])
        self.error_label.set_visible(False)
        page.append(self.error_label)
        self.network_btn = Gtk.Button(label="Network settings", halign=Gtk.Align.START,
                                      css_classes=["row-button"])
        self.network_btn.set_visible(False)
        self.network_btn.connect("clicked", lambda *_: self._open_network())
        page.append(self.network_btn)
        self.signin_btn = Gtk.Button(label=button_label, css_classes=["wide-button"])
        self.signin_btn.connect("clicked", lambda *_: self._submit())
        page.append(self.signin_btn)
        page.connect("unmap", lambda *_: None if self._keep_entries else self._clear_entries())
        page.connect("map", lambda *_: setattr(self, "_keep_entries", False))

    def _form_caldav(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=["signin-form"])
        page.append(Gtk.Label(label="Enter your server address and an app password if the server "
                                    "offers them.", xalign=0, wrap=True, css_classes=["row-desc"]))
        kb = getattr(self.ctx.window, "keyboard", None)
        self.server_entry = Gtk.Entry(placeholder_text="Server (https://cloud.example.com)",
                                      hexpand=True, input_purpose=Gtk.InputPurpose.URL,
                                      css_classes=["osk-entry"])
        self.user_entry = Gtk.Entry(placeholder_text="Username", hexpand=True,
                                    css_classes=["osk-entry"])
        pw_box, self.pw_entry, _t = make_password_field()
        self.pw_entry.set_placeholder_text("Password")
        self.principal_entry = Gtk.Entry(placeholder_text="Advanced: calendar address (optional)",
                                         hexpand=True, input_purpose=Gtk.InputPurpose.URL,
                                         css_classes=["osk-entry"])
        if self.existing:
            self.server_entry.set_text(self.existing.server_url)
            self.user_entry.set_text(self.existing.username)
            for e in (self.server_entry, self.user_entry):
                e.set_editable(False)
                e.set_can_focus(False)
            self.principal_entry.set_visible(False)
        for w in (self.server_entry, self.user_entry, pw_box, self.principal_entry):
            page.append(w)
        if kb is not None:
            if not self.existing:
                kb.attach(self.server_entry, "url", "Next", lambda: self.user_entry.grab_focus())
                kb.attach(self.user_entry, "text", "Next", lambda: self.pw_entry.grab_focus())
                kb.attach(self.principal_entry, "url", "Test & continue", self._submit)
            kb.attach(self.pw_entry, "password",
                      "Test & continue" if self.existing else "Next",
                      self._submit if self.existing else lambda: (
                          self.principal_entry.grab_focus()))
        self.pw_entry.connect("activate", lambda *_: self._submit())
        self._common_tail(page, "Test & continue", "Test & continue")
        return page

    def _form_ics(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=["signin-form"])
        page.append(Gtk.Label(label=ICS_NOTE, xalign=0, wrap=True, css_classes=["row-desc"]))
        kb = getattr(self.ctx.window, "keyboard", None)
        self.user_entry = Gtk.Entry(placeholder_text="Name (optional)", hexpand=True,
                                    css_classes=["osk-entry"])
        pw_box, self.pw_entry, _t = make_password_field()
        self.pw_entry.set_placeholder_text("Calendar link (https:// or webcal://)")
        self.pw_entry.add_css_class("mono-entry")
        page.append(self.user_entry)
        page.append(pw_box)
        page.append(self._color_row())
        if kb is not None:
            kb.attach(self.user_entry, "text", "Next", lambda: self.pw_entry.grab_focus())
            kb.attach(self.pw_entry, "url", "Test & continue", self._submit)
        self.pw_entry.connect("activate", lambda *_: self._submit())
        self._common_tail(page, "Test & continue", "Test & continue")
        return page

    def _color_row(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.color = {"value": None, "buttons": {}}
        first = None
        for c in ICS_COLORS:
            b = Gtk.ToggleButton(focus_on_click=False, css_classes=["color-swatch"])
            b.set_child(Gtk.Label(use_markup=True, label=f'<span foreground="{c}" size="xx-large">●</span>'))
            b.set_size_request(72, 72)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", lambda btn, col=c: btn.get_active() and self.color.update(value=col))
            self.color["buttons"][c] = b
            box.append(b)
        return box

    def _form_icloud(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20,
                       css_classes=["signin-form"])
        page.append(Gtk.Label(label="Use an app-specific password, not your Apple ID password.",
                              xalign=0, wrap=True, css_classes=["row-desc"]))
        kb = getattr(self.ctx.window, "keyboard", None)
        self.user_entry = Gtk.Entry(placeholder_text="Apple ID (name@icloud.com)", hexpand=True,
                                    input_purpose=Gtk.InputPurpose.EMAIL,
                                    css_classes=["osk-entry"])
        pw_box, self.pw_entry, _toggle = make_password_field()
        self.pw_entry.set_placeholder_text("App-specific password")
        if self.existing:
            self.user_entry.set_text(self.existing.username)
            self.user_entry.set_editable(False)
            self.user_entry.set_can_focus(False)
        page.append(self.user_entry)
        page.append(pw_box)
        if kb is not None:
            if not self.existing:
                kb.attach(self.user_entry, "email", "Next", lambda: self.pw_entry.grab_focus())
            kb.attach(self.pw_entry, "password", "Sign in", self._submit)
        self.pw_entry.connect("activate", lambda *_: self._submit())
        self.error_label = Gtk.Label(xalign=0, wrap=True, css_classes=["signin-error"])
        self.error_label.set_visible(False)
        page.append(self.error_label)
        self.network_btn = Gtk.Button(label="Network settings", halign=Gtk.Align.START,
                                      css_classes=["row-button"])
        self.network_btn.set_visible(False)
        self.network_btn.connect("clicked", lambda *_: self._open_network())
        page.append(self.network_btn)
        self.signin_btn = Gtk.Button(label="Sign in", css_classes=["wide-button"])
        self.signin_btn.connect("clicked", lambda *_: self._submit())
        page.append(self.signin_btn)
        if icloud_guide.AVAILABLE:                       # US-33
            page.append(Gtk.Button(
                label="How do I get an app-specific password?",
                css_classes=["row-button"], halign=Gtk.Align.START, hexpand=False))
            page.get_last_child().connect("clicked", lambda *_: self._open_guide())
        page.connect("unmap", lambda *_: None if self._keep_entries else self._clear_entries())
        page.connect("map", lambda *_: setattr(self, "_keep_entries", False))
        return page

    def _open_guide(self) -> None:
        # Keep the typed Apple ID while the guide covers the form; the form's
        # "map" handler re-arms clearing once Back returns to it.
        self._keep_entries = True
        icloud_guide.open_guide(self.ctx)

    def _selection_page(self, user, secret, disc) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        selected = {c.href for c in disc.calendars}
        group = SettingsGroup("Calendars to show")
        for rc in disc.calendars:
            def get(h=rc.href):
                return h in selected

            def put(v, h=rc.href):
                (selected.add if v else selected.discard)(h)
            row = SwitchRow(rc.name, getter=get, setter=put)
            dot = Gtk.Label(use_markup=True, css_classes=["cal-dot"], label=(
                f'<span foreground="{rc.color or "#9aa4ae"}">●</span>'))
            row.prepend(dot)
            group.add(row)
        page.append(group)
        done = Gtk.Button(label="Done", css_classes=["wide-button"])
        done.connect("clicked", lambda *_: self._save(user, secret, disc, selected))
        page.append(done)
        self.selection_done = done
        return page

    # ---- actions ----
    def _show_error(self, text: str, network: bool = False) -> None:
        if self.error_label is None:
            return
        self.error_label.set_text(text)
        self.error_label.set_visible(True)
        self.network_btn.set_visible(network and self.ctx.mode == "settings")

    def _submit(self) -> None:
        if self.ctx.window.blocking.is_open:
            return
        if self.provider != "icloud":
            self._submit_other()
            return
        user = accounts.normalize_apple_id(self.user_entry.get_text())
        raw_pw = self.pw_entry.get_text()
        pw = accounts.normalize_app_password(raw_pw)
        err, warn_only = accounts.validate_app_password(pw)
        err = accounts.validate_apple_id(user) or (None if warn_only else err)
        if err:
            self._show_error(err)
            return
        self.error_label.set_visible(False)
        self.network_btn.set_visible(False)
        secret = Secret(pw)
        self._cancelled = False
        self._keep_entries = True
        self.ctx.window.blocking.show("Signing in to iCloud…", on_cancel=self._cancel)
        run_in_thread(lambda: icloud.discover(user, secret),
                      on_done=lambda d: self._discovered(user, secret, d),
                      on_error=self._failed, name="signin")

    def _submit_other(self) -> None:
        """CalDAV / ICS: validate locally (fixed messages), then discover in a thread."""
        from calpi.sync import providers
        from calpi.sync.provider_caldav import normalize_server
        from calpi.sync.provider_ics import normalize_feed
        pw = self.pw_entry.get_text()
        try:
            if self.provider == "ics":
                url = normalize_feed(pw)
                name = self.user_entry.get_text().strip()
                fields = {"name": name, "color": self.color["value"] or ""}
                user = name
                self._server_url = ""
                self._options = {"color": self.color["value"]} if self.color["value"] else {}
                secret = Secret(url)
            else:
                user = self.user_entry.get_text().strip()
                if not user or not pw:
                    raise ValueError("Enter your username and password.")
                server = normalize_server(self.server_entry.get_text())
                principal = self.principal_entry.get_text().strip()
                fields = {"server_url": server, "username": user, "principal_url": principal}
                self._server_url = server
                self._options = {"principal_url_override": principal} if principal else {}
                secret = Secret(pw)
        except ValueError as e:
            self._show_error(str(e))
            return
        except SyncError as e:
            self._show_error("Enter a link starting with https:// or webcal://"
                             if self.provider == "ics" else
                             "Enter the server address, starting with https://.")
            return
        self.error_label.set_visible(False)
        self.network_btn.set_visible(False)
        self._cancelled = False
        self._keep_entries = True
        prov = providers.get(self.provider)
        what = "Checking the calendar link…" if self.provider == "ics" else "Signing in…"
        self.ctx.window.blocking.show(what, on_cancel=self._cancel)
        run_in_thread(lambda: prov.discover(fields, secret),
                      on_done=lambda d: self._discovered(user, secret, d),
                      on_error=self._failed, name="signin")

    def _cancel(self) -> None:
        self._cancelled = True
        self._keep_entries = False
        self._clear_entries()

    def _failed(self, e: BaseException) -> None:
        if self._cancelled:
            return
        self.ctx.window.blocking.hide()
        self._keep_entries = False
        code = e.code if isinstance(e, SyncError) else None
        log.info("sign-in failed: %s", code.value if code else type(e).__name__)   # never the secret
        self._show_error(signin_message(e, self.provider), network=code in NETWORK_CODES)
        self.pw_entry.grab_focus()
        self.pw_entry.select_region(0, -1)

    def _discovered(self, user, secret, disc) -> None:
        if self._cancelled:
            return
        self.ctx.window.blocking.hide()
        if not disc.calendars:
            self._keep_entries = False
            self._show_error(SIGNIN_MESSAGES["no_calendars"])
            return
        if self.provider == "ics":                      # one calendar, name/colour already chosen
            self._save(user, secret, disc, None)
            return
        if self.existing:
            self._save(user, secret, disc, None)
            return
        self._push(self._selection_page(user, secret, disc), "Choose calendars")

    def _save(self, user, secret, disc, selected) -> None:
        app = self.ctx.app
        try:
            first = not accounts.list_accounts(app.settings)
            if self.provider == "icloud":
                acc = accounts.add_or_update_account(app.settings, app.credentials, "icloud", user,
                                                     secret, disc)
            else:
                from calpi.sync import providers
                acc = providers.save_account(
                    app.settings, app.credentials, self.provider,
                    user if self.provider == "caldav" else (user or disc.display_name or "Calendar"),
                    secret, disc, self._server_url or disc.calendar_home_url, self._options)
            if self.provider != "ics":                   # the ics sync creates its own calendar row
                accounts.apply_calendar_selection(app.store, acc.id, disc.calendars, selected)
            if first:
                app.store.delete_sample_data()
        except Exception:
            log.exception("saving account failed")
            self._pop_selection()
            self._keep_entries = False
            self._show_error(SIGNIN_MESSAGES["save_failed"])
            return
        finally:
            self._clear_entries()
        self._keep_entries = False
        _notify_changed(app)
        _request_sync(app, "account-added")
        app.toast("Password updated" if self.existing else
                  {"icloud": "iCloud account added", "ics": "Subscription added"}.get(
                      self.provider, "Account added"))
        self._pop_all()
        self.on_finished(acc)

    def _pop_selection(self) -> None:
        if self._pages > 1:
            self._pages -= 1
            self.ctx.pop_page()

    def _open_network(self) -> None:
        self._pop_all()
        self.ctx.window.navigator.show("settings", section="network")

    def _clear_entries(self) -> None:
        for e in (self.user_entry, self.pw_entry, self.server_entry, self.principal_entry):
            if e is not None and (e is self.pw_entry or not self.existing):
                e.set_text("")


def ui_host(url: str) -> str:
    from urllib.parse import urlsplit
    return urlsplit(url or "").hostname or ""


def status_text(app, acc: Account) -> str:
    """Per-account status line (US-18 status when present; otherwise just 'Added')."""
    fn = getattr(app, "account_status_text", None)
    if callable(fn):
        try:
            return fn(acc.id)
        except Exception:
            log.exception("account status failed")
    return "Added"


class AccountsSection:
    def __init__(self, ctx):
        self.ctx = ctx
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.list_group = SettingsGroup("Accounts")
        self.empty_label = Gtk.Label(label="No calendar accounts yet", xalign=0,
                                     css_classes=["row-desc"], margin_start=8)
        self.widget.append(self.empty_label)
        self.widget.append(self.list_group)
        self.add_btn = Gtk.Button(label="Add account", css_classes=["wide-button"])
        self.add_btn.connect("clicked", lambda *_: self.add_account())
        self.widget.append(self.add_btn)
        if icloud_guide.AVAILABLE:                       # US-33
            self.help_btn = Gtk.Button(label="Help with iCloud sign-in",
                                       css_classes=["wide-button"])
            self.help_btn.connect("clicked", lambda *_: icloud_guide.open_guide(self.ctx))
            self.widget.append(self.help_btn)
        self._shown = None
        self._refresh()

    def on_show(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        app = self.ctx.app
        accs = accounts.list_accounts(app.settings)
        key = [(a.id, a.display_name, a.username, status_text(app, a)) for a in accs]
        if key == self._shown:
            return
        self._shown = key
        rows = self.list_group.rows
        child = rows.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            rows.remove(child)
            child = nxt
        for a, (_id, name, user, status) in zip(accs, key):
            title = f"{PROVIDER_NAMES.get(a.provider, a.provider)}: {name if name != user else user}"
            self.list_group.add(ListPickerRow(title, status, lambda a=a: self._open_detail(a)))
        self.list_group.set_visible(bool(accs))
        self.empty_label.set_visible(not accs)

    def add_account(self) -> None:
        SignInFlow(self.ctx, on_finished=lambda acc: self._refresh(), choose=True).start()

    def _open_detail(self, acc: Account) -> None:
        app = self.ctx.app
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        g = SettingsGroup(acc.display_name)
        cals = app.store.calendars_for_account(acc.id)
        hidden = sum(1 for c in cals if c.hidden)
        g.add(InfoRow("Provider", PROVIDER_NAMES.get(acc.provider, acc.provider)))
        if acc.provider == "icloud":
            g.add(InfoRow("Apple ID", acc.username))
        elif acc.provider == "caldav":
            g.add(InfoRow("Server", ui_host(acc.server_url)))
            g.add(InfoRow("Username", acc.username))
        else:
            g.add(InfoRow("Host", ui_host(acc.server_url)))          # the link itself is a secret
        g.add(InfoRow("Name", acc.display_name))
        g.add(InfoRow("Calendars", f"{len(cals)}" + (f" ({hidden} hidden)" if hidden else "")))
        g.add(InfoRow("Status", status_text(app, acc)))
        page.append(g)
        g2 = SettingsGroup()
        g2.add(ButtonRow("Calendars", "Customize", lambda: self._open_calendars(),
                         description="Show, hide, rename and recolor this account's calendars."))
        if acc.provider != "ics":
            g2.add(ButtonRow("Update password", "Update", lambda: self._update(acc),
                             description="Use this if the app-specific password stopped working."))
        g2.add(ButtonRow("Remove account", "Remove", lambda: self._remove(acc), destructive=True))
        page.append(g2)
        self.ctx.push_page(page, acc.display_name)

    def _open_calendars(self) -> None:
        self.ctx.window.navigator.show("settings", section="calendars")    # US-26

    def _update(self, acc: Account) -> None:
        def finished(_a):
            self.ctx.pop_page()                  # the detail page
            self._refresh()
        SignInFlow(self.ctx, on_finished=finished, existing=acc).start()

    def _remove(self, acc: Account) -> None:
        self.ctx.window.confirm.ask(
            f"Remove {acc.username}?",
            "Its calendars and events will be removed from calpi. Your calendar data at the "
            "provider isn't affected.",
            "Remove", lambda: self._do_remove(acc), destructive=True)

    def _do_remove(self, acc: Account) -> None:
        app = self.ctx.app
        forget = None
        try:
            from calpi.data import sync_status
            if hasattr(sync_status, "forget_account"):
                forget = lambda: sync_status.forget_account(app.store.conn, acc.id)   # noqa: E731
        except ImportError:
            pass
        accounts.remove_account(app.settings, app.credentials, acc.id, store=app.store,
                                forget_status=forget)
        _notify_changed(app)
        app.toast("Account removed")
        self.ctx.pop_page()
        self._refresh()
        # A running sync may put the calendars back; the sync result subscriber reconciles (D5).


register_section(SectionSpec("accounts", "Accounts", 20, AccountsSection))
