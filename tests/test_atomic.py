import os
import pytest
from calpi.data import atomic


def test_write_and_backup(tmp_path):
    p = tmp_path / "f.json"
    atomic.atomic_write_json(p, {"a": 1}, keep_backup=True)
    atomic.atomic_write_json(p, {"a": 2}, keep_backup=True)
    assert '"a": 2' in p.read_text()
    assert '"a": 1' in (tmp_path / "f.json.bak").read_text()
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert not (tmp_path / "f.json.tmp").exists()


def test_failed_write_removes_tmp(tmp_path, monkeypatch):
    def boom(fd):
        raise OSError("disk full")
    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError):
        atomic.atomic_write_bytes(tmp_path / "f", b"x")
    assert list(tmp_path.iterdir()) == []
