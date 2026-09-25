import pytest

from calpi.widgets.settings import registry
from calpi.widgets.settings.registry import SectionSpec, ordered_sections, register_section


@pytest.fixture(autouse=True)
def clean():
    saved = dict(registry.SECTIONS)
    registry.SECTIONS.clear()
    yield
    registry.SECTIONS.clear()
    registry.SECTIONS.update(saved)


def spec(i, order, **kw):
    return SectionSpec(i, i.title(), order, lambda ctx: None, **kw)


def test_order():
    register_section(spec("about", 90))
    register_section(spec("network", 10))
    register_section(spec("b", 40))
    register_section(spec("a", 40))
    assert [s.id for s in ordered_sections()] == ["network", "a", "b", "about"]


def test_duplicate_rejected():
    register_section(spec("x", 1))
    with pytest.raises(ValueError):
        register_section(spec("x", 2))


def test_available_filter_and_errors():
    register_section(spec("yes", 1))
    register_section(spec("no", 2, available=lambda app: False))
    def boom(app): raise RuntimeError
    register_section(spec("boom", 3, available=boom))
    assert [s.id for s in ordered_sections(object())] == ["yes"]
