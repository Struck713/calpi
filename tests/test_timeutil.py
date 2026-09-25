import importlib
import time
from datetime import datetime

import pytest

from calpi.data import timeutil


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.delenv("CALPI_FAKE_NOW", raising=False)
    monkeypatch.delenv("CALPI_TZ", raising=False)
    yield
    monkeypatch.delenv("CALPI_FAKE_NOW", raising=False)
    monkeypatch.delenv("CALPI_TZ", raising=False)
    timeutil._override_tz = None
    timeutil._fake_offset = None


def test_fake_now_offset_and_moves(monkeypatch):
    monkeypatch.setenv("CALPI_TZ", "UTC")
    monkeypatch.setenv("CALPI_FAKE_NOW", "2026-02-28T23:59:30")
    importlib.reload(timeutil)
    a = timeutil.now()
    assert abs((a.replace(tzinfo=None) - datetime(2026, 2, 28, 23, 59, 30)).total_seconds()) < 2
    time.sleep(0.05)
    assert timeutil.now() > a


def test_override_tz():
    timeutil.set_display_tz("America/New_York")
    assert timeutil.now().tzinfo.key == "America/New_York"
    timeutil.set_display_tz(None)
    assert timeutil._override_tz is None


def test_bad_tz_falls_back(monkeypatch, caplog):
    monkeypatch.setenv("CALPI_TZ", "Nope/Nowhere")
    assert timeutil.display_tz().key == "UTC"
    assert "unknown system time zone" in caplog.text


def test_today_is_date():
    assert timeutil.today() == timeutil.now().date()
