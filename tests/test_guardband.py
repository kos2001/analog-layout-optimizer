"""PM/GBW parasitic guard-band: size against post-layout targets, not nominal."""

from layout_opt.opamp import evaluate_opamp
from layout_opt.opamp_opt import (
    GBW_MIN, PM_MIN, _violation_from_specs, de_log_refine,
)
from layout_opt.flow_e2e import run_end_to_end


def test_violation_accepts_custom_targets():
    # A sizing that meets nominal specs must violate guard-banded ones.
    d = de_log_refine(seed=0, maxiter=60)
    s = evaluate_opamp(d.params)
    assert _violation_from_specs(s, d.params) <= 1e-9
    assert _violation_from_specs(s, d.params,
                                 pm_min=PM_MIN + 15.0,
                                 gbw_min=GBW_MIN * 2.0) > 0


def test_guardband_sizing_survives_estimated_parasitics():
    # Guard-banded sizing must stay stable once the estimated routing
    # parasitics (C on n2 / VOUT) are applied — that is its whole point.
    from layout_opt.opamp_opt import C_N2_EST_F, C_OUT_EST_F
    from layout_opt.parasitics import post_layout_specs

    d = de_log_refine(seed=0, maxiter=90, guardband=True)
    assert d.feasible
    post = post_layout_specs(d.params, C_OUT_EST_F, C_N2_EST_F)
    assert post["pm_deg"] >= PM_MIN - 1e-6
    assert evaluate_opamp(d.params).gbw_hz >= GBW_MIN - 1.0


def test_e2e_guardband_stabilizes_postlayout():
    r = run_end_to_end(place="sa", seed=0, sky130=False, maxiter=90)
    post = next(s for s in r["stages"] if s["name"].startswith("Post-layout"))
    assert post["status"] == "pass", post["detail"]
