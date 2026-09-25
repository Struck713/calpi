from pathlib import Path

import pytest

from calpi.system import brightness as b

FIX = Path(__file__).parent / "fixtures" / "ddcutil"


def test_percent_to_raw():
    assert b.percent_to_raw(100, 255, 1) == 255
    assert b.percent_to_raw(10, 255, 1) == 26
    assert b.percent_to_raw(1, 100, 0) == 10          # clamped to the 10 % minimum
    assert b.percent_to_raw(100, 100) == 100
    assert b.percent_to_raw(50, 100) == 50
    assert b.percent_to_raw(10, 15, 1) >= 1


def test_software_alpha():
    assert b.software_alpha(100) == 0
    assert b.software_alpha(10) == pytest.approx(0.75)
    assert 0 < b.software_alpha(50) < 0.75
    assert b.software_alpha(0) == pytest.approx(0.75)      # never darker than the minimum


def test_parse_getvcp():
    assert b.parse_getvcp_terse((FIX / "getvcp10_terse.txt").read_text()) == (50, 100)
    assert b.parse_getvcp_terse("VCP 10 ERR") is None
    assert b.parse_getvcp_terse("") is None


def test_parse_detect():
    d = b.parse_detect_terse((FIX / "detect_terse.txt").read_text())
    assert [x["bus"] for x in d] == [2, 4]
    assert d[1]["model"].startswith("ACR")
    assert b.parse_detect_terse("No displays found.") == []


def test_coalescer_latest_wins():
    c = b.Coalescer()
    assert c.submit(1) is True
    assert [c.submit(v) for v in (2, 3, 4)] == [False] * 3
    assert c.done() == 4
    assert c.done() is None
    assert c.submit(5) is True


class FakeBackend:
    supports_power_off = False

    def __init__(self, name="ddc", fail=False):
        self.name, self.fail, self.calls = name, fail, []

    def set(self, p):
        if self.fail:
            raise OSError("boom")
        self.calls.append(p)


class FakeSettings:
    def __init__(self, v=100):
        self.v, self.subs = v, []

    def get(self, k):
        return self.v

    def subscribe(self, k, cb):
        self.subs.append(cb)
        return len(self.subs)

    def set(self, k, v):
        self.v = v
        for cb in self.subs:
            cb(k, v)


def make(backend, settings=None, queue=None):
    settings = settings or FakeSettings()
    alphas, mains = [], []
    q = queue if queue is not None else None
    ctl = b.BrightnessController(
        settings, "brightness", alphas.append,
        call_on_main=lambda fn, *a: fn(*a),
        run_async=(lambda fn: q.append(fn)) if q is not None else (lambda fn: fn()),
        probe_async=lambda work, done, err: done(backend),
        probe_fn=None)
    return ctl, settings, alphas


def test_applies_saved_value_after_probe_and_override_not_saved():
    be = FakeBackend()
    ctl, st, _ = make(be, FakeSettings(60))
    assert be.calls == [60] and ctl.backend_name == "ddc"
    ctl.set_override(10)
    assert be.calls[-1] == 10 and st.v == 60
    ctl.set_override(None)
    assert be.calls[-1] == 60


def test_ddc_serialised_and_coalesced():
    be = FakeBackend()
    queue = []
    ctl, st, _ = make(be, FakeSettings(100), queue)
    assert len(queue) == 1                       # probe-time apply started one job
    for v in (20, 30, 40, 50, 60):
        st.set("brightness", v)
    assert len(queue) == 1                       # never a second concurrent job
    queue.pop()()
    assert be.calls == [100, 60]                 # first and last only


def test_falls_back_to_software_after_three_failures():
    be = FakeBackend(fail=True)
    ctl, st, alphas = make(be)
    seen = []
    ctl.ready_callbacks.add(lambda: seen.append(ctl.backend_name))
    st.set("brightness", 90)
    st.set("brightness", 50)
    assert ctl.backend_name == "software"
    assert seen[-1] == "software"
    assert alphas[-1] == pytest.approx(b.software_alpha(50))


def test_preview_cleared_on_setting_write():
    be = FakeBackend()
    ctl, st, _ = make(be)
    ctl.set_preview(30)
    assert ctl.level() == 30
    st.set("brightness", 30)
    assert ctl.preview is None and ctl.level() == 30


def test_probe_order(tmp_path):
    soft = lambda: b.SoftwareDim(lambda a: None, lambda f, *a: f(*a))  # noqa: E731
    # nothing -> software
    assert b.probe(soft, backlight_root=tmp_path / "none",
                   run=lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())).name == "software"
    # writable backlight wins
    dev = tmp_path / "bl" / "rpi_backlight"
    dev.mkdir(parents=True)
    (dev / "brightness").write_text("1")
    (dev / "max_brightness").write_text("255")
    be = b.probe(soft, backlight_root=tmp_path / "bl")
    assert be.name == "backlight"
    be.set(100)
    assert (dev / "brightness").read_text() == "255"
    # ddc
    def run(cmd, timeout=5):
        if "detect" in cmd:
            return (FIX / "detect_terse.txt").read_text()
        if "d6" in cmd:
            raise OSError("unsupported")
        return (FIX / "getvcp10_terse.txt").read_text()
    d = b.probe(soft, backlight_root=tmp_path / "none", run=run)
    assert d.name == "ddc" and d.bus == 2 and d.raw_max == 100 and not d.supports_power_off


def test_ddc_set_command_and_retry():
    calls = []

    def run(cmd, timeout=5):
        calls.append(cmd)
        if len(calls) == 1:
            raise OSError("flaky")
    d = b.DdcCi(2, 100, run=run)
    d.set(50)
    assert len(calls) == 2 and calls[1][-3:] == ["setvcp", "10", "50"] and "--bus" in calls[1]
