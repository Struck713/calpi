from calpi.data import setup_state as ss

STEPS = ["welcome", "wifi", "preferences", "account", "refresh", "overnight", "done"]
NO_OVERNIGHT = [s for s in STEPS if s != "overnight"]


def test_decide():
    assert ss.decide_start_screen(False, 0, False) == ("wizard", {})
    assert ss.decide_start_screen(True, 0, False) == ("calendar", {})
    assert ss.decide_start_screen(True, 2, False) == ("calendar", {})
    assert ss.decide_start_screen(False, 1, False) == ("calendar", {"setup_completed": True})
    assert ss.decide_start_screen(False, 0, True) == ("calendar", {})
    assert ss.decide_start_screen(False, 1, True) == ("calendar", {})


def test_next_prev():
    assert ss.next_step(STEPS, "welcome") == "wifi"
    assert ss.next_step(STEPS, "done") is None
    assert ss.prev_step(STEPS, "welcome") is None
    assert ss.prev_step(STEPS, "done") == "overnight"
    assert ss.next_step(STEPS, "bogus") is None
    assert ss.prev_step(NO_OVERNIGHT, "done") == "refresh"


def test_resume():
    assert ss.resume_step(STEPS, "refresh") == "refresh"
    assert ss.resume_step(NO_OVERNIGHT, "overnight") == "welcome"
    assert ss.resume_step(STEPS, None) == "welcome"


def test_progress():
    counted = ["wifi", "preferences", "account", "refresh", "overnight"]
    assert ss.progress(counted, "welcome") is None
    assert ss.progress(counted, "done") is None
    assert ss.progress(counted, "wifi") == (1, 5)
    assert ss.progress(counted[:-1], "refresh") == (4, 4)
