import os
import pytest

# US-32: tests that don't exercise the setup wizard start straight on the calendar.
os.environ.setdefault("CALPI_SKIP_SETUP", "1")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("CALPI_GTK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set CALPI_GTK_TESTS=1 to run GTK/Broadway tests")
    for item in items:
        if "gtk" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("env")
    """Each test gets its own XDG_STATE_HOME (so the default ~/.local/state/calpi is never touched)
    and RUNTIME_DIRECTORY (crash counter, sync lock). Tests that pass their own state or
    runtime dir still override these."""
    monkeypatch.setenv("XDG_STATE_HOME", str(base / "xdg-state"))
    run = base / "runtime"
    run.mkdir()
    monkeypatch.setenv("RUNTIME_DIRECTORY", str(run))
    monkeypatch.delenv("STATE_DIRECTORY", raising=False)
    monkeypatch.delenv("CALPI_STATE_DIR", raising=False)


@pytest.fixture(scope="session", autouse=True)
def _broadway_for_in_process_gtk():
    """Tests that import Gtk inside the pytest process (not in a subprocess) need a display:
    give them their own Broadway daemon on a unique display instead of whatever $DISPLAY is."""
    if os.environ.get("CALPI_GTK_TESTS") != "1":
        yield
        return
    import subprocess
    import time
    disp = os.environ.get("CALPI_TEST_BROADWAY", ":61")
    p = subprocess.Popen(["gtk4-broadwayd", disp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    time.sleep(1)
    os.environ["GDK_BACKEND"] = "broadway"
    os.environ["BROADWAY_DISPLAY"] = disp
    yield
    p.terminate()
