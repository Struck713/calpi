import logging
import os
import stat
import subprocess
import sys

import pytest

from calpi.data import credentials as C
from calpi.data.credentials import CredentialStore, Secret

PW = "abcd-efgh-ijkl-mnop"


def store(tmp_path, serial="0123456789abcdef"):
    return CredentialStore(tmp_path, serial_fn=lambda: (serial, "test"))


def test_round_trip(tmp_path):
    s = store(tmp_path)
    assert s.status() == "empty" and s.ids() == [] and s.get("a") is None
    s.set("acct-1", Secret(PW))
    s.set("acct-2", Secret("second-secret"))
    s2 = store(tmp_path)
    assert s2.status() == "ok" and s2.ids() == ["acct-1", "acct-2"]
    assert s2.get("acct-1").reveal() == PW
    s2.delete("acct-1")
    assert store(tmp_path).ids() == ["acct-2"]


def test_no_plaintext_and_perms(tmp_path):
    s = store(tmp_path)
    s.set("acct-sensitive", Secret(PW))
    blob = (tmp_path / "credentials.bin").read_bytes()
    assert b"abcd" not in blob and b"acct-sensitive" not in blob and blob[:4] == b"CPC1"
    assert stat.S_IMODE((tmp_path / "credentials.bin").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "keys/credentials.key").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "keys").stat().st_mode) == 0o700
    assert len((tmp_path / "keys/credentials.key").read_bytes()) == 32


def test_new_nonce_per_write(tmp_path):
    s = store(tmp_path)
    s.set("a", Secret(PW))
    b1 = (tmp_path / "credentials.bin").read_bytes()
    s.set("a", Secret(PW))
    assert (tmp_path / "credentials.bin").read_bytes() != b1


def test_keyfile_never_overwritten(tmp_path):
    s = store(tmp_path)
    s.set("a", Secret(PW))
    k = (tmp_path / "keys/credentials.key").read_bytes()
    store(tmp_path).set("b", Secret("another-secret"))
    assert (tmp_path / "keys/credentials.key").read_bytes() == k


def test_different_serial_unreadable_then_recover(tmp_path, caplog):
    store(tmp_path).set("a", Secret(PW))
    s = store(tmp_path, serial="ffffffffffffffff")
    with caplog.at_level(logging.ERROR, logger="calpi.credentials"):
        assert s.status() == "unreadable"
        assert s.get("a") is None and s.ids() == []
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1
    s.set("b", Secret("new-secret-value"))
    assert list(tmp_path.glob("credentials.bin.unreadable-*"))
    s3 = store(tmp_path, serial="ffffffffffffffff")
    assert s3.status() == "ok" and s3.get("b").reveal() == "new-secret-value"


@pytest.mark.parametrize("mutate", [
    lambda b: b[:-1] + bytes([b[-1] ^ 1]),
    lambda b: b"XXXX" + b[4:],
    lambda b: b[:20],
    lambda b: b"",
])
def test_tamper_unreadable(tmp_path, mutate):
    store(tmp_path).set("a", Secret(PW))
    f = tmp_path / "credentials.bin"
    f.write_bytes(mutate(f.read_bytes()))
    s = store(tmp_path)
    assert s.status() == "unreadable" and s.get("a") is None


def test_bad_keyfile_length_not_overwritten(tmp_path):
    store(tmp_path).set("a", Secret(PW))
    kf = tmp_path / "keys/credentials.key"
    kf.write_bytes(b"short")
    s = store(tmp_path)
    assert s.status() == "unreadable"
    assert kf.read_bytes() == b"short"


def test_reload_on_external_change(tmp_path):
    a, b = store(tmp_path), store(tmp_path)
    a.set("x", Secret(PW))
    assert b.ids() == ["x"]
    a.set("y", Secret("another-secret"))
    assert b.ids() == ["x", "y"]


def test_secret_type():
    s = Secret(PW)
    assert repr(s) == "Secret('***')" and str(s) == "Secret('***')"
    with pytest.raises(TypeError):
        hash(s)
    import pickle
    with pytest.raises(TypeError):
        pickle.dumps(s)
    with pytest.raises(ValueError):
        Secret("")


def _handler():
    import io
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(C.RedactingFormatter("%(message)s"))
    h.addFilter(C._REDACTOR)
    lg = logging.getLogger("t.redact")
    lg.setLevel(logging.INFO)
    lg.propagate = False
    lg.addHandler(h)
    return lg, buf, h


def test_redaction_message_and_traceback():
    secret = Secret("s3cret-value-xyz")
    lg, buf, h = _handler()
    try:
        lg.info(f"password is {secret.reveal()}")
        try:
            raise ValueError(f"bad {secret.reveal()}")
        except ValueError:
            lg.exception("failed")
    finally:
        lg.removeHandler(h)
    out = buf.getvalue()
    assert "s3cret-value-xyz" not in out and "***" in out and "Traceback" in out


def test_hardware_serial_parsing(monkeypatch):
    from pathlib import Path
    real_bytes, real_text = Path.read_bytes, Path.read_text

    def rb(self):
        if str(self).endswith("devicetree/base/serial-number"):
            return b"00000000ABCDEF12\x00"
        return real_bytes(self)
    monkeypatch.setattr(Path, "read_bytes", rb)
    assert C.hardware_serial() == ("00000000abcdef12", "devicetree")

    def rb_missing(self):
        if str(self).endswith("serial-number"):
            raise FileNotFoundError
        return real_bytes(self)

    def rt(self, *a, **k):
        if str(self) == "/proc/cpuinfo":
            return "processor : 0\nSerial\t\t: 00000000abcdef12\n"
        return real_text(self, *a, **k)
    monkeypatch.setattr(Path, "read_bytes", rb_missing)
    monkeypatch.setattr(Path, "read_text", rt)
    assert C.hardware_serial() == ("00000000abcdef12", "cpuinfo")


def test_no_gi_import():
    code = "import sys; import calpi.data.credentials; sys.exit(1 if 'gi' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code], cwd=os.path.dirname(os.path.dirname(__file__))).returncode == 0
