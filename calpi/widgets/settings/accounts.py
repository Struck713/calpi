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
PROVIDER_NAMES = {"icloud": "iCloud"}


def signin_message(e: BaseException) -> str:
    if isinstance(e, SyncError):
        return SIGNIN_MESSAGES.get(e.code) or f"Couldn't sign in ({e.code.value})."
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

    def __init__(self, ctx, *, on_finished: Callable[[Account], None], existing: Account | None = None):
        self.ctx, self.on_finished, self.existing = ctx, on_finished, existing
        self._cancelled = False
        self._keep_entries = False
        self._pages = 0
        self.user_entry = self.pw_entry = self.error_label = self.signin_btn = None

    # ---- pages ----
    def start(self) -> None:
        # D1: only iCloud is registered, so the provider chooser is skipped.
        self._push(self._form(), "Update password" if self.existing else "Add iCloud account")

    def _push(self, widget, title) -> None:
        self._pages += 1
        self.ctx.push_page(widget, title)

    def _pop_all(self) -> None:
        while self._pages > 0:
            self._pages -= 1
            self.ctx.pop_page()

    def _form(self) -> Gtk.Widget:
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
        self._show_error(signin_message(e), network=code in NETWORK_CODES)
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
        if self.existing:
            self._save(user, secret, disc, None)
            return
        self._push(self._selection_page(user, secret, disc), "Choose calendars")

    def _save(self, user, secret, disc, selected) -> None:
        app = self.ctx.app
        try:
            first = not accounts.list_accounts(app.settings)
            acc = accounts.add_or_update_account(app.settings, app.credentials, "icloud", user,
                                                 secret, disc)
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
        app.toast("Password updated" if self.existing else "iCloud account added")
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
        for e in (self.user_entry, self.pw_entry):
            if e is not None and (e is self.pw_entry or not self.existing):
                e.set_text("")


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
        SignInFlow(self.ctx, on_finished=lambda acc: self._refresh()).start()

    def _open_detail(self, acc: Account) -> None:
        app = self.ctx.app
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        g = SettingsGroup(acc.display_name)
        cals = app.store.calendars_for_account(acc.id)
        hidden = sum(1 for c in cals if c.hidden)
        g.add(InfoRow("Provider", PROVIDER_NAMES.get(acc.provider, acc.provider)))
        g.add(InfoRow("Apple ID", acc.username))
        g.add(InfoRow("Name", acc.display_name))
        g.add(InfoRow("Calendars", f"{len(cals)}" + (f" ({hidden} hidden)" if hidden else "")))
        g.add(InfoRow("Status", status_text(app, acc)))
        page.append(g)
        g2 = SettingsGroup()
        g2.add(ButtonRow("Calendars", "Customize", lambda: self._open_calendars(),
                         description="Show, hide, rename and recolor this account's calendars."))
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
            "Its calendars and events will be removed from calpi. Your iCloud data isn't affected.",
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
