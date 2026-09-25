import threading
from gi.repository import GLib
from calpi.tasks import run_in_thread, safe_callback


def _run(loop):
    GLib.timeout_add(2000, lambda: loop.quit() or False)
    loop.run()


def test_on_done_main_thread():
    loop = GLib.MainLoop()
    got = {}

    def done(v):
        got["v"] = v
        got["main"] = threading.current_thread() is threading.main_thread()
        loop.quit()
    run_in_thread(lambda: 42, on_done=done)
    _run(loop)
    assert got == {"v": 42, "main": True}


def test_on_error_main_thread():
    loop = GLib.MainLoop()
    got = {}

    def boom():
        raise ValueError("x")

    def err(e):
        got["e"] = e
        got["main"] = threading.current_thread() is threading.main_thread()
        loop.quit()
    run_in_thread(boom, on_error=err)
    _run(loop)
    assert isinstance(got["e"], ValueError) and got["main"]


def test_safe_callback_keeps_timer_running(caplog):
    loop = GLib.MainLoop()
    n = {"c": 0}

    @safe_callback(repeat=True)
    def tick():
        n["c"] += 1
        if n["c"] == 1:
            raise RuntimeError("first")
    GLib.timeout_add(10, tick)
    GLib.timeout_add(200, lambda: loop.quit() or False)
    loop.run()
    assert n["c"] >= 3
    assert "Traceback" in caplog.text or any(r.exc_info for r in caplog.records)


def test_safe_callback_none_removes():
    assert safe_callback(lambda: None, repeat=None)() == GLib.SOURCE_REMOVE
