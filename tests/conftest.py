import os
import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("CALPI_GTK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set CALPI_GTK_TESTS=1 to run GTK/Broadway tests")
    for item in items:
        if "gtk" in item.keywords:
            item.add_marker(skip)
