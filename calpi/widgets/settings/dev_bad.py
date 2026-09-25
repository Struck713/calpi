"""Test-only section whose factory raises (CALPI_TEST_BAD_SECTION=1)."""
from calpi.widgets.settings.registry import SectionSpec, register_section


def _boom(ctx):
    raise RuntimeError("deliberate test failure")


register_section(SectionSpec("badtest", "Broken (test)", 5, _boom))
