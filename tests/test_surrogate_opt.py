"""The hybrid loop: few ground-truth calls, validated convergence, real cost.

This is the test that backs the claim "a surrogate can stand in for Virtuoso in
the search loop, but you still validate against the truth."
"""

from layout_opt.generator import DiffPairConfig
from layout_opt.optimize import optimize
from layout_opt.surrogate_opt import surrogate_assisted_optimize

TARGET = 3.0
NINIT, NHOLD, ROUNDS = 10, 8, 5


def _run():
    return surrogate_assisted_optimize(
        fom_target=TARGET, n_init=NINIT, n_holdout=NHOLD,
        rounds=ROUNDS, seed=0, de_maxiter=25,
    )


def test_expensive_call_budget_is_tiny():
    r = _run()
    # Ground truth is queried only for init + holdout + one per round.
    assert r.expensive_calls == NINIT + NHOLD + ROUNDS
    # ...while the optimizer consumed orders of magnitude more cheap calls.
    assert r.surrogate_calls > 50 * r.expensive_calls


def test_surrogate_prediction_error_shrinks():
    r = _run()
    first = r.rounds[0].pred_error
    last_avg = sum(rd.pred_error for rd in r.rounds[-2:]) / 2
    # Active-learning retraining tightens the surrogate where it matters.
    assert last_avg < 0.5 * first


def test_best_meets_target_under_ground_truth():
    r = _run()
    # The chosen design must satisfy the spec when checked by the *truth*,
    # not merely by the surrogate.
    assert r.best_fom_truth >= TARGET


def test_performance_constraint_costs_area():
    r = _run()
    geom_area = optimize(maxiter=120).result.area  # pure area optimum, no perf
    # Meeting the gain target forces the design off the area floor.
    assert r.best_area > geom_area + 1e-3
