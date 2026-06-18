"""The ground-truth model: deterministic, and in genuine tension with area."""

from layout_opt.generator import DiffPairConfig, DesignParams
from layout_opt.truth import truth_fom, truth_performance


def p(**kw) -> DesignParams:
    base = dict(w_finger=0.6, l=0.08, finger_pitch=0.25, guard_gap=0.30, gr_width=0.10)
    base.update(kw)
    return DesignParams(**base)


def test_deterministic():
    assert truth_fom(p()) == truth_fom(p())


def test_performance_rewards_bigger_devices():
    # Gain ~ sqrt(W_total * L): wider fingers and longer channel both help.
    base = truth_fom(p())
    assert truth_fom(p(w_finger=1.2)) > base
    assert truth_fom(p(l=0.20)) > base


def test_parasitics_penalize_wide_spacing():
    base = truth_fom(p())
    assert truth_fom(p(finger_pitch=0.55)) < base
    assert truth_fom(p(guard_gap=0.90)) < base


def test_tension_with_area_minimum():
    # At the pure area-minimizing geometry (everything at its floor), the FoM is
    # LOW - so any nontrivial FoM target must push the design off the area floor.
    cfg = DiffPairConfig()
    area_opt = DesignParams(
        w_finger=cfg.w_min_total / cfg.nf, l=0.03,
        finger_pitch=0.18, guard_gap=0.20, gr_width=0.05,
    )
    big = DesignParams(
        w_finger=1.2, l=0.20, finger_pitch=0.18, guard_gap=0.20, gr_width=0.05,
    )
    assert truth_performance(big, cfg).fom > truth_performance(area_opt, cfg).fom
