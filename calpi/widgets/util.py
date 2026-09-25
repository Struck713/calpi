from gi.repository import Gtk


def set_text_if_changed(label: Gtk.Label, text: str) -> None:
    if label.get_text() != text:
        label.set_text(text)


def set_visible_if_changed(widget: Gtk.Widget, visible: bool) -> None:
    if widget.get_visible() != visible:
        widget.set_visible(visible)


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
