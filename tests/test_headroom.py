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


# --- per-group channel length and length-aware biasing (SKY130) -------------
def test_gain_devices_get_their_own_length_with_wl_preserved():
    import re
    p = de_log_refine(seed=0).params
    m = replace(GENERIC_NGSPICE, l_um=0.2, l_gain_um=0.6)
    nl = render_netlist(p, m, "/tmp/x.txt")

    def l_of(dev):
        return float(re.search(rf"^m{dev} .* l=([\d.]+)u", nl, re.M).group(1))

    for dev in ("1", "2", "3", "4", "7", "b7"):
        assert l_of(dev) == pytest.approx(0.6), dev          # output resistance sets gain
    for dev in ("5", "b5", "6"):
        assert l_of(dev) == pytest.approx(0.2), dev          # M6 on the Miller-split node
    w1 = float(re.search(r"^m1 .* w=([\d.]+)u", nl, re.M).group(1))
    assert w1 == pytest.approx(round(p.wl1 * 0.6, 4))        # W/L unchanged


def test_sky130_vth_follows_channel_length():
    from layout_opt.ngspice_backend import SKY130_TT_VTH, sky130_vth
    assert sky130_vth(0.5) == SKY130_TT_VTH[0.5]
    n, pp = sky130_vth(1.25)                                  # between 1.0 and 1.5
    assert SKY130_TT_VTH[1.5][0] < n < SKY130_TT_VTH[1.0][0]
    assert SKY130_TT_VTH[1.0][1] < pp < SKY130_TT_VTH[1.5][1]
    assert sky130_vth(0.1) == SKY130_TT_VTH[0.5]              # clamped at the ends
    assert sky130_vth(9.0) == SKY130_TT_VTH[3.0]


def test_operating_point_is_seeded_from_the_analytic_dc_model():
    p = de_log_refine(seed=0).params
    nl = render_netlist(p, GENERIC_NGSPICE, "/tmp/x.txt")
    nodeset = next(l for l in nl.splitlines() if l.startswith(".nodeset"))
    for node in ("outp", "outm", "tail", "nb5", "pb7"):
        assert f"v({node})=" in nodeset
    seeds = dict(kv.split("=") for kv in nodeset.split()[1:])
    vcm = float(seeds["v(vout)"])
    assert float(seeds["v(outp)"]) < vcm                     # not all seeded at vcm
