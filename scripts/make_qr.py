#!/usr/bin/env python3
"""Render a QR code as a grayscale PNG (no Pillow). Dev-machine only.

usage: make_qr.py OUT.png URL [module_px=10] [border=2]
Uses the `qrcode` package (pip install qrcode) for the matrix.
"""
import struct
import sys
import zlib


def main() -> None:
    out, url = sys.argv[1], sys.argv[2]
    scale = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    border = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(url)
    qr.make(fit=True)
    m = qr.get_matrix()
    n = len(m) + 2 * border
    rows = []
    for y in range(n):
        line = bytearray()
        for x in range(n):
            my, mx = y - border, x - border
            dark = 0 <= my < len(m) and 0 <= mx < len(m) and m[my][mx]
            line += (b"\x00" if dark else b"\xff") * scale
        rows += [b"\x00" + bytes(line)] * scale
    size = n * scale

    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
    with open(out, "wb") as f:
        f.write(png)
    print(f"{out}: {size}x{size}px, {len(m)} modules")


if __name__ == "__main__":
    main()
