"""Month | Week (| Agenda) segmented switcher shared by all view headers (US-39/40).

To add a view (US-40): append a ViewDef to VIEW_DEFS and its name to settings_store.VIEWS.
The view screen must implement `anchor_date() -> date` and `show_date(d: date)` so switching
keeps the period aligned (see MainWindow.show_view). No other code needs to change.
"""
from __future__ import annotations

from dataclasses import dataclass

from gi.repository import Gtk


@dataclass(frozen=True)
class ViewDef:
    name: str        # value of the default_view setting
    label: str       # button text
    screen: str      # Navigator screen name


VIEW_DEFS: list[ViewDef] = [
    ViewDef("month", "Month", "calendar"),
    ViewDef("week", "Week", "week"),
]


def screen_for(view: str) -> str:
    for v in VIEW_DEFS:
        if v.name == view:
            return v.screen
    return "calendar"


def view_for_screen(screen: str | None) -> str | None:
    for v in VIEW_DEFS:
        if v.screen == screen:
            return v.name
    return None


class ViewSwitcher(Gtk.Box):
    """Put one in each view's header start_slot: `ViewSwitcher("week")`."""

    def __init__(self, current: str):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                         css_classes=["view-switcher"], valign=Gtk.Align.CENTER)
        self.current = current
        self.buttons: dict[str, Gtk.Button] = {}
        for v in VIEW_DEFS:
            b = Gtk.Button(label=v.label, css_classes=["nav-button", "view-button"],
                           focus_on_click=False)
            if v.name == current:
                b.add_css_class("selected")
            b.connect("clicked", self._on_clicked, v.name)
            self.buttons[v.name] = b
            self.append(b)

    def _on_clicked(self, _btn, view: str) -> None:
        if view == self.current:
            return
        root = self.get_root()
        if root is not None and hasattr(root, "show_view"):
            root.show_view(view, reason="switcher")

    def set_current(self, view: str) -> None:
        self.current = view
        for name, b in self.buttons.items():
            if (name == view) != b.has_css_class("selected"):
                (b.add_css_class if name == view else b.remove_css_class)("selected")
