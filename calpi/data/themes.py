"""Light / dark colour themes. No gi imports.

GTK 4.8 has no CSS var(), so style.css uses @named colours and `css_defines()` prepends the
`@define-color` lines for the active theme. The cairo week view reads the same tokens via `rgb()`.
"""
from __future__ import annotations

THEME_NAMES = ("dark", "light")
DEFAULT_THEME = "dark"

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#101418", "surface": "#182028", "bg_deep": "#0d1216", "weekend": "#12171c",
        "text": "#e8e8e8", "text_dim": "#9aa4ae", "text_faint": "#5c6670",
        "accent": "#4f9dff", "on_accent": "#101418", "danger": "#ff6b6b",
        "warn": "#e0a040", "ok": "#4caf50",
        "key": "#26303a", "key_special": "#1b232b", "key_on": "#3a4a5a", "toast": "#2b3642",
        "osk_dock": "#0b0f13",
    },
    "light": {
        "bg": "#f4f6f8", "surface": "#ffffff", "bg_deep": "#e6eaee", "weekend": "#e9edf1",
        "text": "#1a1f24", "text_dim": "#525d68", "text_faint": "#78838d",
        "accent": "#1a6fe0", "on_accent": "#ffffff", "danger": "#d02f2f",
        "warn": "#b06a00", "ok": "#2e8b3a",
        "key": "#ffffff", "key_special": "#d5dbe1", "key_on": "#b8c4d0", "toast": "#d9e0e6",
        "osk_dock": "#dde2e7",
    },
}

_current = DEFAULT_THEME


def normalize(name) -> str:
    return name if name in THEMES else DEFAULT_THEME


def set_current(name: str) -> None:
    global _current
    _current = normalize(name)


def current() -> str:
    return _current


def color(token: str, name: str | None = None) -> str:
    return THEMES[name or _current][token]


def rgb(token: str, name: str | None = None) -> tuple[float, float, float]:
    c = color(token, name)
    return tuple(int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))     # type: ignore[return-value]


def css_defines(name: str | None = None) -> str:
    return "\n".join(f"@define-color {k} {v};" for k, v in THEMES[name or _current].items())
