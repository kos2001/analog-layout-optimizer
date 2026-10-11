"""DC headroom: every transistor must sit in saturation at the bias point.

The square-law gain model assumes saturation; it says nothing about whether
the DC node voltages allow it. A sizing that pushes Vov6 to its floor puts the
second-stage gate (= Vth + Vov6) below the tail + Vov1 that M2 needs, so M2
drops into triode and the simulated gain collapses (81.5 dB analytic vs
50 dB in the level-1 simulator that mirrors the analytic model).
"""

import math
from dataclasses import replace

import pytest

from layout_opt.ngspice_backend import (
    GENERIC_NGSPICE, ngspice_available, ngspice_evaluate, render_netlist,
)
from layout_opt.opamp import SAT_MARGIN, VTH_N, VTH_P, cm_window, evaluate_opamp
from layout_opt.opamp_opt import _violation_from_specs, de_log_refine


def test_cm_window_matches_hand_derivation():
    p = de_log_refine(seed=0).params
    s = evaluate_opamp(p)
    lo, hi = cm_window(p)
    # lower edge: tail M5 saturated  -> Vcm >= Vtn + Vov1 + Vov5 + margin
    assert lo == pytest.approx(VTH_N + s.vov1 + s.vov5 + SAT_MARGIN)
    # upper edge: tightest of M2 (2Vtn + Vov6), M1 and M7 limits
    m2 = 2 * VTH_N + s.vov6 - SAT_MARGIN
    m1 = 1.8 - VTH_P + VTH_N - s.vov3 - SAT_MARGIN
    m7 = 1.8 - s.vov7 - SAT_MARGIN
    assert hi == pytest.approx(min(m2, m1, m7))


def test_sized_designs_have_a_valid_common_mode_window():
    for seed in range(3):
        d = de_log_refine(seed=seed)
        assert d.feasible
        assert evaluate_opamp(d.params).headroom >= 0.0, seed


def test_no_headroom_is_a_violation():
    d = de_log_refine(seed=0)
    s = replace(evaluate_opamp(d.params), headroom=-0.1)
    assert _violation_from_specs(s, d.params) > 0.0


def test_testbench_biases_inside_the_window():
    p = de_log_refine(seed=0).params
    lo, hi = cm_window(p, GENERIC_NGSPICE.vth_n, GENERIC_NGSPICE.vth_p)
    nl = render_netlist(p, GENERIC_NGSPICE, "/tmp/x.txt")
    vcm = float(next(l for l in nl.splitlines() if l.startswith("vcm ")).split()[-1])
    assert lo <= vcm <= hi
    assert vcm != pytest.approx(0.9)                     # not blindly VDD/2


@pytest.mark.skipif(not ngspice_available(), reason="ngspice not installed")
def test_level1_simulation_now_agrees_with_the_analytic_model():
    # The generic level-1 models share the analytic model's constants, so a
    # correctly biased sizing must simulate close to what the model predicts.
    p = de_log_refine(seed=0).params
    a = evaluate_opamp(p)
    s = ngspice_evaluate(p, GENERIC_NGSPICE)
    assert abs(s.gain_db - a.gain_db) < 3.0
    assert s.gbw_hz == pytest.approx(a.gbw_hz, rel=0.25)
    assert math.isfinite(s.pm_deg)
