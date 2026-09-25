import struct
from pathlib import Path

from calpi.data import guides

ASSET = Path(__file__).resolve().parent.parent / "calpi" / "assets" / guides.QR_ASSET


def test_guide_data():
    assert 1 <= len(guides.steps()) <= 6
    texts = [h for h, _ in guides.ICLOUD_APP_PASSWORD_GUIDE]
    for h, ps in guides.ICLOUD_APP_PASSWORD_GUIDE:
        texts += ps
    assert all(t.strip() for t in texts)
    assert not any("TODO" in t or "{" in t for t in texts)
    assert "account.apple.com" in " ".join(texts)
    assert guides.GUIDE_SOURCE["checked"]


def test_qr_asset_is_png_of_expected_size():
    d = ASSET.read_bytes()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", d[16:24])
    assert w == h and 320 <= w <= 400


def test_open_guide_pushes_page():
    import os
    if not os.environ.get("CALPI_GTK_TESTS"):
        return
    from calpi.widgets import icloud_guide

    class Ctx:
        def push_page(self, w, title):
            self.got = (w, title)
    c = Ctx()
    icloud_guide.open_guide(c)
    assert c.got[1] == "App-specific passwords"
