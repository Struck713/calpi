"""Settings screen package. Importing this package is cheap and needs no display.

Section modules register themselves with `registry.register_section` when imported.
`load_sections()` is the ONE place that lists the section modules; later stories add theirs here.
"""
from __future__ import annotations

import importlib
import logging
import os

log = logging.getLogger("calpi.settings.ui")

SECTION_MODULES = [
    "about",
    "accounts",
    # US-23 network, US-25 accounts, US-26 calendars, US-27 sync, US-29 display,
    # US-28 preferences, US-31 status: append here when implemented.
]


def load_sections() -> None:
    mods = list(SECTION_MODULES)
    if os.environ.get("CALPI_DEV_ROWS") == "1":
        mods.append("dev_rows")
    if os.environ.get("CALPI_TEST_BAD_SECTION") == "1":
        mods.append("dev_bad")
    for name in mods:
        try:
            importlib.import_module(f"{__name__}.{name}")
        except Exception:
            log.exception("settings section module %s failed to import", name)
