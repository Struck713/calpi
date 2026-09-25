from calpi.data.credentials import CredentialStore
from calpi.data.settings_store import SettingsStore
from calpi.sync import cli, icloud
from calpi.sync.http import HttpClient
from tests.test_icloud import Fake, happy

SECRET = "abcd-efgh-ijkl-mnop"


def run(tmp_path, argv, routes=None, monkeypatch=None):
    s = SettingsStore(tmp_path)
    c = CredentialStore(tmp_path, serial_fn=lambda: ("abc", "t"))
    client = HttpClient(allowed_auth_hosts=icloud.ALLOWED, transport=Fake(routes or happy()))
    return cli.main(argv, settings=s, credentials=c, client=client)


def test_add_list_remove(tmp_path, monkeypatch, capsys, caplog):
    monkeypatch.setenv("PW", SECRET)
    assert run(tmp_path, ["add-account", "--username", "me@icloud.com", "--password-env", "PW"]) == 0
    out = capsys.readouterr().out
    assert "Work" in out and "#1badf8" in out and "Reminders" not in out and SECRET not in out
    assert run(tmp_path, ["list-accounts"]) == 0
    out = capsys.readouterr().out
    assert "me@icloud.com" in out and SECRET not in out
    acc_id = out.split()[0]
    assert run(tmp_path, ["remove-account", "--id", acc_id]) == 0
    assert SECRET not in caplog.text


def test_auth_failure_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PW", SECRET)
    routes = {("PROPFIND", "https://caldav.icloud.com/"): (401, {}, b"")}
    assert run(tmp_path, ["discover", "--username", "u", "--password-env", "PW"], routes) == 2
    cap = capsys.readouterr()
    assert "AUTH_FAILED" in cap.err and SECRET not in cap.out + cap.err
