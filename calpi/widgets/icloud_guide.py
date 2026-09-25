"""iCloud app-specific password guide (US-33). Opened as a sub-page via ctx.push_page."""
from __future__ import annotations

import logging
from pathlib import Path

from gi.repository import Gdk, Gtk

from calpi.data import guides

log = logging.getLogger(__name__)

AVAILABLE = True
_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_texture = None


def _qr_texture():
    global _texture
    if _texture is None:
        try:
            _texture = Gdk.Texture.new_from_filename(str(_ASSETS / guides.QR_ASSET))
        except Exception:
            log.exception("could not load QR asset")
            return None
    return _texture


def open_guide(ctx) -> None:
    ctx.push_page(IcloudGuidePage(ctx).widget, "App-specific passwords")


class IcloudGuidePage:
    def __init__(self, ctx=None):
        self.ctx = ctx
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=64,
                        css_classes=["guide-page"])
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, hexpand=True,
                       valign=Gtk.Align.START)
        for heading, paras in guides.ICLOUD_APP_PASSWORD_GUIDE:
            text.append(Gtk.Label(label=heading, xalign=0, wrap=True,
                                  css_classes=["guide-heading"]))
            numbered = heading == guides.STEPS_HEADING
            for i, p in enumerate(paras, 1):
                if numbered:
                    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16,
                                  valign=Gtk.Align.START)
                    row.append(Gtk.Label(label=str(i), valign=Gtk.Align.START,
                                         css_classes=["guide-step-number"]))
                    row.append(Gtk.Label(label=p, xalign=0, wrap=True, hexpand=True,
                                         max_width_chars=60, css_classes=["guide-body"]))
                    text.append(row)
                else:
                    text.append(Gtk.Label(label=p, xalign=0, wrap=True, max_width_chars=60,
                                          css_classes=["guide-body"]))
        qr = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.START)
        tex = _qr_texture()
        if tex is not None:
            pic = Gtk.Picture.new_for_paintable(tex)
            pic.set_can_shrink(False)
            pic.set_halign(Gtk.Align.CENTER)
            qr.append(pic)
        qr.append(Gtk.Label(label=guides.QR_CAPTION, wrap=True, css_classes=["guide-caption"]))
        outer.append(text)
        outer.append(qr)
        self.widget = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.widget.set_child(outer)
