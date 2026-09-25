from gi.repository import Gtk


def set_text_if_changed(label: Gtk.Label, text: str) -> None:
    if label.get_text() != text:
        label.set_text(text)


def set_visible_if_changed(widget: Gtk.Widget, visible: bool) -> None:
    if widget.get_visible() != visible:
        widget.set_visible(visible)


def pin_grid_columns(grid: Gtk.Grid, n: int) -> None:
    """Give columns 1..n-1 a permanent zero-size child (column 0 is assumed occupied).

    GTK 4.8 (Bookworm) gives an empty column of a homogeneous grid zero width, so a day
    without events would collapse and shift every other day sideways.
    """
    for col in range(1, n):
        grid.attach(Gtk.Box(can_target=False), col, 0, 1, 1)


def set_class(widget: Gtk.Widget, css_class: str, on: bool) -> None:
    if on and not widget.has_css_class(css_class):
        widget.add_css_class(css_class)
    elif not on and widget.has_css_class(css_class):
        widget.remove_css_class(css_class)


def add_style_provider(provider, priority) -> None:
    """Version-tolerant wrapper for adding a display-wide CSS provider."""
    from gi.repository import Gdk
    display = Gdk.Display.get_default()
    fn = getattr(Gtk, "style_context_add_provider_for_display", None)
    if fn is not None:
        fn(display, provider, priority)
    else:
        Gtk.StyleContext.add_provider_for_display(display, provider, priority)


def exempt_scrollbars(sw: Gtk.ScrolledWindow) -> Gtk.ScrolledWindow:
    """Scrollbars are thin by design; keep them out of the touch-target checker (US-11)."""
    sw.get_vscrollbar().add_css_class("target-exempt")
    sw.get_hscrollbar().add_css_class("target-exempt")
    return sw


def is_refresh_key(name: str, state) -> bool:
    """F5 or Ctrl+R (US-19)."""
    from gi.repository import Gdk
    return name == "F5" or (name.lower() == "r" and bool(state and state & Gdk.ModifierType.CONTROL_MASK))


def trigger_refresh(widget) -> None:
    app = widget.get_root().get_application() if widget.get_root() is not None else None
    if app is not None and hasattr(app, "trigger_manual_refresh"):
        app.trigger_manual_refresh()
