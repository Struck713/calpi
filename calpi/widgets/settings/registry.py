"""Settings section registry (no gi): ids, order, availability."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# Order numbers (contract): network 10, accounts 20, calendars 30, sync 40, display 50,
# weather 55, preferences 60, status 70, about 90.


@dataclass(frozen=True)
class SectionSpec:
    id: str
    title: str
    order: int
    factory: Callable[[Any], Any]          # (SectionContext) -> Section
    available: Callable[[Any], bool] = lambda app: True


SECTIONS: dict[str, SectionSpec] = {}


def register_section(spec: SectionSpec) -> None:
    if spec.id in SECTIONS:
        raise ValueError(f"duplicate settings section {spec.id!r}")
    SECTIONS[spec.id] = spec


def ordered_sections(app=None) -> list[SectionSpec]:
    """Registered sections sorted by (order, id), filtered by `available(app)`."""
    out = []
    for spec in SECTIONS.values():
        try:
            if spec.available(app):
                out.append(spec)
        except Exception:
            continue
    return sorted(out, key=lambda s: (s.order, s.id))
