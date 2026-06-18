"""The optimizer must find the *known* analytic optimum, fully offline.

Because the surrogate is transparent, the constrained optimum is computable by
hand: minimize bbox area while meeting every DRC floor and the drive spec.
Every parameter wants to shrink, so each lands on its binding lower bound:

  * l, finger_pitch, guard_gap, gr_width -> their DRC floors
  * w_finger                              -> spec floor w_min_total / nf

This lets us assert correctness of the generator + evaluator + optimizer
together without any Virtuoso.
"""

from layout_opt.evaluate import evaluate
from layout_opt.generator import DiffPairConfig, DesignParams, PDKRules
from layout_opt.optimize import optimize

import pytest


def analytic_optimum(cfg: DiffPairConfig, rules: PDKRules) -> DesignParams:
    return DesignParams(
        w_finger=cfg.w_min_total / cfg.nf,
        l=rules.min_l,
        finger_pitch=rules.min_poly_pitch,
        guard_gap=rules.min_gr_gap,
        gr_width=rules.min_gr_width,
    )


def test_converges_to_analytic_optimum():
    cfg = DiffPairConfig(nf=4)
    rules = PDKRules()
    opt = optimize(cfg=cfg, rules=rules, seed=0, maxiter=200)

    want = analytic_optimum(cfg, rules)
    got = opt.params

    # Each parameter within 1nm of the analytic optimum.
    assert got.w_finger == pytest.approx(want.w_finger, abs=1e-3)
    assert got.l == pytest.approx(want.l, abs=1e-3)
    assert got.finger_pitch == pytest.approx(want.finger_pitch, abs=1e-3)
    assert got.guard_gap == pytest.approx(want.guard_gap, abs=1e-3)
    assert got.gr_width == pytest.approx(want.gr_width, abs=1e-3)


def test_optimum_is_drc_clean_and_minimal():
    cfg = DiffPairConfig(nf=4)
    rules = PDKRules()
    opt = optimize(cfg=cfg, rules=rules, seed=0, maxiter=200)

    assert opt.result.is_clean
    assert opt.result.penalty == 0.0

    want_area = evaluate(analytic_optimum(cfg, rules), cfg, rules).area
    # Optimizer area must not beat the true optimum (allow tiny numerical slack).
    assert opt.result.area == pytest.approx(want_area, rel=1e-3)
    assert opt.result.area >= want_area - 1e-6
