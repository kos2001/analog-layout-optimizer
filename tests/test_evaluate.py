from layout_opt.evaluate import PENALTY_WEIGHT, evaluate, make_objective
from layout_opt.generator import DiffPairConfig, DesignParams, PDKRules

import pytest


def clean_params() -> DesignParams:
    # All at DRC floors; w_finger meets the drive spec (nf*0.5 = 2.0 = w_min_total).
    return DesignParams(
        w_finger=0.5, l=0.03, finger_pitch=0.18, guard_gap=0.20, gr_width=0.05
    )


def test_clean_design_has_no_penalty():
    r = evaluate(clean_params())
    assert r.is_clean
    assert r.penalty == 0.0
    assert r.objective == pytest.approx(r.area)


def test_drc_violation_is_penalized():
    p = DesignParams(
        w_finger=0.5, l=0.01, finger_pitch=0.18, guard_gap=0.20, gr_width=0.05
    )  # l below min_l (0.03)
    r = evaluate(p)
    assert not r.is_clean
    assert any("L" in v for v in r.violations)
    # shortfall 0.02 * weight
    assert r.penalty == pytest.approx(PENALTY_WEIGHT * 0.02)


def test_spec_violation_is_penalized():
    p = DesignParams(
        w_finger=0.2, l=0.03, finger_pitch=0.18, guard_gap=0.20, gr_width=0.05
    )  # nf*0.2 = 0.8 < w_min_total 2.0
    r = evaluate(p)
    assert any("W_total" in v for v in r.violations)
    assert r.penalty == pytest.approx(PENALTY_WEIGHT * (2.0 - 0.8))


def test_objective_function_is_finite_on_bad_input():
    obj = make_objective()
    assert obj([float("nan")] * 5) < 1e10  # caught, returns finite penalty
    assert obj([1, 2, 3]) == pytest.approx(1.0e9)  # wrong length -> caught
