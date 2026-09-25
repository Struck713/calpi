from calpi.system import display_power as dp


class Backend:
    def __init__(self, name, power):
        self.name, self.supports_power_off = name, power


OVERLAY = dp.BlackOverlay(lambda a: None, lambda: None)


def runner(table):
    def run(cmd, timeout=5):
        key = cmd[0]
        if key not in table:
            raise OSError("not installed")
        return table[key]
    return run


WLOPM = "HDMI-A-1 on\n"
RANDR = 'HDMI-A-1 "Some Monitor"\n  Enabled: yes\n'


def names(ms):
    return [m.name for m in ms]


def test_wlopm_first_then_others_then_overlay():
    ms = dp.probe(Backend("backlight", True), OVERLAY, run=runner({"wlopm": WLOPM, "wlr-randr": RANDR}))
    assert names(ms) == ["wlopm", "backlight", "wlr-randr", "overlay"]
    assert ms[0].trusted and ms[1].trusted and not ms[2].trusted


def test_wlopm_fails_falls_through():
    ms = dp.probe(Backend("ddc", True), OVERLAY, run=runner({"wlr-randr": RANDR}))
    assert names(ms) == ["ddc", "wlr-randr", "overlay"]
    assert not ms[0].trusted


def test_nothing_available_is_overlay_only():
    ms = dp.probe(Backend("software", False), OVERLAY, run=runner({}))
    assert ms == [OVERLAY]
    assert dp.output_name(ms) == dp.DEFAULT_OUTPUT


def test_no_power_off_support_skips_backend():
    ms = dp.probe(Backend("backlight", False), OVERLAY, run=runner({"wlopm": WLOPM}))
    assert names(ms) == ["wlopm", "overlay"]


def test_commands():
    calls = []
    m = dp.Wlopm("HDMI-A-1", run=lambda c, t=5: calls.append(c))
    m.off(); m.on()
    w = dp.WlrRandr("HDMI-A-1", run=lambda c, t=5: calls.append(c))
    w.off(); w.on()
    assert calls == [["wlopm", "--off", "HDMI-A-1"], ["wlopm", "--on", "HDMI-A-1"],
                     ["wlr-randr", "--output", "HDMI-A-1", "--off"],
                     ["wlr-randr", "--output", "HDMI-A-1", "--on"]]


def test_parsers():
    assert dp.parse_wlopm("HDMI-A-1 on\nHDMI-A-2 off\n") == ["HDMI-A-1", "HDMI-A-2"]
    assert dp.parse_wlopm("usage: wlopm ...") == []
    assert dp.parse_wlr_randr(RANDR) == ["HDMI-A-1"]
