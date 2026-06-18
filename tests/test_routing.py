"""Structured router: connectivity always holds, DRC detected, optimum found."""

import pytest

from layout_opt.generator import DiffPairConfig, DesignParams
from layout_opt.routing import (
    RoutingParams,
    RoutingRules,
    connectivity_ok,
    optimize_routing,
    route,
    routing_violations,
    routed_layout,
)

CFG = DiffPairConfig(nf=4)
P = DesignParams(w_finger=0.5, l=0.03, finger_pitch=0.18, guard_gap=0.20, gr_width=0.05)


def rp(**kw) -> RoutingParams:
    base = dict(rail_width=0.10, rail_pitch=0.30, via_size=0.06)
    base.update(kw)
    return RoutingParams(**base)


def test_params_vector_roundtrip():
    r = rp()
    assert RoutingParams.from_vector(r.to_vector()) == r


def test_topology_counts():
    res = route(P, rp(), CFG)
    n = 2 * CFG.nf
    assert len(res.rails) == 5                 # VINP VINN VOUTN VOUTP VTAIL
    assert res.via_count == 3 * n              # gate + drain + source per finger
    assert len(res.stubs) == 3 * n


def test_connectivity_always_holds():
    # Connectivity is structural - it must hold for any routing params.
    for r in (rp(), rp(rail_width=0.2, rail_pitch=0.5), rp(via_size=0.04)):
        assert connectivity_ok(route(P, r, CFG), CFG)


def test_drc_violations_detected():
    bad = rp(rail_width=0.05, rail_pitch=0.10, via_size=0.04)
    v = routing_violations(bad)
    assert any("rail_width" in m for m in v)
    assert any("rail_spacing" in m for m in v)
    assert any("via_enclosure" in m for m in v)


def test_clean_routing_has_no_violations():
    assert routing_violations(rp(rail_width=0.10, rail_pitch=0.30, via_size=0.06)) == []


def test_tighter_pitch_shortens_wirelength():
    loose = route(P, rp(rail_pitch=0.45), CFG).wirelength
    tight = route(P, rp(rail_pitch=0.20), CFG).wirelength
    assert tight < loose


def test_optimizer_finds_drc_clean_minimum():
    rules = RoutingRules()
    opt = optimize_routing(P, CFG, rules=rules, seed=0, maxiter=120)
    assert opt.is_clean
    # Analytic optimum: via at floor; rail_width = max(min_w, via+2*enc);
    # rail_pitch = rail_width + min_spacing.
    assert opt.params.via_size == pytest.approx(rules.min_via, abs=2e-3)
    exp_w = max(rules.min_m_width, rules.min_via + 2 * rules.min_via_enclosure)
    assert opt.params.rail_width == pytest.approx(exp_w, abs=3e-3)
    assert opt.params.rail_pitch == pytest.approx(exp_w + rules.min_m_spacing, abs=3e-3)


def test_optimized_routing_beats_loose_default():
    opt = optimize_routing(P, CFG, seed=0, maxiter=120)
    loose = route(P, rp(rail_width=0.2, rail_pitch=0.45, via_size=0.1), CFG)
    assert opt.wirelength < loose.wirelength
    assert opt.metal_area < loose.metal_area


def test_routed_layout_includes_device_and_routing():
    lay = routed_layout(P, rp(), CFG)
    # device shapes (13) + 5 rails + 24 stubs + 24 vias
    assert len(lay.rects) == 13 + 5 + 24 + 24
    assert len(lay.rects_on("M2")) == 5 + 24
