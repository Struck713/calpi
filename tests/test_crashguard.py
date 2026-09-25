import pytest

from calpi import crashguard, paths


@pytest.fixture(autouse=True)
def rt(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "runtime_dir", lambda: tmp_path)
    return tmp_path


def test_fifth_start_in_window_is_safe():
    res = [crashguard.record_start_and_check(1000 + i * 10) for i in range(5)]
    assert res == [False, False, False, False, True]


def test_spread_starts_never_safe():
    assert not any(crashguard.record_start_and_check(i * 200.0) for i in range(10))


def test_mark_stable_clears():
    for i in range(5):
        crashguard.record_start_and_check(1000 + i)
    crashguard.mark_stable()
    assert crashguard.record_start_and_check(1010) is False


def test_corrupt_file_is_empty(rt):
    (rt / "starts").write_text("garbage\n\x00")
    assert crashguard.record_start_and_check(100.0) is False
    assert (rt / "starts").read_text().split() == ["100.0"]
