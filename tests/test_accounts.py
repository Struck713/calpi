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
