"""Black-box optimization over the surrogate objective.

Uses scipy's differential_evolution (global, gradient-free, bounded) - a good
fit for the non-smooth penalty objective and dependency-light for offline CI.
The evaluation backend is injected, so swapping the surrogate for a real
Virtuoso/Spectre `evaluate` later requires no change here.

For >~3 noisy/expensive params with a real (slow) backend, swap the optimizer
for TuRBO per the repo's `optimizer` skill - the (objective, bounds) interface
is identical.
"""

from __future__ import annotations

from dataclasses import dataclass

from scipy.optimize import differential_evolution

from .evaluate import EvalResult, evaluate, make_objective
from .generator import (
    DEFAULT_BOUNDS,
    DesignParams,
    DiffPairConfig,
    PDKRules,
    bounds_vector,
)


@dataclass
class OptResult:
    params: DesignParams
    result: EvalResult
    n_evals: int
    raw: object  # underlying scipy OptimizeResult


def optimize(
    cfg: DiffPairConfig | None = None,
    rules: PDKRules | None = None,
    bounds: dict | None = None,
    seed: int = 0,
    maxiter: int = 100,
    tol: float = 1e-7,
) -> OptResult:
    """Minimize bbox area subject to DRC + drive-strength spec (as penalties)."""
    cfg = cfg or DiffPairConfig()
    rules = rules or PDKRules()
    objective = make_objective(cfg, rules)
    bnds = bounds_vector(bounds or DEFAULT_BOUNDS)

    res = differential_evolution(
        objective,
        bounds=bnds,
        seed=seed,
        maxiter=maxiter,
        tol=tol,
        polish=True,
        updating="deferred",
    )

    best = DesignParams.from_vector(res.x)
    return OptResult(
        params=best,
        result=evaluate(best, cfg, rules),
        n_evals=int(res.nfev),
        raw=res,
    )


def optimize_trajectory(
    cfg: DiffPairConfig | None = None,
    rules: PDKRules | None = None,
    bounds: dict | None = None,
    seed: int = 0,
    maxiter: int = 60,
) -> tuple[OptResult, list[DesignParams]]:
    """Like ``optimize`` but also return the best-so-far design per generation.

    The trajectory is what the frontend animates: each entry is the incumbent
    best at the end of one differential-evolution generation, so playing them
    back shows the area shrinking toward the DRC-clean optimum.
    """
    cfg = cfg or DiffPairConfig()
    rules = rules or PDKRules()
    objective = make_objective(cfg, rules)
    bnds = bounds_vector(bounds or DEFAULT_BOUNDS)

    frames: list[DesignParams] = []

    def _cb(xk, convergence=None):
        # scipy passes the current best vector each generation.
        frames.append(DesignParams.from_vector(xk))

    res = differential_evolution(
        objective,
        bounds=bnds,
        seed=seed,
        maxiter=maxiter,
        polish=False,           # keep frames on the search grid, no final jump
        updating="deferred",
        callback=_cb,
    )

    best = DesignParams.from_vector(res.x)
    if not frames or frames[-1].to_vector() != best.to_vector():
        frames.append(best)
    opt = OptResult(
        params=best,
        result=evaluate(best, cfg, rules),
        n_evals=int(res.nfev),
        raw=res,
    )
    return opt, frames
