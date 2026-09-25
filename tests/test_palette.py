import re

from calpi.data.formatting import contrast_text
from calpi.data.palette import APP_BG, PALETTE, contrast_ratio


def test_twelve_distinct_lowercase_hex():
    colors = [c for c, _n in PALETTE]
    assert len(colors) == 12 and len(set(colors)) == 12
    assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in colors)
    assert len({n for _c, n in PALETTE}) == 12


def test_contrast_against_background_and_text():
    for color, name in PALETTE:
        assert contrast_ratio(color, APP_BG) >= 3.0, name
        assert contrast_ratio(color, contrast_text(color)) >= 4.5, name


def test_contrast_ratio_extremes():
    assert round(contrast_ratio("#000000", "#ffffff"), 1) == 21.0
