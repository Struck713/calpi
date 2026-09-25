from calpi.inactivity import InactivityTracker


def make():
    t = [0.0]
    return t, InactivityTracker(clock=lambda: t[0])


def test_fires_once_and_rearms():
    t, tr = make()
    calls = []
    tr.add(10, lambda: calls.append(1))
    t[0] = 9; tr.check(); assert calls == []
    t[0] = 10; tr.check(); assert calls == [1]
    t[0] = 50; tr.check(); assert calls == [1]
    tr.touch()
    t[0] = 55; tr.check(); assert calls == [1]
    t[0] = 60; tr.check(); assert calls == [1, 1]


def test_two_listeners_independent():
    t, tr = make()
    a, b = [], []
    tr.add(5, lambda: a.append(1))
    tr.add(20, lambda: b.append(1))
    t[0] = 6; tr.check(); assert (a, b) == ([1], [])
    t[0] = 21; tr.check(); assert (a, b) == ([1], [1])


def test_remove_and_set_timeout():
    t, tr = make()
    calls = []
    h = tr.add(5, lambda: calls.append(1))
    tr.remove(h)
    t[0] = 100; tr.check(); assert calls == []
    h = tr.add(500, lambda: calls.append(2))
    tr.set_timeout(h, 150)
    t[0] = 260; tr.check(); assert calls == [2]


def test_exception_isolated():
    t, tr = make()
    calls = []
    tr.add(1, lambda: 1 / 0)
    tr.add(1, lambda: calls.append(1))
    t[0] = 2; tr.check(); assert calls == [1]
