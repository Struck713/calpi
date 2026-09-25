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
