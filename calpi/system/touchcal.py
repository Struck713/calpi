"""Pure helpers for touchscreen bring-up (US-34): targets, offsets, calibration fit, udev rule.

No GTK here so it is unit-testable and importable anywhere.

libinput's LIBINPUT_CALIBRATION_MATRIX is six numbers "a b c d e f" mapping normalised (0..1)
device coordinates: x' = a*x + b*y + c, y' = d*x + e*y + f.
"""
from __future__ import annotations

import math
import re
from typing import Iterable, Sequence

Point = tuple[float, float]
Matrix = tuple[float, float, float, float, float, float]

IDENTITY: Matrix = (1, 0, 0, 0, 1, 0)
ROTATE_180: Matrix = (-1, 0, 1, 0, -1, 1)
TOLERANCE_PX = 12.0                     # US-34 acceptance criterion 4
TARGET_INSET = 60                       # target centre distance from the edges (px)


def targets(width: int, height: int, inset: int = TARGET_INSET) -> list[Point]:
    """The 9 targets: corners, edge midpoints, centre (row-major)."""
    xs = (inset, width / 2, width - inset)
    ys = (inset, height / 2, height - inset)
    return [(float(x), float(y)) for y in ys for x in xs]


def nearest_target(p: Point, tgts: Sequence[Point]) -> Point:
    return min(tgts, key=lambda t: math.hypot(p[0] - t[0], p[1] - t[1]))


def offset(p: Point, tgts: Sequence[Point]) -> tuple[float, float, float]:
    """(dx, dy, distance) from the nearest target to touch p."""
    t = nearest_target(p, tgts)
    dx, dy = p[0] - t[0], p[1] - t[1]
    return dx, dy, math.hypot(dx, dy)


def summarize(dists: Iterable[float], tolerance: float = TOLERANCE_PX) -> dict:
    d = list(dists)
    if not d:
        return {"n": 0, "max": 0.0, "mean": 0.0, "ok": False}
    return {"n": len(d), "max": max(d), "mean": sum(d) / len(d), "ok": max(d) <= tolerance}


def _fit_axis(m: Sequence[float], t: Sequence[float]) -> tuple[float, float]:
    """Least squares t = s*m + o."""
    n = len(m)
    mm, mt = sum(m) / n, sum(t) / n
    var = sum((x - mm) ** 2 for x in m)
    if var < 1e-9:
        return 1.0, mt - mm
    s = sum((x - mm) * (y - mt) for x, y in zip(m, t)) / var
    return s, mt - s * mm


def fit_calibration(points: Sequence[tuple[Point, Point]], width: int, height: int) -> Matrix:
    """points: [(target(tx, ty), measured(mx, my)), ...] in pixels.

    Returns the libinput matrix, in normalised units, that maps measured -> target. It is
    RELATIVE to the matrix in effect when measuring: compose with `compose(new, current)`.
    """
    if len(points) < 2:
        raise ValueError("need at least 2 points")
    sx, ox = _fit_axis([m[0] for _t, m in points], [t[0] for t, _m in points])
    sy, oy = _fit_axis([m[1] for _t, m in points], [t[1] for t, _m in points])
    return (sx, 0.0, ox / width, 0.0, sy, oy / height)


def compose(new: Matrix, current: Matrix) -> Matrix:
    """Matrix equivalent to applying `current` first and then `new`."""
    a, b, c, d, e, f = new
    A, B, C, D, E, F = current
    return (a * A + b * D, a * B + b * E, a * C + b * F + c,
            d * A + e * D, d * B + e * E, d * C + e * F + f)


def apply(matrix: Matrix, p: Point, width: int, height: int) -> Point:
    a, b, c, d, e, f = matrix
    x, y = p[0] / width, p[1] / height
    return ((a * x + b * y + c) * width, (d * x + e * y + f) * height)


def format_matrix(m: Sequence[float]) -> str:
    return " ".join(f"{v:.6g}" for v in m)


_MATRIX_RE = re.compile(r"^\s*(-?\d+(\.\d+)?\s+){5}-?\d+(\.\d+)?\s*$")


def valid_matrix_string(s: str) -> bool:
    return bool(_MATRIX_RE.match(s or ""))


def udev_rule(name: str, matrix: str) -> str:
    """The /etc/udev/rules.d/99-calpi-touch.rules line (US-34 D2)."""
    if '"' in name or "\n" in name:
        raise ValueError("bad device name")
    if not valid_matrix_string(matrix):
        raise ValueError("bad matrix")
    return (f'ACTION=="add|change", KERNEL=="event*", ATTRS{{name}}=="{name}", '
            f'ENV{{LIBINPUT_CALIBRATION_MATRIX}}="{" ".join(matrix.split())}"')
