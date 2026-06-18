"""Surrogate-assisted (active-learning) optimization with a validation loop.

This is the hybrid that answers "can a surrogate stand in for Virtuoso?":

  1. Sample a few designs and evaluate the *expensive* ground truth (Spectre+PEX
     stand-in) -> initial training set.
  2. Fit a GP surrogate of the FoM.
  3. Optimize area s.t. DRC + drive-spec + (surrogate FoM >= target) using
     thousands of *cheap* surrogate calls - zero ground-truth calls here.
  4. VALIDATE: evaluate the proposed optimum with the ground truth (one
     expensive call). Record surrogate-vs-truth error.
  5. Add that point to the training set, retrain, repeat.

The ground truth is queried only `n_init + n_holdout + rounds` times, versus the
many thousands of evaluations the optimizer consumes - the savings a surrogate
buys. The per-round prediction error and holdout RMSE quantify how far you can
trust the surrogate, i.e. when you still must fall back to the real simulator.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import differential_evolution
from scipy.stats import qmc

from .evaluate import PENALTY_WEIGHT, evaluate
from .generator import (
    DEFAULT_BOUNDS,
    DesignParams,
    DiffPairConfig,
    PDKRules,
    bounds_vector,
)
from .surrogate import SurrogateModel
from .truth import truth_fom


def _lhs(n: int, bounds: list[tuple[float, float]], seed: int) -> list[DesignParams]:
    """Latin-hypercube sample of *n* designs within bounds."""
    sampler = qmc.LatinHypercube(d=len(bounds), seed=seed)
    unit = sampler.random(n)
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    scaled = lo + unit * (hi - lo)
    return [DesignParams.from_vector(row) for row in scaled]


@dataclass
class Round:
    index: int
    proposed: DesignParams
    area: float
    fom_pred: float       # surrogate prediction at the proposed optimum
    fom_truth: float      # ground-truth FoM at the proposed optimum
    pred_error: float     # |pred - truth|
    holdout_rmse: float   # surrogate accuracy on a fixed held-out set
    holdout_r2: float
    meets_target: bool    # does the TRUTH FoM meet the target?
    expensive_calls: int  # cumulative ground-truth evaluations used


@dataclass
class SurrogateOptResult:
    rounds: list[Round] = field(default_factory=list)
    best: DesignParams | None = None
    best_area: float = float("nan")
    best_fom_truth: float = float("nan")
    expensive_calls: int = 0
    surrogate_calls: int = 0  # cheap calls (optimizer evaluations)
    fom_target: float = 0.0


def surrogate_assisted_optimize(
    fom_target: float,
    cfg: DiffPairConfig | None = None,
    rules: PDKRules | None = None,
    n_init: int = 12,
    n_holdout: int = 12,
    rounds: int = 6,
    seed: int = 0,
    de_maxiter: int = 40,
) -> SurrogateOptResult:
    cfg = cfg or DiffPairConfig()
    rules = rules or PDKRules()
    bnds = bounds_vector(DEFAULT_BOUNDS)

    expensive = 0  # ground-truth call counter
    surrogate_calls = 0

    # --- initial training set + fixed holdout, both from the ground truth ---
    train_x = _lhs(n_init, bnds, seed=seed)
    train_y = [truth_fom(p, cfg) for p in train_x]
    expensive += len(train_x)

    hold_x = _lhs(n_holdout, bnds, seed=seed + 999)
    hold_y = [truth_fom(p, cfg) for p in hold_x]
    expensive += len(hold_x)

    model = SurrogateModel()
    model.fit(train_x, train_y)

    result = SurrogateOptResult(fom_target=fom_target)

    for r in range(rounds):
        # Objective uses ONLY the surrogate for the (expensive) FoM term.
        nonlocal_counter = {"n": 0}

        def objective(x) -> float:
            nonlocal_counter["n"] += 1
            p = DesignParams.from_vector(x)
            base = evaluate(p, cfg, rules).objective  # area + DRC + drive-spec
            fom_pred, _ = model.predict_one(p)
            fom_pen = PENALTY_WEIGHT * max(0.0, fom_target - fom_pred)
            return base + fom_pen

        de = differential_evolution(
            objective, bounds=bnds, seed=seed + r,
            maxiter=de_maxiter, polish=False, updating="deferred",
        )
        surrogate_calls += nonlocal_counter["n"]
        proposed = DesignParams.from_vector(de.x)

        # --- VALIDATE against the ground truth (one expensive call) ---
        fom_pred, _ = model.predict_one(proposed)
        fom_truth = truth_fom(proposed, cfg)
        expensive += 1

        metrics = model.score(hold_x, hold_y)
        area = evaluate(proposed, cfg, rules).area
        result.rounds.append(
            Round(
                index=r,
                proposed=proposed,
                area=area,
                fom_pred=fom_pred,
                fom_truth=fom_truth,
                pred_error=abs(fom_pred - fom_truth),
                holdout_rmse=metrics.rmse,
                holdout_r2=metrics.r2,
                meets_target=fom_truth >= fom_target,
                expensive_calls=expensive,
            )
        )

        # --- active learning: add the validated point, retrain ---
        train_x.append(proposed)
        train_y.append(fom_truth)
        model.fit(train_x, train_y)

    # Best = smallest area among rounds whose TRUTH FoM met the target.
    feasible = [rd for rd in result.rounds if rd.meets_target]
    chosen = min(feasible, key=lambda rd: rd.area) if feasible else \
        min(result.rounds, key=lambda rd: rd.pred_error)
    result.best = chosen.proposed
    result.best_area = chosen.area
    result.best_fom_truth = chosen.fom_truth
    result.expensive_calls = expensive
    result.surrogate_calls = surrogate_calls
    return result
