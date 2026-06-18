"""Surrogate (Virtuoso-free) evaluation of a candidate design.

The optimizer treats evaluation as a black box. Here the box is pure Python:

  objective = bbox_area + penalty(DRC violations) + penalty(spec violations)

Every DRC rule modeled here is a coordinate inequality - exactly the subset of
a real DRC deck (min width / min spacing / min enclosure) that *can* be checked
geometrically without the PDK engine. The physically-faithful checks (real DRC
deck, LVS, parasitic-aware performance) are deferred to a Virtuoso backend that
would replace `evaluate` with the same (params -> scalar) signature.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .generator import DesignParams, DiffPairConfig, PDKRules, generate_layout


# Penalty weight: large vs. typical area (~1-3 um^2) so any violation dominates,
# steering the optimizer firmly into the DRC-clean / spec-meeting region.
PENALTY_WEIGHT = 1.0e3


@dataclass
class EvalResult:
    area: float
    penalty: float
    violations: list[str] = field(default_factory=list)

    @property
    def objective(self) -> float:
        return self.area + self.penalty

    @property
    def is_clean(self) -> bool:
        return not self.violations


def _under(name: str, value: float, floor: float, viols: list[str]) -> float:
    """Return shortfall below *floor* (0 if satisfied) and record a violation."""
    gap = floor - value
    if gap > 0:
        viols.append(f"{name}: {value:.4g} < min {floor:.4g}")
        return gap
    return 0.0


def evaluate(
    p: DesignParams,
    cfg: DiffPairConfig | None = None,
    rules: PDKRules | None = None,
) -> EvalResult:
    """Evaluate a design: compute area and DRC/spec penalties. Pure function."""
    cfg = cfg or DiffPairConfig()
    rules = rules or PDKRules()

    layout = generate_layout(p, cfg)
    area = layout.bbox_area()

    viols: list[str] = []
    shortfall = 0.0
    # Geometric DRC rules (min width / spacing / enclosure).
    shortfall += _under("L", p.l, rules.min_l, viols)
    shortfall += _under("W_finger", p.w_finger, rules.min_w, viols)
    shortfall += _under("poly_pitch", p.finger_pitch, rules.min_poly_pitch, viols)
    shortfall += _under("guard_gap", p.guard_gap, rules.min_gr_gap, viols)
    shortfall += _under("gr_width", p.gr_width, rules.min_gr_width, viols)

    # Design spec: total transistor width must meet a drive-strength floor.
    w_total = cfg.nf * p.w_finger
    shortfall += _under("W_total(spec)", w_total, cfg.w_min_total, viols)

    return EvalResult(area=area, penalty=PENALTY_WEIGHT * shortfall, violations=viols)


def make_objective(cfg: DiffPairConfig | None = None, rules: PDKRules | None = None):
    """Build a vector->scalar objective for scipy/TuRBO. Never returns nan/inf."""
    cfg = cfg or DiffPairConfig()
    rules = rules or PDKRules()

    def objective(x) -> float:
        try:
            p = DesignParams.from_vector(x)
            val = evaluate(p, cfg, rules).objective
        except Exception:
            return 1.0e9  # hard penalty on any failure; keep optimizer finite
        if not math.isfinite(val):
            return 1.0e9  # nan/inf (e.g. nan params) must never reach the optimizer
        return val

    return objective
