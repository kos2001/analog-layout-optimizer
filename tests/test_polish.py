"""Post-SA placement polish: measured moves, never worse at sign-off."""

import pytest

from layout_opt import polish
from layout_opt.placement import run_flow, sa_place
from layout_opt.polish import (
    GAIN_OBJECTIVES, GAIN_PCT, OBJECTIVES, TOLERANCE_PCT, Layout, Trial,
    _components, evaluate_layout, improves, objectives, polish_placement,
)
from layout_opt.schematic import two_stage_ota


def _t(verdict="PASS", **obj) -> Trial:
    base = {k: 10.0 for k in OBJECTIVES}
    base.update(obj)
    return Trial(layout=Layout(pos={}), flow={"signoff": {"verdict": verdict}},
                 objectives=base)


def test_evaluate_layout_matches_run_flow():
    sch = two_stage_ota()
    pos = sa_place(sch, 1, analog_aware=True)
    ref = run_flow(seed=1, analog_aware=True)
    assert objectives(evaluate_layout(sch, Layout(pos=pos))) == objectives(ref)


def test_mirror_flips_pins_left_right():
    sch = two_stage_ota()
    pos = sa_place(sch, 0)
    plain = {c.id: c for c in _components(sch, Layout(pos=pos))}
    flipped = {c.id: c for c in _components(sch, Layout(pos=pos, mirror={"M6": True}))}
    m6, f6 = plain["M6"], flipped["M6"]
    assert [(p.net, m6.w - 1 - p.dx, p.dy) for p in m6.pins] == \
        [(p.net, p.dx, p.dy) for p in f6.pins]
    assert plain["M5"].pins == flipped["M5"].pins


def test_gate_requires_signoff_and_a_material_gain():
    inc = _t()
    assert improves(inc, _t(wirelength=9.0))                       # -10% WL
    assert not improves(inc, _t(verdict="FAIL", wirelength=5.0))   # sign-off first
    assert not improves(inc, _t(wirelength=9.9))                   # -1% < GAIN_PCT
    assert not improves(inc, _t(wirelength=9.0, vias=11.0))        # vias may not grow
    assert not improves(inc, _t(wirelength=9.0, symmetry=10.5))    # matching kept
    # Within tolerance on a secondary objective is allowed for a real gain.
    assert improves(inc, _t(vias=9.0, wirelength=10.0 * (1 + TOLERANCE_PCT["wirelength"] / 200)))


def test_gate_bounds_drift_from_the_original():
    original = _t()
    inc = _t(vias=8.0, wirelength=10.19)           # already used most of the WL slack
    trial = _t(vias=7.0, wirelength=10.38)         # +1.9% vs inc, +3.8% vs original
    assert improves(inc, trial)
    assert not improves(inc, trial, original)


def test_non_signing_off_placement_is_returned_unchanged(monkeypatch):
    monkeypatch.setattr(polish._signoff, "run_signoff",
                        lambda *a, **k: {"verdict": "FAIL", "drcWarnings": 0})
    pos = sa_place(two_stage_ota(), 0)
    r = polish_placement(pos, rounds=2)
    assert r["changed"] is False and r["nTrials"] == 0
    assert r["pos"] == pos and r["reason"] == "incumbent does not sign off"


@pytest.mark.parametrize("seed", [0, 1])
def test_polish_never_worsens_signoff_or_any_objective(seed):
    sch = two_stage_ota()
    pos = sa_place(sch, seed, analog_aware=True)
    r = polish_placement(pos, sch, rounds=1)
    before, after = r["before"], r["after"]
    assert r["flow"]["signoff"]["verdict"] == "PASS"
    for k in OBJECTIVES:
        assert after[k] <= before[k] * (1 + TOLERANCE_PCT[k] / 100) + 1e-9, k
    if r["changed"]:
        assert any(after[k] <= before[k] * (1 - GAIN_PCT / 100) for k in GAIN_OBJECTIVES)
        # The reported flow is the polished placement, re-measured.
        assert objectives(evaluate_layout(sch, Layout(pos=r["pos"], mirror=r["mirror"]))) == after
