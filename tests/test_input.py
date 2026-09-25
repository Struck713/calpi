from calpi.input import CursorPolicy, route_key, MOUSE, TOUCHSCREEN, MOTION, TOUCH


def test_hidden_by_default_and_touch_never_shows():
    p = CursorPolicy()
    assert p.visible is False
    assert p.on_event(TOUCHSCREEN, TOUCH, 1.0) == (False, None)


def test_motion_shows_and_hides_after_3s_with_one_timer():
    p = CursorPolicy()
    vis, delay = p.on_event(MOUSE, MOTION, 0.0)
    assert vis is True and delay == 3.0
    timers = 1
    for t in (0.5, 1.0, 2.0):
        vis, delay = p.on_event(MOUSE, MOTION, t)
        assert vis is True
        timers += delay is not None
    assert timers == 1
    vis, delay = p.on_timer(3.0)          # last motion at 2.0: not yet
    assert vis is None and abs(delay - 2.0) < 1e-9
    assert p.on_timer(5.0) == (False, None)
    assert p.visible is False and p.timer_pending is False


def test_touch_hides_immediately():
    p = CursorPolicy()
    p.on_event(MOUSE, MOTION, 0.0)
    assert p.on_event(TOUCHSCREEN, TOUCH, 0.1)[0] is False


class Screen:
    def __init__(self, ret): self.ret, self.keys = ret, []
    def on_key(self, n, s): self.keys.append(n); return self.ret


class Nav:
    def __init__(self, cur, screen): self.current, self.s, self.went_back = cur, screen, False
    def get(self, n): return self.s
    def back(self): self.went_back = True


def test_screen_handles_key():
    s = Screen(True); n = Nav("day", s)
    assert route_key(n, "Left", 0) and not n.went_back


def test_escape_goes_back_except_on_calendar():
    n = Nav("day", Screen(False))
    assert route_key(n, "Escape", 0) and n.went_back
    n = Nav("calendar", Screen(False))
    assert not route_key(n, "Escape", 0) and not n.went_back


def test_failing_handler_does_not_break_router():
    class Bad:
        def on_key(self, n, s): raise RuntimeError
    n = Nav("day", Bad())
    assert route_key(n, "Escape", 0) and n.went_back
