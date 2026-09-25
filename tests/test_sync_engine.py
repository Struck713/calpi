import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from calpi.data.settings_store import K_ACCOUNTS, K_SYNC_INTERVAL_MINUTES, SettingsStore
from calpi.sync.worker import RESULT_PREFIX
from calpi import sync_engine
from calpi.sync_engine import Request, SyncEngine, build_argv, parse_result_line


class Timers:
    def __init__(self):
        self.n = 0
        self.live = {}                       # id -> (seconds, cb)

    def add(self, seconds, cb):
        self.n += 1
        self.live[self.n] = (seconds, cb)
        return self.n

    def remove(self, i):
        assert i in self.live, "removing a source that is not armed"
        del self.live[i]

    def find(self, seconds):
        return [i for i, (s, _) in self.live.items() if s == seconds]

    def fire(self, i):
        _s, cb = self.live.pop(i)
        cb()


class Spawner:
    def __init__(self):
        self.calls = []
        self.killed = 0
        self.fail = False

    def __call__(self, req, on_done):
        if self.fail:
            raise OSError("no fork")
        self.calls.append((req, on_done))
        return self

    def force_exit(self):
        self.killed += 1

    def finish(self, obj=None, raw=None):
        _req, cb = self.calls[-1]
        cb(raw if raw is not None else RESULT_PREFIX + json.dumps(obj) + "\n")


def done(changed=False, errors=(None,), window=("2026-01-01T00:00:00Z", "2027-04-01T00:00:00Z")):
    return {"v": 1, "status": "done", "reason": "x", "changed": changed, "window": list(window),
            "accounts": [{"account_id": "a", "error": e, "calendars": []} for e in errors]}


@pytest.fixture
def h(tmp_path, monkeypatch):
    monkeypatch.delenv("CALPI_TEST_SYNC_ON_START", raising=False)
    app = SimpleNamespace(safe_mode=False, settings=SettingsStore(tmp_path), clock=None, window=None,
                          changed=0)
    app.on_data_changed = lambda: setattr(app, "changed", app.changed + 1)
    t, sp = Timers(), Spawner()
    now = [1000.0]
    eng = SyncEngine(app, spawn=sp, timeout_add=t.add, source_remove=t.remove, monotonic=lambda: now[0])
    return SimpleNamespace(app=app, t=t, sp=sp, eng=eng, now=now)


def test_first_run_after_10s_then_interval_from_end(h):
    h.eng.start()
    assert h.t.find(10)
    h.t.fire(h.t.find(10)[0])
    assert len(h.sp.calls) == 1 and h.sp.calls[0][0].reason == "startup"
    assert h.t.find(180)                                    # timeout armed
    h.now[0] = 1007.0
    h.sp.finish(done())
    assert not h.t.find(180)                                # timeout source removed
    assert h.t.find(15 * 60)                                # armed from the END of the run
    h.t.fire(h.t.find(15 * 60)[0])
    assert h.sp.calls[1][0].reason == "interval"


def test_requests_while_running_coalesce(h):
    h.eng.request_sync("a")
    h.eng.request_sync("b", extra=(date(2030, 1, 1), date(2030, 2, 1)))
    h.eng.request_sync("c", force=True, extra=(date(2029, 1, 1), date(2029, 2, 1)))
    assert len(h.sp.calls) == 1
    assert h.eng._pending.force and h.eng._pending.extra == (date(2029, 1, 1), date(2030, 2, 1))
    h.sp.finish(done())
    assert len(h.sp.calls) == 2                             # exactly one follow-up
    assert h.sp.calls[1][0].force
    assert not h.t.find(15 * 60)                            # no interval armed while a run is active
    h.sp.finish(done())
    assert len(h.sp.calls) == 2 and h.t.find(15 * 60)


def test_request_merge_reason():
    m = Request("a").merge(Request("b")).merge(Request("a"))
    assert m.reason == "coalesced:a,b"


def test_timeout_kills_and_marks_timeout(h):
    got = []
    h.eng.result_callbacks.append(got.append)
    h.eng.request_sync("x")
    h.eng.app.settings.set(K_ACCOUNTS, [])                  # no accounts: nothing to mark
    h.t.fire(h.t.find(180)[0])
    assert h.sp.killed == 1
    h.sp.finish(raw="")                                     # killed: no output
    assert got[0]["status"] == "crashed" and h.eng.last_result is got[0]
    assert h.t.find(15 * 60)                                # schedule continues
    assert not h.eng.is_running


def test_timeout_marks_every_account(h):
    from dataclasses import asdict
    from test_fetch import ACC
    h.app.settings.set(K_ACCOUNTS, [asdict(ACC)])
    h.eng.request_sync("x")
    h.t.fire(h.t.find(180)[0])
    h.sp.finish(raw="")
    assert [a["error"] for a in h.eng.last_result["accounts"]] == ["TIMEOUT"]


