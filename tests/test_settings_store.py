import json
import logging
import os
import subprocess
import sys

import pytest

from calpi.data import settings_store as ss
from calpi.data.settings_store import SettingsStore, Key, K_SETUP_COMPLETED


@pytest.fixture(autouse=True)
def test_keys():
    added = [ss.register(Key("t_int", int, 5, lambda v: 0 <= v <= 10)),
             ss.register(Key("t_dict", dict, {})),
             ss.register(Key("t_a", int, 0)), ss.register(Key("t_b", int, 0)),
             ss.register(Key("t_opt", (str, type(None)), None))]
    yield
    for k in added:
        del ss.REGISTRY[k.name]


def write(d, obj, name="settings.json"):
    (d / name).write_text(obj if isinstance(obj, str) else json.dumps(obj))


def read(d, name="settings.json"):
    return json.loads((d / name).read_text())


def test_defaults_and_roundtrip(tmp_path):
    s = SettingsStore(tmp_path)
    assert s.get(K_SETUP_COMPLETED) is False
    assert s.set(K_SETUP_COMPLETED, True) is True
    assert SettingsStore(tmp_path).get(K_SETUP_COMPLETED) is True
    raw = read(tmp_path)
    assert raw == {"schema_version": 1, "setup_completed": True}   # defaults not stored
    assert (tmp_path / "settings.json").read_text().endswith("}\n")


def test_unknown_key_raises(tmp_path):
    s = SettingsStore(tmp_path)
    with pytest.raises(KeyError):
        s.get("nope")
    with pytest.raises(KeyError):
        s.set("nope", 1)


def test_type_validation(tmp_path):
    s = SettingsStore(tmp_path)
    with pytest.raises(ValueError):
        s.set(K_SETUP_COMPLETED, 1)
    with pytest.raises(ValueError):
        s.set("t_int", True)
    with pytest.raises(ValueError):
        s.set("t_int", 11)
    assert s.get("t_int") == 5
    assert s.set("t_opt", None) is False
    assert s.set("t_opt", "x") is True


def test_same_value_no_write_no_notify(tmp_path, monkeypatch):
    s = SettingsStore(tmp_path)
    calls = []
    s.subscribe("t_int", lambda k, v: calls.append((k, v)))
    n = []
    real = ss.atomic_write_json
    monkeypatch.setattr(ss, "atomic_write_json", lambda *a, **k: (n.append(1), real(*a, **k)))
    assert s.set("t_int", 5) is False
    assert not n and not calls
    s.set("t_int", 6)
    assert calls == [("t_int", 6)] and len(n) == 1


def test_observers(tmp_path, caplog):
    s = SettingsStore(tmp_path)
    got = []

    def bad(k, v):
        raise RuntimeError("x")
    s.subscribe("t_int", bad)
    tok = s.subscribe("t_int", lambda k, v: got.append(v))
    with caplog.at_level(logging.ERROR):
        s.set("t_int", 1)
    assert got == [1] and "observer" in caplog.text
    s.unsubscribe(tok)
    s.set("t_int", 2)
    assert got == [1]


def test_update_single_write(tmp_path, monkeypatch):
    s = SettingsStore(tmp_path)
    got = []
    for k in ("t_int", "t_a", "t_b"):
        s.subscribe(k, lambda k, v: got.append(k))
    n = []
    real = ss.atomic_write_json
    monkeypatch.setattr(ss, "atomic_write_json", lambda *a, **k: (n.append(1), real(*a, **k)))
    assert sorted(s.update({"t_int": 1, "t_a": 2, "t_b": 3})) == ["t_a", "t_b", "t_int"]
    assert len(n) == 1 and sorted(got) == ["t_a", "t_b", "t_int"]
    with pytest.raises(ValueError):
        s.update({"t_a": 9, "t_int": 99})
    assert s.get("t_a") == 2


def test_copies(tmp_path):
    s = SettingsStore(tmp_path)
    s.set("t_dict", {"a": [1]})
    d = s.get("t_dict")
    d["a"].append(2)
    assert s.get("t_dict") == {"a": [1]}


def test_reset(tmp_path):
    s = SettingsStore(tmp_path)
    s.set("t_int", 1)
    assert s.reset("t_int") and s.get("t_int") == 5


def test_invalid_on_disk_uses_default(tmp_path, caplog):
    write(tmp_path, {"schema_version": 1, "t_int": "x", "setup_completed": 1, "t_a": 3})
    with caplog.at_level(logging.WARNING):
        s = SettingsStore(tmp_path)
    assert s.get("t_int") == 5 and s.get(K_SETUP_COMPLETED) is False and s.get("t_a") == 3
    assert "invalid stored value" in caplog.text
    s.set("t_b", 1)
    assert read(tmp_path) == {"schema_version": 1, "t_a": 3, "t_b": 1}


