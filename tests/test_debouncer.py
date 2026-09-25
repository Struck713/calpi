from calpi.data.debounce import Debouncer


class Sched:
    def __init__(self):
        self.now, self.items, self.n = 0.0, {}, 0

    def schedule(self, delay, fn):
        self.n += 1
        self.items[self.n] = (self.now + delay, fn)
        return self.n

    def cancel(self, h):
        self.items.pop(h, None)

    def advance(self, dt):
        self.now += dt
        for h, (t, fn) in sorted(self.items.items(), key=lambda kv: kv[1][0]):
            if t <= self.now and h in self.items:
                del self.items[h]
                fn()


def make():
    s, out = Sched(), []
    return s, out, Debouncer(0.5, out.append, s.schedule, s.cancel)


def test_last_value_wins_after_quiet_period():
    s, out, d = make()
    d.call(1); s.advance(0.3); d.call(2); s.advance(0.3)
    assert out == []
    s.advance(0.3)
    assert out == [2] and not d.pending


def test_flush_runs_immediately_once():
    s, out, d = make()
    d.call(5)
    d.flush(); d.flush()
    s.advance(1)
    assert out == [5]


def test_cancel_drops():
    s, out, d = make()
    d.call(1); d.cancel(); s.advance(1)
    assert out == [] and not d.pending
