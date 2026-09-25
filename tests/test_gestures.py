from calpi.data.gestures import classify_swipe as c, should_claim


def test_thresholds():
    assert c(-150, 0, 0.5) == 1
    assert c(150, 0, 0.5) == -1
    assert c(-149, 0, 0.5) == 0
    assert c(-300, 150, 0.5) == 1      # ratio exactly 2
    assert c(200, 110, 0.5) == 0       # diagonal
    assert c(-200, 0, 1.0) == 1
    assert c(-200, 0, 1.2) == 0        # slow
    assert c(-200, 0, 0) == 0


def test_flick():
    assert c(-90, 0, 0.08) == 1
    assert c(-80, 0, 0.1) == 1         # exactly 800 px/s
    assert c(-79, 0, 0.05) == 0
    assert c(-90, 0, 0.2) == 0         # too slow for a flick


def test_tap():
    assert c(5, 2, 0.1) == 0
    assert not should_claim(19, 0)
    assert should_claim(40, 20)
    assert not should_claim(40, 21)
    assert not should_claim(10, 100)