def test_unknown_keys_kept(tmp_path):
    write(tmp_path, {"schema_version": 1, "future_key": [1, 2]})
    s = SettingsStore(tmp_path)
    s.set("t_a", 1)
    assert read(tmp_path)["future_key"] == [1, 2]


def test_future_schema_kept(tmp_path, caplog):
    write(tmp_path, {"schema_version": 7, "t_a": 1})
    s = SettingsStore(tmp_path)
    s.set("t_a", 2)
    assert read(tmp_path)["schema_version"] == 7


def test_migration_from_v0(tmp_path):
    write(tmp_path, {"setup_completed": True})
    s = SettingsStore(tmp_path)
    assert s.get(K_SETUP_COMPLETED) is True
    s.set("t_a", 1)
    assert read(tmp_path)["schema_version"] == 1


def test_fake_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "CURRENT_SCHEMA", 2)
    monkeypatch.setitem(ss.MIGRATIONS, 1, lambda d: {**d, "t_a": d.pop("old_a")})
    write(tmp_path, {"schema_version": 1, "old_a": 4})
    s = SettingsStore(tmp_path)
    assert s.get("t_a") == 4


# ---- recovery ---------------------------------------------------------
def test_corrupt_uses_backup(tmp_path, caplog):
    write(tmp_path, {"t_a": 1}, "settings.json.bak")
    write(tmp_path, "{not json")
    with caplog.at_level(logging.WARNING):
        s = SettingsStore(tmp_path)
    assert s.get("t_a") == 1
    assert list(tmp_path.glob("settings.json.corrupt-*"))
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    assert "restored settings from backup" in caplog.text


def test_both_corrupt_defaults(tmp_path):
    write(tmp_path, "{x")
    write(tmp_path, "{y", "settings.json.bak")
    s = SettingsStore(tmp_path)
    assert s.get("t_int") == 5


def test_list_top_level_is_corrupt(tmp_path):
    write(tmp_path, "[1,2]")
    SettingsStore(tmp_path)
    assert list(tmp_path.glob("settings.json.corrupt-*"))


def test_corrupt_files_pruned(tmp_path):
    for i in range(5):
        f = tmp_path / f"settings.json.corrupt-{100 + i}"
        f.write_text("x")
        os.utime(f, (1000 + i, 1000 + i))
    SettingsStore(tmp_path)
    names = sorted(p.name for p in tmp_path.glob("settings.json.corrupt-*"))
    assert names == [f"settings.json.corrupt-{n}" for n in (102, 103, 104)]


# ---- simulated power cuts --------------------------------------------
class Crash(BaseException):
    pass


def _crash_at(monkeypatch, step):
    """step: 1 = before first replace, 2 = between replaces, 3 = before dir fsync."""
    real_replace = os.replace
    count = {"n": 0}

    def replace(a, b):
        if str(b).endswith(".corrupt") or ".corrupt-" in str(b):
            return real_replace(a, b)
        count["n"] += 1
        if (step == 1 and count["n"] == 1) or (step == 2 and count["n"] == 2):
            raise Crash()
        return real_replace(a, b)
    monkeypatch.setattr(os, "replace", replace)
    if step == 3:
        from calpi.data import atomic

        def fsync_dir(_d):
            raise Crash()
        monkeypatch.setattr(atomic, "_fsync_dir", fsync_dir)


@pytest.mark.parametrize("step,expected", [(1, 1), (2, 1), (3, 2)])
def test_power_cut(tmp_path, monkeypatch, caplog, step, expected):
    s = SettingsStore(tmp_path)
    s.set("t_a", 1)
    s.set("t_b", 1)            # now .bak exists too
    with monkeypatch.context() as m:
        _crash_at(m, step)
        with pytest.raises(Crash):
            s.set("t_a", 2)
    (tmp_path / "settings.json.tmp").write_text("garbage") if step == 1 else None
    with caplog.at_level(logging.WARNING):
        s2 = SettingsStore(tmp_path)
    assert s2.get("t_a") == expected
    assert s2.get("t_b") == 1
    assert not list(tmp_path.glob("settings.json.corrupt-*"))
    if step == 2:
        assert "restored settings from backup" in caplog.text


def test_disk_error_rolls_back(tmp_path, monkeypatch):
    s = SettingsStore(tmp_path)
    s.set("t_a", 1)
    seen = []
    s.subscribe("t_a", lambda k, v: seen.append(v))

    def boom(*a, **k):
        raise OSError("ro fs")
    monkeypatch.setattr(ss, "atomic_write_json", boom)
    with pytest.raises(OSError):
        s.set("t_a", 2)
    assert s.get("t_a") == 1 and seen == []


def test_no_gi_import():
    code = "import sys, calpi.data.settings_store, calpi.data.atomic; sys.exit('gi' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
