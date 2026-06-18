"""Structured router + routing optimization for the differential pair.

The diff pair's topology is regular, so a full maze router is overkill: we route
it with horizontal net rails plus vertical stubs and vias, the way it is drawn
by hand. Interdigitated fingers (even = device A, odd = device B) connect:

    gates  : A -> VINP rail,  B -> VINN rail
    drains : A -> VOUTN rail, B -> VOUTP rail   (the differential outputs)
    sources: all -> VTAIL rail                   (shared tail node)

Gate/drain rails stack ABOVE the active area; the tail rail runs BELOW it.
Everything is pure Python (no Virtuoso); the emitted shapes are real metal/via
rectangles the existing SKILL emitter can build.

Routing parameters the optimizer searches (microns):
    rail_width   metal width of every rail/stub
    rail_pitch   center-to-center spacing of stacked rails
    via_size     square via side

Objective: minimize wirelength + routing metal area, subject to metal DRC
(min width / min spacing / via enclosure) and connectivity. As with the device
geometry, the DRC-clean optimum is analytically known, so it is test-checkable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scipy.optimize import differential_evolution

from .generator import DiffPairConfig, DesignParams, active_bbox
from .geometry import Layout, Rect

# Net names, ordered as the rails stack above the active area.
ABOVE_NETS = ("VINP", "VINN", "VOUTN", "VOUTP")
TAIL_NET = "VTAIL"

METAL = "M2"
VIA = "VIA12"


@dataclass(frozen=True)
class RoutingRules:
    """Metal/via DRC floors (microns). Illustrative, swap in your PDK."""

    min_m_width: float = 0.06
    min_m_spacing: float = 0.07
    min_via: float = 0.04
    min_via_enclosure: float = 0.02   # metal overhang around a via, per side


@dataclass(frozen=True)
class RoutingParams:
    rail_width: float
    rail_pitch: float
    via_size: float

    ORDER = ("rail_width", "rail_pitch", "via_size")

    def to_vector(self) -> list[float]:
        return [getattr(self, k) for k in self.ORDER]

    @classmethod
    def from_vector(cls, x) -> "RoutingParams":
        if len(x) != len(cls.ORDER):
            raise ValueError(f"expected {len(cls.ORDER)} routing params, got {len(x)}")
        return cls(**{k: float(v) for k, v in zip(cls.ORDER, x)})


DEFAULT_ROUTE_BOUNDS = {
    "rail_width": (0.06, 0.30),
    "rail_pitch": (0.13, 0.50),
    "via_size": (0.04, 0.15),
}


def route_bounds_vector(bounds: dict | None = None) -> list[tuple[float, float]]:
    b = bounds or DEFAULT_ROUTE_BOUNDS
    return [b[k] for k in RoutingParams.ORDER]


@dataclass
class RoutingResult:
    rails: list[Rect] = field(default_factory=list)
    stubs: list[Rect] = field(default_factory=list)
    vias: list[Rect] = field(default_factory=list)
    net_fingers: dict = field(default_factory=dict)  # net -> [finger indices]
    wirelength: float = 0.0
    via_count: int = 0
    metal_area: float = 0.0
    top_y: float = 0.0     # highest routing y (for area expansion)
    bot_y: float = 0.0     # lowest routing y


def _finger_x(i: int, p: DesignParams) -> float:
    return i * p.finger_pitch


def route(
    p: DesignParams,
    rp: RoutingParams,
    cfg: DiffPairConfig | None = None,
    rules: RoutingRules | None = None,
) -> RoutingResult:
    """Build the rail/stub/via geometry connecting the diff-pair fingers."""
    cfg = cfg or DiffPairConfig()
    rules = rules or RoutingRules()
    n = 2 * cfg.nf

    ax0, ay0, ax1, ay1 = active_bbox(p, cfg)
    gate_y = p.w_finger + cfg.poly_ext      # gate terminal (poly top)
    drain_y = p.w_finger                     # drain contact (diffusion top)
    source_y = 0.0                           # source contact (diffusion bottom)

    # Net -> connected finger indices.
    net_fingers: dict[str, list[int]] = {
        "VINP": [i for i in range(n) if i % 2 == 0],
        "VINN": [i for i in range(n) if i % 2 == 1],
        "VOUTN": [i for i in range(n) if i % 2 == 0],
        "VOUTP": [i for i in range(n) if i % 2 == 1],
        TAIL_NET: list(range(n)),
    }
    # The y-terminal each net taps off of.
    net_term_y = {
        "VINP": gate_y, "VINN": gate_y,
        "VOUTN": drain_y, "VOUTP": drain_y,
        TAIL_NET: source_y,
    }

    res = RoutingResult(net_fingers=net_fingers)
    clearance = rules.min_m_spacing
    half = rp.rail_width / 2.0

    def add_rail(net: str, y_center: float) -> None:
        idxs = net_fingers[net]
        xs = [_finger_x(i, p) for i in idxs]
        x0 = min(xs) - half
        x1 = max(xs) + half
        res.rails.append(Rect(METAL, "drawing", x0, y_center - half, x1, y_center + half))
        res.wirelength += (x1 - x0)
        res.metal_area += (x1 - x0) * rp.rail_width
        res.top_y = max(res.top_y, y_center + half)
        res.bot_y = min(res.bot_y, y_center - half)
        # Vertical stub + via from each finger terminal to this rail.
        ty = net_term_y[net]
        for i in idxs:
            x = _finger_x(i, p)
            y_lo, y_hi = sorted((ty, y_center))
            res.stubs.append(
                Rect(METAL, "drawing", x - half, y_lo, x + half, y_hi)
            )
            res.wirelength += (y_hi - y_lo)
            res.metal_area += rp.rail_width * (y_hi - y_lo)
            v = rp.via_size / 2.0
            res.vias.append(
                Rect(VIA, "drawing", x - v, y_center - v, x + v, y_center + v)
            )
            res.via_count += 1

    # Rails above the active area, stacked by rail_pitch.
    base = ay1 + clearance + half
    for k, net in enumerate(ABOVE_NETS):
        add_rail(net, base + k * rp.rail_pitch)

    # Tail rail below the active area.
    add_rail(TAIL_NET, ay0 - clearance - half)

    return res


def routed_layout(
    p: DesignParams,
    rp: RoutingParams,
    cfg: DiffPairConfig | None = None,
    rules: RoutingRules | None = None,
) -> Layout:
    """Device layout (from generator) plus routing, as one Layout."""
    from .generator import generate_layout

    cfg = cfg or DiffPairConfig()
    lay = generate_layout(p, cfg)
    r = route(p, rp, cfg, rules)
    for rect in (*r.rails, *r.stubs, *r.vias):
        lay.add(rect)
    return lay


# --------------------------------------------------------------------------
# DRC + objective
# --------------------------------------------------------------------------
# Tolerance so a design sitting *exactly* on a DRC floor isn't flagged by
# floating-point rounding (e.g. 0.15 - 0.08 = 0.06999999... vs a 0.07 floor).
_DRC_EPS = 1e-9


def routing_violations(rp: RoutingParams, rules: RoutingRules | None = None) -> list[str]:
    """Metal/via DRC checks expressible as inequalities on the routing params."""
    rules = rules or RoutingRules()
    v: list[str] = []
    if rp.rail_width < rules.min_m_width - _DRC_EPS:
        v.append(f"rail_width: {rp.rail_width:.4g} < min {rules.min_m_width}")
    if rp.via_size < rules.min_via - _DRC_EPS:
        v.append(f"via_size: {rp.via_size:.4g} < min {rules.min_via}")
    # Adjacent rails must not short: gap = pitch - width >= min spacing.
    gap = rp.rail_pitch - rp.rail_width
    if gap < rules.min_m_spacing - _DRC_EPS:
        v.append(f"rail_spacing: {gap:.4g} < min {rules.min_m_spacing}")
    # Metal must enclose the via on all sides.
    need = rp.via_size + 2 * rules.min_via_enclosure
    if rp.rail_width < need - _DRC_EPS:
        v.append(f"via_enclosure: rail_width {rp.rail_width:.4g} < via+2*enc {need:.4g}")
    return v


def connectivity_ok(res: RoutingResult, cfg: DiffPairConfig | None = None) -> bool:
    """Every finger reaches a gate, a drain, and the tail net."""
    cfg = cfg or DiffPairConfig()
    n = 2 * cfg.nf
    gates = sorted(res.net_fingers["VINP"] + res.net_fingers["VINN"])
    drains = sorted(res.net_fingers["VOUTN"] + res.net_fingers["VOUTP"])
    return (
        gates == list(range(n))
        and drains == list(range(n))
        and res.net_fingers[TAIL_NET] == list(range(n))
    )


ROUTE_PENALTY = 1.0e3
AREA_WEIGHT = 5.0      # weight on routing metal area within the objective
# Feasibility back-off: the penalty pushes against each floor *plus* this
# margin, so a soft-penalized optimum lands strictly inside the DRC-clean
# region instead of marginally (sub-grid) outside it.
ROUTE_MARGIN = 5.0e-4


def _route_shortfall(rp: RoutingParams, rules: RoutingRules, margin: float) -> float:
    """Total constraint shortfall against floors + margin (>=0)."""
    m = margin
    sf = 0.0
    sf += max(0.0, (rules.min_m_width + m) - rp.rail_width)
    sf += max(0.0, (rules.min_via + m) - rp.via_size)
    sf += max(0.0, (rules.min_m_spacing + m) - (rp.rail_pitch - rp.rail_width))
    need = rp.via_size + 2 * rules.min_via_enclosure
    sf += max(0.0, (need + m) - rp.rail_width)
    return sf


def routing_objective(
    rp: RoutingParams,
    p: DesignParams,
    cfg: DiffPairConfig | None = None,
    rules: RoutingRules | None = None,
) -> float:
    """Minimize wirelength + metal area, penalize DRC violations."""
    cfg = cfg or DiffPairConfig()
    rules = rules or RoutingRules()
    res = route(p, rp, cfg, rules)
    shortfall = _route_shortfall(rp, rules, ROUTE_MARGIN)
    return res.wirelength + AREA_WEIGHT * res.metal_area + ROUTE_PENALTY * shortfall


@dataclass
class RouteOptResult:
    params: RoutingParams
    wirelength: float
    metal_area: float
    via_count: int
    violations: list[str]
    objective: float

    @property
    def is_clean(self) -> bool:
        return not self.violations


def optimize_routing(
    p: DesignParams,
    cfg: DiffPairConfig | None = None,
    rules: RoutingRules | None = None,
    bounds: dict | None = None,
    seed: int = 0,
    maxiter: int = 80,
) -> RouteOptResult:
    """Find DRC-clean routing params that minimize wirelength + metal area
    for a fixed device geometry *p*."""
    cfg = cfg or DiffPairConfig()
    rules = rules or RoutingRules()
    bnds = route_bounds_vector(bounds or DEFAULT_ROUTE_BOUNDS)

    def obj(x) -> float:
        try:
            rp = RoutingParams.from_vector(x)
            return routing_objective(rp, p, cfg, rules)
        except Exception:
            return 1.0e9

    de = differential_evolution(
        obj, bounds=bnds, seed=seed, maxiter=maxiter, polish=True,
        tol=1e-8, updating="deferred",
    )
    rp = RoutingParams.from_vector(de.x)
    res = route(p, rp, cfg, rules)
    return RouteOptResult(
        params=rp,
        wirelength=res.wirelength,
        metal_area=res.metal_area,
        via_count=res.via_count,
        violations=routing_violations(rp, rules),
        objective=de.fun,
    )
