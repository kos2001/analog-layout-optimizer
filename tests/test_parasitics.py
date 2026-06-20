"""Parasitic extraction + post-layout re-simulation."""

from layout_opt.parasitics import (
    Tech, extract_parasitics, post_layout_specs, post_layout_from_routing, DEMO_SIZING,
)
from layout_opt.opamp import evaluate_opamp
from layout_opt.placement import run_flow


def _routing(nets):
    return {"nets": nets}


def test_extract_scales_with_wirelength():
    short = _routing({"A": {"cells": [[0, 0, 0], [1, 0, 0]], "wirelength": 1, "vias": 0}})
    long = _routing({"A": {"cells": [[i, 0, 0] for i in range(20)], "wirelength": 19, "vias": 0}})
    cs = extract_parasitics(short)["A"]
    cl = extract_parasitics(long)["A"]
    assert cl["C_fF"] > cs["C_fF"] and cl["R_ohm"] > cs["R_ohm"]


def test_coupling_counted_between_nets():
    nets = {"A": {"cells": [[0, 0, 0]], "wirelength": 0, "vias": 0},
            "B": {"cells": [[1, 0, 0]], "wirelength": 0, "vias": 0}}
    par = extract_parasitics(_routing(nets))
    assert par["A"]["coupling"] >= 1 and par["B"]["coupling"] >= 1


def test_parasitics_only_degrade_phase_margin():
    pre = evaluate_opamp(DEMO_SIZING)
    post = post_layout_specs(DEMO_SIZING, c_out_F=40e-15, c_n2_F=30e-15)
    assert post["pm_deg"] < pre.pm_deg            # parasitics hurt PM
    assert abs(post["gain_db"] - pre.gain_db) < 0.1   # DC gain unchanged
    assert abs(post["gbw_mhz"] - pre.gbw_hz / 1e6) < 0.1  # GBW set by Cc, unchanged


def test_zero_parasitics_match_schematic():
    pre = evaluate_opamp(DEMO_SIZING)
    post = post_layout_specs(DEMO_SIZING, 0.0, 0.0)
    assert abs(post["pm_deg"] - pre.pm_deg) < 0.5


def test_internal_node_cap_hurts_more_than_output():
    # Same cap on the high-impedance n2 node hurts PM far more than on the load.
    out_only = post_layout_specs(DEMO_SIZING, c_out_F=30e-15, c_n2_F=0.0)
    n2_only = post_layout_specs(DEMO_SIZING, c_out_F=0.0, c_n2_F=30e-15)
    assert n2_only["pm_deg"] < out_only["pm_deg"]


def test_better_placement_degrades_less():
    sa = post_layout_from_routing(run_flow("sa", seed=1)["routing"])
    rnd = post_layout_from_routing(run_flow("random", seed=1)["routing"])
    assert sa["post"]["pm_deg"] > rnd["post"]["pm_deg"]   # tighter route -> better PM


def test_flow_includes_postlayout():
    f = run_flow("sa", seed=1)
    pl = f["postlayout"]
    assert "pre" in pl and "post" in pl and "critical" in pl
    assert pl["pre"]["pm_deg"] > pl["post"]["pm_deg"]
