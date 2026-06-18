"""Parameterized differential-pair layout generator.

Models a textbook analog cell: two transistors (A / B) laid out as
interdigitated vertical fingers, surrounded by a guard ring.

    guard ring (M1 frame)
    +-------------------------------+
    |   A  B  A  B  A  B  A  B       |   <- 2*nf interdigitated poly fingers
    |  |OD diffusion under fingers|  |
    +-------------------------------+

The generator is a *pure function* of (DesignParams, DiffPairConfig): same
inputs -> same geometry. No Virtuoso, no global state. This is exactly the
"layer 1 / layer 2" logic that can be unit-tested offline; the only deferred
step is *executing* the emitted SKILL inside Virtuoso (see skill.py).
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Layout, Rect


@dataclass(frozen=True)
class PDKRules:
    """Minimum geometric rules, in microns. Stand-ins for a real PDK DRC deck.

    Each is a hard lower bound; going below it is a DRC violation. These values
    are illustrative (loosely 28nm-ish) - swap in your PDK's numbers.
    """

    min_l: float = 0.03            # min poly (gate) length
    min_w: float = 0.10            # min finger width (diffusion height)
    min_poly_pitch: float = 0.18   # min poly center-to-center spacing
    min_gr_gap: float = 0.20       # min gap from active area to guard ring
    min_gr_width: float = 0.05     # min guard-ring metal width


@dataclass(frozen=True)
class DiffPairConfig:
    """Fixed (non-optimized) configuration of the differential pair."""

    nf: int = 4                    # fingers per device; total fingers = 2*nf
    w_min_total: float = 2.0       # drive-strength spec: nf * w_finger >= this
    poly_ext: float = 0.05         # poly extension beyond diffusion (per side)
    diff_ext: float = 0.06         # diffusion extension beyond outer poly (per side)
    layer_poly: str = "PO"
    layer_diff: str = "OD"
    layer_gr: str = "M1"

    def __post_init__(self) -> None:
        if self.nf < 1:
            raise ValueError("nf must be >= 1")


@dataclass(frozen=True)
class DesignParams:
    """The continuous parameters the optimizer searches over (microns)."""

    w_finger: float        # finger width  (diffusion height)
    l: float               # gate length
    finger_pitch: float    # poly center-to-center spacing
    guard_gap: float       # gap from active area to guard ring
    gr_width: float        # guard-ring metal width

    # Stable order used to pack/unpack to/from the optimizer's vector x.
    ORDER = ("w_finger", "l", "finger_pitch", "guard_gap", "gr_width")

    def to_vector(self) -> list[float]:
        return [getattr(self, k) for k in self.ORDER]

    @classmethod
    def from_vector(cls, x) -> "DesignParams":
        if len(x) != len(cls.ORDER):
            raise ValueError(f"expected {len(cls.ORDER)} params, got {len(x)}")
        return cls(**{k: float(v) for k, v in zip(cls.ORDER, x)})


# Default search bounds (lower, upper) per parameter, microns.
DEFAULT_BOUNDS = {
    "w_finger": (0.10, 2.00),
    "l": (0.03, 0.30),
    "finger_pitch": (0.18, 0.60),
    "guard_gap": (0.20, 1.00),
    "gr_width": (0.05, 0.30),
}


def bounds_vector(bounds: dict | None = None) -> list[tuple[float, float]]:
    """Return bounds as a list aligned with DesignParams.ORDER."""
    b = bounds or DEFAULT_BOUNDS
    return [b[k] for k in DesignParams.ORDER]


def active_bbox(p: DesignParams, cfg: DiffPairConfig) -> tuple[float, float, float, float]:
    """Bounding box of the active region (diffusion + poly), before guard ring."""
    n = 2 * cfg.nf
    last_center = (n - 1) * p.finger_pitch
    x0 = -p.l / 2.0 - cfg.diff_ext
    x1 = last_center + p.l / 2.0 + cfg.diff_ext
    y0 = -cfg.poly_ext
    y1 = p.w_finger + cfg.poly_ext
    return (x0, y0, x1, y1)


def generate_layout(p: DesignParams, cfg: DiffPairConfig | None = None) -> Layout:
    """Build the differential-pair Layout from parameters. Pure function."""
    cfg = cfg or DiffPairConfig()
    n = 2 * cfg.nf
    lay = Layout(name=f"diffpair_nf{cfg.nf}")

    # 1. Diffusion (one rect spanning all fingers).
    ax0, ay0, ax1, ay1 = active_bbox(p, cfg)
    lay.add(Rect(cfg.layer_diff, "drawing", ax0, 0.0, ax1, p.w_finger))

    # 2. Poly fingers, interdigitated A B A B ... (device assignment is encoded
    #    in net/label downstream; geometry is identical per finger here).
    for i in range(n):
        xc = i * p.finger_pitch
        lay.add(
            Rect(
                cfg.layer_poly,
                "drawing",
                xc - p.l / 2.0,
                -cfg.poly_ext,
                xc + p.l / 2.0,
                p.w_finger + cfg.poly_ext,
            )
        )

    # 3. Guard ring as 4 metal rects framing the active area at guard_gap.
    ix0, iy0 = ax0 - p.guard_gap, ay0 - p.guard_gap      # inner edge of ring
    ix1, iy1 = ax1 + p.guard_gap, ay1 + p.guard_gap
    ox0, oy0 = ix0 - p.gr_width, iy0 - p.gr_width         # outer edge of ring
    ox1, oy1 = ix1 + p.gr_width, iy1 + p.gr_width
    gr = cfg.layer_gr
    lay.add(Rect(gr, "drawing", ox0, oy0, ox1, iy0))      # bottom bar
    lay.add(Rect(gr, "drawing", ox0, iy1, ox1, oy1))      # top bar
    lay.add(Rect(gr, "drawing", ox0, iy0, ix0, iy1))      # left bar
    lay.add(Rect(gr, "drawing", ix1, iy0, ox1, iy1))      # right bar

    return lay
