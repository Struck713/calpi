import pytest

from calpi.data.keyboard_layouts import (LAYOUTS, MAX_ROW_UNITS, PURPOSES, reachable_chars,
                                          row_units)

ASCII = {chr(c) for c in range(0x20, 0x7F)}


@pytest.mark.parametrize("purpose", ["password", "text", "email", "url"])
def test_full_ascii_reachable(purpose):
    assert ASCII <= reachable_chars(purpose)


def test_all_inserts_ascii_and_rows_fit():
    for purpose, layers in LAYOUTS.items():
        for name, rows in layers.items():
            for row in rows:
                assert row_units(row) <= MAX_ROW_UNITS, (purpose, name, row_units(row))
                for k in row:
                    assert k.insert is None or k.insert.isascii()


@pytest.mark.parametrize("purpose", [p for p in PURPOSES if p != "number"])
def test_layers_have_essentials(purpose):
    for name, rows in LAYOUTS[purpose].items():
        actions = {k.action for r in rows for k in r}
        assert "backspace" in actions and "hide" in actions and "done" in actions
        assert any(a and a.startswith("layer:") for a in actions)


def test_number_is_digits_only():
    chars = reachable_chars("number")
    assert set("0123456789") <= chars and not (chars & set("abcdefghijklmnopqrstuvwxyz"))
