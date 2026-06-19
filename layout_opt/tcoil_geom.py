"""T-coil physical geometry: a symmetric square-spiral inductor.

Turns the abstract (L, k, Cb) of `tcoil.py` into a real **layout shape** and,
conversely, extracts L and k *from* the geometry — so the drawn coil determines
the electrical behavior.

Geometry parameters (microns):
  turns    n     number of turns
  width    w     metal trace width
  spacing  s     gap between adjacent turns
  inner    d_in  inner opening (innermost side length)

Derived:
  outer side  d_out = d_in + 2*n*(w+s)
  inductance  L via the modified-Wheeler square-spiral formula
  coupling    k of the two center-tapped halves (heuristic, rises with turns)

To drive the normalized electrical model (`tcoil.py`, R=C_L=1), a physical coil
L (Henries) at a node (R ohms, C_L farads) maps to normalized L = L / (R^2 C_L).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .tcoil import TCoilParams, bw_extension as _bw_ext, peaking_db as _peak

_MU0 = 4.0e-7 * math.pi          # H/m
# Modified-Wheeler coefficients for a SQUARE spiral.
_K1, _K2 = 2.34, 2.75


@dataclass(frozen=True)
class TCoilGeometry:
    turns: float        # n
    width: float        # w (um)
    spacing: float      # s (um)
    inner: float        # d_in (um)

    def d_out(self) -> float:
        return self.inner + 2.0 * self.turns * (self.width + self.spacing)


def spiral_points(g: TCoilGeometry) -> list[tuple[float, float]]:
    """Centerline polyline of an inward square spiral, centered on the origin (um)."""
    pitch = g.width + g.spacing
    d_out = g.d_out()
    # Inward square spiral: directions cycle R, D, L, U; each pair of segments
    # shrinks by one pitch.
    dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    lengths: list[float] = []
    cur = d_out
    nseg = max(int(round(4 * g.turns)), 2)
    for i in range(nseg):
        lengths.append(cur)
        if i % 2 == 1:               # shrink after every second segment
            cur = max(cur - pitch, pitch)
    x = y = 0.0
    pts = [(x, y)]
    for i, seglen in enumerate(lengths):
        dx, dy = dirs[i % 4]
        x += dx * seglen
        y += dy * seglen
        pts.append((x, y))
    # center on origin
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    return [(p[0] - cx, p[1] - cy) for p in pts]


def wire_length_um(g: TCoilGeometry) -> float:
    pts = spiral_points(g)
    return sum(abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1])
               for i in range(len(pts) - 1))


@dataclass
class TCoilExtract:
    L_nH: float          # full-spiral inductance
    k: float             # coupling of the two halves
    d_out_um: float
    wire_um: float
    area_um2: float


def extract(g: TCoilGeometry) -> TCoilExtract:
    """Extract L (nH) and coupling k from the geometry."""
    d_out = g.d_out() * 1e-6                       # m
    d_in = g.inner * 1e-6
    d_avg = (d_out + d_in) / 2.0
    rho = (d_out - d_in) / (d_out + d_in)          # fill ratio
    L = _K1 * _MU0 * (g.turns ** 2) * d_avg / (1.0 + _K2 * rho)   # Henries
    # Heuristic coupling of the two center-tapped halves: tighter winding (more
    # turns, smaller fill ratio) interleaves better -> higher k, capped < 1.
    k = min(0.92, 0.55 + 0.12 * g.turns - 0.25 * rho)
    k = max(0.1, k)
    return TCoilExtract(
        L_nH=L * 1e9,
        k=round(k, 4),
        d_out_um=round(g.d_out(), 2),
        wire_um=round(wire_length_um(g), 2),
        area_um2=round(g.d_out() ** 2, 1),
    )


def to_normalized(L_nH: float, k: float, *, r_ohm: float, cl_ff: float,
                  cb_norm: float) -> TCoilParams:
    """Map a physical coil at a node (R, C_L) to the normalized model params.

    normalized L = L_phys / (R^2 * C_L). Cb is taken already-normalized.
    """
    l_phys = L_nH * 1e-9
    cl = cl_ff * 1e-15
    norm_l = l_phys / (r_ohm ** 2 * cl)
    return TCoilParams(L=norm_l, k=k, Cb=cb_norm)


def evaluate_geometry(g: TCoilGeometry, *, r_ohm: float = 50.0, cl_ff: float = 80.0,
                      cb_norm: float = 0.14) -> dict:
    """Full geometry -> shape + extracted L/k + normalized response."""
    ex = extract(g)
    p = to_normalized(ex.L_nH, ex.k, r_ohm=r_ohm, cl_ff=cl_ff, cb_norm=cb_norm)
    return {
        "extract": ex,
        "norm_L": round(p.L, 4),
        "params": p,
        "bw_extension": round(_bw_ext(p), 3),
        "peaking_db": round(_peak(p), 3),
    }
