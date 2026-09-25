"""One CSS provider with a class per calendar (.cal-N), regenerated when colours change."""
from __future__ import annotations

from gi.repository import Gtk

from calpi.data.formatting import contrast_text, valid_color
from calpi.data.models import Calendar
from calpi.widgets.util import add_style_provider


def load_css(provider: Gtk.CssProvider, css: str) -> None:
    """Version-tolerant CssProvider.load_from_* (signature changed across GTK versions)."""
    fn = getattr(provider, "load_from_string", None)
    if fn is not None:
        fn(css)
        return
    try:
        provider.load_from_data(css.encode())
    except TypeError:
        provider.load_from_data(css, -1)


def swatch_css() -> str:
    """One rule per palette colour: `.swatch-N` (US-26; palette.py stays the single source)."""
    from calpi.data.palette import PALETTE
    return "\n".join(f".swatch-{i} {{ background-image: none; background-color: {c}; "
                     f"color: {contrast_text(c)}; }}" for i, (c, _n) in enumerate(PALETTE))


class CalendarColors:
    def __init__(self):
        self._swatches = Gtk.CssProvider()
        load_css(self._swatches, swatch_css())
        add_style_provider(self._swatches, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._provider = Gtk.CssProvider()
        add_style_provider(self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._classes: dict[str, str] = {}
        self.hash: tuple = ()

    def update(self, calendars: list[Calendar]) -> bool:
        """Returns True if the CSS was regenerated."""
        key = tuple(sorted((c.id, valid_color(c.color)) for c in calendars))
        if key == self.hash:
            return False
        self.hash = key
        self._classes = {}
        css = []
        for i, (cid, color) in enumerate(key):
            cls = f"cal-{i}"
            self._classes[cid] = cls
            css.append(f".bar.{cls} {{ background-color: {color}; color: {contrast_text(color)}; }}")
            css.append(f".line.{cls} .dot {{ background-color: {color}; }}")
            css.append(f".cal-dot.{cls} {{ background-color: {color}; }}")     # US-26 settings dots
        load_css(self._provider, "\n".join(css))
        return True

    def css_class(self, calendar_id: str) -> str:
        return self._classes.get(calendar_id, "cal-unknown")
