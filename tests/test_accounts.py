import pytest

from calpi.data import accounts
from calpi.data.credentials import CredentialStore, Secret
from calpi.data.settings_store import SettingsStore
from calpi.sync.icloud import Discovery


@pytest.fixture
def env(tmp_path):
    return SettingsStore(tmp_path), CredentialStore(tmp_path, serial_fn=lambda: ("abc", "test"))


def disc(home="https://p1.icloud.com/1/calendars/", name="Me"):
    return Discovery("https://caldav.icloud.com/1/principal/", home, name, [])


def test_add_then_update_case_insensitive(env):
    s, c = env
    a = accounts.add_or_update_account(s, c, "icloud", "Me@iCloud.com", Secret("pass-one-xx"), disc())
    b = accounts.add_or_update_account(s, c, "icloud", "me@icloud.com", Secret("pass-two-xx"),
                                       disc("https://p2.icloud.com/1/calendars/"))
    assert b.id == a.id and a.id.startswith("icloud-")
    assert len(accounts.list_accounts(s)) == 1
    assert c.get(a.id).reveal() == "pass-two-xx"
    assert accounts.get_account(s, a.id).calendar_home_url.startswith("https://p2.")
    assert b.created_at == a.created_at
    assert "pass-two-xx" not in s.path.read_text()


def test_settings_failure_removes_secret(env):
    s, c = env
    def boom(*a, **k):
        raise OSError("disk")
    s.set = boom
    with pytest.raises(OSError):
        accounts.add_or_update_account(s, c, "icloud", "a@b.c", Secret("pass-one-xx"), disc())
    assert c.ids() == []


def test_settings_failure_restores_old_secret(env):
    s, c = env
    a = accounts.add_or_update_account(s, c, "icloud", "a@b.c", Secret("pass-one-xx"), disc())
    s.set = lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
    with pytest.raises(OSError):
        accounts.add_or_update_account(s, c, "icloud", "a@b.c", Secret("pass-two-xx"), disc())
    assert c.get(a.id).reveal() == "pass-one-xx"


def test_remove(env):
    s, c = env
    a = accounts.add_or_update_account(s, c, "icloud", "a@b.c", Secret("pass-one-xx"), disc())
    assert accounts.remove_account(s, c, a.id)
    assert accounts.list_accounts(s) == [] and c.ids() == []
    assert not accounts.remove_account(s, c, a.id)


def test_invalid_accounts_rejected(env):
    s, _ = env
    with pytest.raises(ValueError):
        s.set("accounts", [{"id": "x"}])


# ---- US-25 helpers ----
from calpi.data.event_store import EventStore
from calpi.data.models import Calendar, RemoteCalendar


def test_normalize_app_password():
    n = accounts.normalize_app_password
    assert n("ABCD EFGH IJKL MNOP") == "abcd-efgh-ijkl-mnop"
    assert n("abcdefghijklmnop") == "abcd-efgh-ijkl-mnop"
    assert n("Abcd-efghijkl-mnop") == "abcd-efgh-ijkl-mnop"
    assert n("Ab3$random-Password-20") == "Ab3$random-Password-20"


def test_normalize_and_validate_apple_id():
    assert accounts.normalize_apple_id("  Me@ICloud.COM ") == "Me@icloud.com"
    assert accounts.validate_apple_id("me@icloud.com") is None
    assert accounts.validate_apple_id("me@icloud") is not None
    assert accounts.validate_apple_id("me icloud.com") is not None


def test_validate_app_password():
    assert accounts.validate_app_password("abcd-efgh-ijkl-mnop") == (None, False)
    err, warn = accounts.validate_app_password("longerpassword1")
    assert err and warn
    err, warn = accounts.validate_app_password("short")
    assert err and not warn


def _store(tmp_path):
    return EventStore(tmp_path / "e.sqlite3")


def _remotes():
    return [RemoteCalendar("/a/", "A", "#ff0000"), RemoteCalendar("/b/", "B", None)]


def test_apply_selection_and_keep_flags(tmp_path):
    st = _store(tmp_path)
    accounts.apply_calendar_selection(st, "icloud-1", _remotes(), {"/a/"})
    cals = {c.remote_href: c for c in st.list_calendars()}
    assert not cals["/a/"].hidden and cals["/b/"].hidden
    # update: existing flags kept, new calendar visible
    st.set_calendar_overrides(cals["/a/"].id, user_name="Mine")
    accounts.apply_calendar_selection(st, "icloud-1", _remotes() + [RemoteCalendar("/c/", "C")], None)
    cals = {c.remote_href: c for c in st.list_calendars()}
    assert cals["/b/"].hidden and not cals["/c/"].hidden and cals["/a/"].user_name == "Mine"


def test_reconcile(tmp_path):
    s, c = SettingsStore(tmp_path), CredentialStore(tmp_path, serial_fn=lambda: ("abc", "test"))
    st = _store(tmp_path)
    a = accounts.add_or_update_account(s, c, "icloud", "a@b.c", Secret("pass-one-xx"), disc())
    accounts.apply_calendar_selection(st, a.id, _remotes(), None)
    accounts.apply_calendar_selection(st, "icloud-gone", _remotes(), None)
    st.upsert_calendar(Calendar(id="sample:1", remote_name="S"))
    st.upsert_calendar(Calendar(id="local", remote_name="L"))
    assert accounts.reconcile_calendars(s, st) == 2
    ids = {c.id for c in st.list_calendars()}
    assert "sample:1" in ids and "local" in ids and len(ids) == 4


def test_remove_account_continues_after_failure(tmp_path):
    s, c = SettingsStore(tmp_path), CredentialStore(tmp_path, serial_fn=lambda: ("abc", "test"))
    st = _store(tmp_path)
    a = accounts.add_or_update_account(s, c, "icloud", "a@b.c", Secret("pass-one-xx"), disc())
    accounts.apply_calendar_selection(st, a.id, _remotes(), None)
    def boom(_id):
        raise OSError("x")
    c.delete = boom
    called = []
    assert accounts.remove_account(s, c, a.id, store=st, forget_status=lambda: called.append(1))
    assert accounts.list_accounts(s) == [] and st.list_calendars() == [] and called
