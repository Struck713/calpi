import os
import socket

import pytest

from calpi import watchdog


@pytest.fixture
def sock(tmp_path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.settimeout(2)
    yield s, tmp_path
    s.close()


def test_ready_and_ping(sock, monkeypatch):
    s, tmp = sock
    path = str(tmp / "n.sock")
    s.bind(path)
    monkeypatch.setenv("NOTIFY_SOCKET", path)
    assert watchdog.ready("up") is True
    assert s.recv(200) == b"READY=1\nSTATUS=up"
    assert watchdog.ping()
    assert s.recv(200) == b"WATCHDOG=1"
    watchdog.stopping()
    assert s.recv(200) == b"STOPPING=1"
    watchdog.status("hi")
    assert s.recv(200) == b"STATUS=hi"


def test_abstract_socket(sock, monkeypatch):
    s, _ = sock
    name = f"calpi-test-{os.getpid()}"
    s.bind("\0" + name)
    monkeypatch.setenv("NOTIFY_SOCKET", "@" + name)
    assert watchdog.ping()
    assert s.recv(100) == b"WATCHDOG=1"


def test_no_socket_is_noop(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert watchdog.ready() is False
    assert watchdog.ping() is False


def test_dead_socket_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "missing"))
    assert watchdog.ping() is False


def test_interval(monkeypatch):
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    assert watchdog.watchdog_interval_s() is None
    monkeypatch.setenv("WATCHDOG_USEC", "30000000")
    assert watchdog.watchdog_interval_s() == 30.0
