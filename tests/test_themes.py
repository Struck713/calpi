import re
from pathlib import Path

from calpi.data import settings_store, themes
from calpi.data.palette import contrast_ratio


def test_themes_define_the_same_tokens():
    assert set(themes.THEMES["dark"]) == set(themes.THEMES["light"])
    assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for t in themes.THEMES.values() for c in t.values())


def test_every_token_in_style_css_is_defined():
    css = (Path(__file__).parents[1] / "calpi" / "style.css").read_text()
    used = set(re.findall(r"@([a-z_]+)", css.replace("@define-color", "")))
    assert used <= set(themes.THEMES["dark"]), used - set(themes.THEMES["dark"])
    assert "@define-color" not in css and not re.search(r"#[0-9a-fA-F]{3,6}\b", css)


def test_text_is_readable_in_both_themes():
    for name, t in themes.THEMES.items():
        assert contrast_ratio(t["text"], t["bg"]) >= 7, name
        assert contrast_ratio(t["text_dim"], t["surface"]) >= 4.5, name
        assert contrast_ratio(t["on_accent"], t["accent"]) >= 4.5, name
        assert contrast_ratio(t["accent"], t["bg"]) >= 3.0, name


def test_setting_defaults_to_dark_and_validates():
    key = settings_store.REGISTRY[settings_store.K_THEME]
    assert key.default == "dark" and key.validate("light") and not key.validate("blue")
    assert themes.normalize("nonsense") == "dark"
    assert themes.css_defines("light").count("@define-color") == len(themes.THEMES["light"])
