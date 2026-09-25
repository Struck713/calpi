from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from calpi.data.sync_text import compute_state

tz = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 25, 14, 30, tzinfo=tz)
REC = NOW.replace(hour=14, minute=5)


def cs(running=False, offline=False, clock=True, net="online", last=REC):
    return compute_state(running, offline, clock, net, last, NOW)


def test_ok_and_empty():
    assert cs() == ("ok", "Updated 14:05")
    assert cs(last=None) == ("ok", "")
    assert cs(net=None, clock=None) == ("ok", "Updated 14:05")


def test_running_wins():
    assert cs(running=True, offline=True, clock=False, net="offline") == ("running", "Updating…")


def test_offline():
    assert cs(offline=True) == ("offline", "Offline · updated 14:05")
    assert cs(net="offline")[0] == "offline"
    assert cs(net="limited")[0] == "offline"
    assert cs(offline=True, last=None) == ("offline", "Offline")


def test_clock_needs_unsynced_and_offline():
    assert cs(clock=False, net="offline") == ("clock", "Clock not set")
    assert cs(clock=False, offline=True)[0] == "clock"
    assert cs(clock=False)[0] == "ok"                       # unsynced but online: no warning
    assert cs(clock=None, net="offline")[0] == "offline"


def test_stale():
    assert cs(last=NOW - timedelta(hours=6))[0] == "ok"
    assert cs(last=NOW - timedelta(hours=6, minutes=1))[0] == "stale"
    y = (NOW - timedelta(days=1)).replace(hour=22, minute=15)
    assert cs(last=y) == ("ok", "Updated yesterday 22:15") or cs(last=y)[1] == "Updated yesterday 22:15"
    assert cs(last=NOW - timedelta(days=3)) == ("stale", "Updated 3 days ago")
    assert cs(last=NOW - timedelta(days=10))[1].startswith("Updated 15 Sep")


def test_offline_beats_stale():
    assert cs(offline=True, last=NOW - timedelta(days=3))[1] == "Offline · updated 3 days ago"
