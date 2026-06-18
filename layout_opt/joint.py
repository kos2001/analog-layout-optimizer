"""Joint device + routing co-optimization.

Earlier steps optimized the device geometry and the routing separately. But the
*real* cell area includes the interconnect: rails stack above/below the active
area, and the rail x-span follows the finger pitch. Optimizing the device alone
therefore underestimates the true area.

Here both are searched together over one 8-D vector:

    device  (5) : w_finger, l, finger_pitch, guard_gap, gr_width
    routing (3) : rail_width, rail_pitch, via_size

Objective: minimize the TOTAL routed-cell bounding-box area, subject to device
DRC + drive-strength spec, routing DRC, and connectivity (structural). Pure
Python; no Virtuoso. The constrained optimum is at the floors, so it is
test-checkable.
"""

from __future__ import annotations

from dataclasses import dataclass

from scipy.optimize import differential_evolution

from .evaluate import PENALTY_WEIGHT, evaluate
from .generator import (
    DEFAULT_BOUNDS,
    DesignParams,
    DiffPairConfig,
    PDKRules,
    bounds_vector,
)
from .routing import (
    DEFAULT_ROUTE_BOUNDS,
    ROUTE_MARGIN,
    ROUTE_PENALTY,
    RoutingParams,
    RoutingRules,
    _route_shortfall,
    connectivity_ok,
    route,
    routed_layout,
    route_bounds_vector,
    routing_violations,
)

_NDEV = len(DesignParams.ORDER)


@dataclass
class JointResult:
    device: DesignParams
    routing: RoutingParams
    total_area: float          # full routed-cell bbox area
    device_area: float         # device-only bbox area (for comparison)
    wirelength: float
    device_violations: list[str]
    routing_violations: list[str]
    drive_spec_met: bool
    connected: bool
    n_evals: int

    @property
    def is_clean(self) -> bool:
        return (
            not self.device_violations
            and not self.routing_violations
            and self.drive_spec_met
            and self.connected
        )


def _split(x):
    return DesignParams.from_vector(x[:_NDEV]), RoutingParams.from_vector(x[_NDEV:])


def joint_bounds() -> list[tuple[float, float]]:
    return bounds_vector(DEFAULT_BOUNDS) + route_bounds_vector(DEFAULT_ROUTE_BOUNDS)


def joint_objective(
    x,
    cfg: DiffPairConfig,
    rules: PDKRules,
    rrules: RoutingRules,
) -> float:
    try:
        p, rp = _split(x)
    except Exception:
        return 1.0e9
    ev = evaluate(p, cfg, rules)                 # device area + DRC + drive spec
    total_area = routed_layout(p, rp, cfg, rrules).bbox_area()
    route_sf = _route_shortfall(rp, rrules, ROUTE_MARGIN)
    # Use the FULL cell area as the area term; keep device DRC/spec penalty.
    return total_area + ev.penalty + ROUTE_PENALTY * route_sf


def optimize_joint(
    cfg: DiffPairConfig | None = None,
    rules: PDKRules | None = None,
    rrules: RoutingRules | None = None,
    seed: int = 0,
    maxiter: int = 150,
) -> JointResult:
    cfg = cfg or DiffPairConfig()
    rules = rules or PDKRules()
    rrules = rrules or RoutingRules()
    bnds = joint_bounds()

    res = differential_evolution(
        lambda x: joint_objective(x, cfg, rules, rrules),
        bounds=bnds, seed=seed, maxiter=maxiter, polish=True,
        tol=1e-9, updating="deferred",
    )
    return _result_from_x(res.x, cfg, rules, rrules, int(res.nfev))


def _result_from_x(x, cfg, rules, rrules, nfev) -> JointResult:
    p, rp = _split(x)
    routed = route(p, rp, cfg, rrules)
    ev = evaluate(p, cfg, rules)
    return JointResult(
        device=p,
        routing=rp,
        total_area=routed_layout(p, rp, cfg, rrules).bbox_area(),
        device_area=ev.area,
        wirelength=routed.wirelength,
        device_violations=ev.violations,
        routing_violations=routing_violations(rp, rrules),
        drive_spec_met=(cfg.nf * p.w_finger) >= cfg.w_min_total - 1e-9,
        connected=connectivity_ok(routed, cfg),
        n_evals=int(nfev),
    )


def optimize_joint_trajectory(
    cfg: DiffPairConfig | None = None,
    rules: PDKRules | None = None,
    rrules: RoutingRules | None = None,
    seed: int = 0,
    maxiter: int = 80,
) -> tuple[JointResult, list[tuple[DesignParams, RoutingParams]]]:
    """Joint optimization that also returns the best (device, routing) per
    generation, for the UI to animate the full cell shrinking."""
    cfg = cfg or DiffPairConfig()
    rules = rules or PDKRules()
    rrules = rrules or RoutingRules()
    bnds = joint_bounds()

    frames: list[tuple[DesignParams, RoutingParams]] = []

    def _cb(xk, convergence=None):
        frames.append(_split(xk))

    res = differential_evolution(
        lambda x: joint_objective(x, cfg, rules, rrules),
        bounds=bnds, seed=seed, maxiter=maxiter, polish=False,
        updating="deferred", callback=_cb,
    )
    final = _split(res.x)
    if not frames or frames[-1] != final:
        frames.append(final)
    return _result_from_x(res.x, cfg, rules, rrules, int(res.nfev)), frames
