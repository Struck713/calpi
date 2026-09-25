"""On-screen keyboard layout data (pure Python, no gi).

purpose -> layer name -> rows -> Key specs. Every printable ASCII character
(0x20-0x7E) is reachable for the text, password, email and url purposes.
Non-ASCII characters are out of scope (Wi-Fi and iCloud app passwords are ASCII).
"""
from __future__ import annotations

from dataclasses import dataclass

PURPOSES = ("text", "email", "password", "url", "number")
MAX_ROW_UNITS = 11.5


@dataclass(frozen=True)
class Key:
    label: str = ""
    insert: str | None = None
    action: str | None = None
    width: float = 1.0


def _ins(chars: str, width: float = 1.0) -> list[Key]:
    return [Key(c, insert=c, width=width) for c in chars]


BACKSPACE = Key("⌫", action="backspace", width=1.5)
SHIFT = Key("⇧", action="shift", width=1.25)


def _bottom(switch_label: str, switch_to: str) -> list[Key]:
    return [Key(switch_label, action=f"layer:{switch_to}", width=1.5),
            Key("←", action="left"),
            Key("space", action="space", width=4.0),
            Key("→", action="right"),
            Key("Clear", action="clear", width=1.2),
            Key("Hide", action="hide", width=1.2),
            Key("Done", action="done", width=1.6)]


def _letters(quick: list[Key] | None = None, row2_extra: str = "") -> list[list[Key]]:
    rows = []
    if quick:
        rows.append(quick)
    rows += [
        _ins("qwertyuiop") + [BACKSPACE],
        _ins("asdfghjkl" + row2_extra),
        [SHIFT] + _ins("zxcvbnm.-") + [SHIFT],
        _bottom("?123", "symbols"),
    ]
    return rows


_SYMBOLS = [
    _ins("1234567890") + [BACKSPACE],
    _ins("-/:;()$&@\""),
    [Key("#+=", action="layer:more", width=1.5)] + _ins(".,?!'", 1.5),
    _bottom("ABC", "letters"),
]
_MORE = [
    _ins("[]{}#%^*+=") + [BACKSPACE],
    _ins("_\\|~<>`"),
    [Key("?123", action="layer:symbols", width=1.5)],
    _bottom("ABC", "letters"),
]

_TEXT = {"letters": _letters(), "symbols": _SYMBOLS, "more": _MORE}
_EMAIL = {"letters": _letters(_ins("@.-_") + [Key(".com", insert=".com", width=2.0)]),
          "symbols": _SYMBOLS, "more": _MORE}
_URL = {"letters": _letters([Key("https://", insert="https://", width=2.0)] + _ins("/:.-_~?=&")),
        "symbols": _SYMBOLS, "more": _MORE}
_NUMBER = {"numbers": [
    _ins("123", 1.5) + [BACKSPACE],
    _ins("456", 1.5),
    _ins("789", 1.5),
    _ins(".", 1.5) + _ins("0", 1.5) + [Key("Clear", action="clear", width=1.5)],
    [Key("Hide", action="hide", width=2.0), Key("Done", action="done", width=3.0)],
]}

LAYOUTS: dict[str, dict[str, list[list[Key]]]] = {
    "text": _TEXT, "email": _EMAIL, "password": _TEXT, "url": _URL, "number": _NUMBER,
}
FIRST_LAYER = {"number": "numbers"}


def layout_id(purpose: str) -> str:
    """Purposes with identical layer data share one built widget tree."""
    return "text" if purpose == "password" else purpose


def first_layer(purpose: str) -> str:
    return FIRST_LAYER.get(purpose, "letters")


def reachable_chars(purpose: str) -> set[str]:
    out: set[str] = set()
    for rows in LAYOUTS[purpose].values():
        for row in rows:
            for k in row:
                if k.insert:
                    out.update(k.insert)
                    if len(k.insert) == 1 and k.insert.isalpha():
                        out.add(k.insert.upper())
                if k.action == "space":
                    out.add(" ")
    return out


def row_units(row: list[Key]) -> float:
    return sum(k.width for k in row)
