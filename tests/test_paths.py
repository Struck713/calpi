import os
import stat
import pytest
from calpi import paths


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ("STATE_DIRECTORY", "CALPI_STATE_DIR", "RUNTIME_DIRECTORY", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(k, raising=False)
    paths.set_state_dir_override(None)
    yield
    paths.set_state_dir_override(None)


def test_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path / "sd"))
    monkeypatch.setenv("CALPI_STATE_DIR", str(tmp_path / "cs"))
    paths.set_state_dir_override(tmp_path / "ov")
    assert paths.state_dir() == tmp_path / "ov"


def test_state_directory_beats_calpi_env(monkeypatch, tmp_path):
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path / "sd"))
    monkeypatch.setenv("CALPI_STATE_DIR", str(tmp_path / "cs"))
    assert paths.state_dir() == tmp_path / "sd"


def test_colon_form_uses_first(monkeypatch, tmp_path):
    monkeypatch.setenv("STATE_DIRECTORY", f"{tmp_path / 'a'}:{tmp_path / 'b'}")
    assert paths.state_dir() == tmp_path / "a"


def test_calpi_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CALPI_STATE_DIR", str(tmp_path / "cs"))
    assert paths.state_dir() == tmp_path / "cs"


def test_default_under_home(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.state_dir() == tmp_path / ".local/state/calpi"


def test_created_0700(tmp_path):
    paths.set_state_dir_override(tmp_path / "x" / "y")
    p = paths.state_dir()
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o700


def test_runtime_dir_fallback(tmp_path):
    paths.set_state_dir_override(tmp_path)
    assert paths.runtime_dir() == tmp_path / "run"
