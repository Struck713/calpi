import json
import sqlite3

import pytest

from calpi import paths
from calpi.data.credentials import CredentialStore, Secret
from calpi.data.event_store import EventStore
from calpi.data.settings_store import K_ACCOUNTS, K_TIMEZONE, SettingsStore
from calpi.sync import icloud, worker
from calpi.sync.http import HttpClient

from test_fetch import ACC, Fake, PW


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DIRECTORY", str(tmp_path / "run"))
    paths.set_state_dir_override(tmp_path)
    yield tmp_path
    paths.set_state_dir_override(None)


def make_deps(tmp, fake=None, creds=True, db_path=None):
    settings = SettingsStore(tmp)
    from dataclasses import asdict
    settings.set(K_ACCOUNTS, [asdict(ACC)])
    settings.set(K_TIMEZONE, "Europe/Berlin")
    cs = CredentialStore(tmp, serial_fn=lambda: ("SER", "test"))
    if creds:
        cs.set(ACC.id, PW)
    fake = fake or Fake()
    return worker.Deps(settings=lambda: settings, store=lambda: EventStore(db_path or tmp / "w.sqlite3"),
                       credentials=lambda: cs,
                       client=lambda acc: HttpClient(allowed_auth_hosts=icloud.ALLOWED, transport=fake))


def test_run_shape_and_second_run_unchanged(env):
    deps = make_deps(env)
    r = worker.run(worker.parse_args(["--reason", "t"]), deps)
    assert r["v"] == 1 and r["status"] == "done" and r["reason"] == "t"
    assert r["changed"] is True and r["revision_after"] != r["revision_before"]
    a = r["accounts"][0]
    assert a["account_id"] == ACC.id and a["error"] is None
    assert {c["name"] for c in a["calendars"]} >= {"Work", "Home"}
    assert all(c["status"] == "ok" for c in a["calendars"])
    assert r["window"][0] < r["window"][1] and r["window"][0].endswith("Z")
    json.dumps(r)
    r2 = worker.run(worker.parse_args([]), deps)
    assert r2["changed"] is False
    st = {c["name"]: c["status"] for c in r2["accounts"][0]["calendars"]}
    assert st["Work"] == "unchanged" and st["Home"] == "unchanged"   # "Unspecified" has no ctag: re-read


def test_missing_credentials_no_network(env):
    fake = Fake()
    r = worker.run(worker.parse_args([]), make_deps(env, fake, creds=False))
    assert r["accounts"][0]["error"] == "CREDENTIALS_UNREADABLE"
    assert fake.calls == []


def test_account_filter(env):
    r = worker.run(worker.parse_args(["--account", "nope"]), make_deps(env))
    assert r["accounts"] == []


def test_extra_range_widens_window(env):
    r = worker.run(worker.parse_args(["--extra-range", "2031-01-01:2031-03-01"]), make_deps(env))
    assert r["window"][1].startswith("2031-02-28") or r["window"][1].startswith("2031-03-01")


def test_main_only_result_line_on_stdout(env, capsys):
    rc = worker.main(["--reason", "t"], deps=make_deps(env))
    out = capsys.readouterr().out
    assert rc == 0
    lines = out.splitlines()
    assert len(lines) == 1 and lines[0].startswith(worker.RESULT_PREFIX)
    assert json.loads(lines[0][len(worker.RESULT_PREFIX):])["status"] == "done"


def test_main_busy_when_lock_held(env, capsys):
    held = worker._acquire_lock()
    try:
        rc = worker.main(["--reason", "t"], deps=make_deps(env))
    finally:
        held.close()
    assert rc == 3
    r = json.loads(capsys.readouterr().out.strip()[len(worker.RESULT_PREFIX):])
    assert r["status"] == "busy"
    assert worker.main([], deps=make_deps(env)) == 0          # lock released again


def test_main_crash_and_database_error(env, capsys):
    deps = make_deps(env)
    deps.settings = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    assert worker.main([], deps=deps) == 1
    r = json.loads(capsys.readouterr().out.strip()[len(worker.RESULT_PREFIX):])
    assert r["status"] == "crashed" and r["detail"] == "RuntimeError"

    deps = make_deps(env)
    deps.store = lambda: (_ for _ in ()).throw(sqlite3.DatabaseError("malformed"))
    assert worker.main([], deps=deps) == 1
    r = json.loads(capsys.readouterr().out.strip()[len(worker.RESULT_PREFIX):])
    assert r["detail"] == "DatabaseError"