def test_bad_output_handled_as_unknown(h, caplog):
    from dataclasses import asdict
    from test_fetch import ACC
    h.app.settings.set(K_ACCOUNTS, [asdict(ACC)])
    for raw in ("", "hello\n", RESULT_PREFIX + "{not json\n"):
        h.eng.request_sync("x")
        h.sp.finish(raw=raw)
        assert h.eng.last_result["accounts"][0]["error"] == "UNKNOWN"
        assert not h.eng.is_running and h.t.find(15 * 60)
        h.t.fire(h.t.find(15 * 60)[0]) if False else None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_spawn_failure_keeps_schedule(h):
    h.sp.fail = True
    h.eng.request_sync("x")
    assert not h.eng.is_running and h.t.find(15 * 60)


def test_interval_change_reschedules(h):
    h.eng.start()
    h.t.fire(h.t.find(10)[0])
    h.now[0] = 1000.0
    h.sp.finish(done())
    assert h.t.find(900)
    h.now[0] = 1300.0
    h.app.settings.set(K_SYNC_INTERVAL_MINUTES, 5)          # due = 1000+300-1300 = 0 -> now
    assert not h.t.find(900) and h.t.find(1)
    h.app.settings.set(K_SYNC_INTERVAL_MINUTES, 60)
    assert h.t.find(3600 - 300)


def test_debounce_accounts_and_browse(h):
    h.eng.start()
    h.t.fire(h.t.find(10)[0])
    h.sp.finish(done())
    n = len(h.sp.calls)
    h.app.settings.set(K_ACCOUNTS, [])                      # valid: empty list is the default -> maybe no change
    from dataclasses import asdict
    from test_fetch import ACC
    h.app.settings.set(K_ACCOUNTS, [asdict(ACC)])
    assert len(h.t.find(2)) == 1
    h.t.fire(h.t.find(2)[0])
    assert len(h.sp.calls) == n + 1 and h.sp.calls[-1][0].reason == "accounts-changed"
    h.sp.finish(done())
    # browsing: five outside-window month changes -> one request
    h.app.window = SimpleNamespace(month_view=SimpleNamespace(visible_range=lambda: (date(2040, 1, 1), date(2040, 2, 12))))
    for _ in range(5):
        h.eng._on_month_changed(2040, 1)
    assert len(h.t.find(3)) == 1
    h.t.fire(h.t.find(3)[0])
    req = h.sp.calls[-1][0]
    assert req.reason == "browse" and req.extra == (date(2040, 1, 1), date(2040, 2, 12))


def test_inside_window_month_change_does_nothing(h, monkeypatch):
    h.eng.synced_window = (datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc))
    h.app.window = SimpleNamespace(month_view=SimpleNamespace(visible_range=lambda: (date(2040, 1, 1), date(2040, 2, 12))))
    h.eng._on_month_changed(2040, 1)
    assert not h.t.live


def test_safe_mode_arms_nothing_but_manual_works(h):
    h.app.safe_mode = True
    h.eng.start()
    assert not h.t.live
    h.eng.request_sync("manual")
    assert len(h.sp.calls) == 1


def test_changed_calls_on_data_changed_once(h):
    h.eng.request_sync("x")
    h.sp.finish(done(changed=False))
    assert h.app.changed == 0
    h.eng.request_sync("x")
    h.sp.finish(done(changed=True))
    assert h.app.changed == 1


def test_callbacks_state_and_success_time(h):
    states, res = [], []
    h.eng.state_callbacks.append(states.append)
    h.eng.result_callbacks.append(res.append)
    h.eng.request_sync("x")
    assert states == [True] and h.eng.is_running
    h.sp.finish(done(errors=("AUTH_FAILED",)))
    assert states == [True, False] and len(res) == 1 and h.eng.last_success_wall is None
    h.eng.request_sync("x")
    h.sp.finish(done(errors=("AUTH_FAILED", None)))
    assert h.eng.last_success_wall is not None
    assert h.eng.synced_window[0] == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_callback_exception_does_not_break(h):
    h.eng.result_callbacks.append(lambda r: 1 / 0)
    h.eng.request_sync("x")
    h.sp.finish(done())
    assert not h.eng.is_running and h.t.find(15 * 60)


def test_parse_result_line_and_argv():
    assert parse_result_line(f"log\n{RESULT_PREFIX}" + '{"status":"done"}\n')["status"] == "done"
    assert parse_result_line(None) is None and parse_result_line(RESULT_PREFIX + "[1]") is None
    a = build_argv(Request("r", True, (date(2030, 1, 1), date(2030, 2, 1))), python="/py")
    assert a[-8:] == ["/py", "-m", "calpi.sync.worker", "--reason", "r", "--force",
                      "--extra-range", "2030-01-01:2030-02-01"]
