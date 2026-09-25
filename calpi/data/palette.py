"""Calendar colour palette (US-26). No gi imports. Contrast-checked in tests/test_palette.py."""
from __future__ import annotations

from calpi.data.formatting import relative_luminance

APP_BG = "#101418"

PALETTE: list[tuple[str, str]] = [
    ("#4f9dff", "Blue"), ("#3ecf8e", "Green"), ("#ffb020", "Amber"), ("#ff6b6b", "Red"),
    ("#c77dff", "Purple"), ("#2ec5d3", "Teal"), ("#ff8fb1", "Pink"), ("#a3d65c", "Lime"),
    ("#ff9248", "Orange"), ("#8fa3ff", "Periwinkle"), ("#e0c068", "Sand"), ("#b0bec5", "Grey"),
]


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 2.x contrast ratio of two '#rrggbb' colours (1..21)."""
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)
