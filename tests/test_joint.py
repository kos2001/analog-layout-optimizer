"""Joint device+routing co-optimization over the full 8-D parameter space."""

import pytest

from layout_opt.generator import DesignParams, DiffPairConfig, PDKRules
from layout_opt.joint import optimize_joint
from layout_opt.optimize import optimize as optimize_device
from layout_opt.routing import RoutingParams, RoutingRules, routed_layout

# Run the (deterministic) joint optimization once, share across tests.
J = optimize_joint(seed=0, maxiter=150)
CFG = DiffPairConfig()
RULES = PDKRules()
RRULES = RoutingRules()


def test_joint_optimum_is_clean():
    assert J.is_clean
    assert J.device_violations == []
    assert J.routing_violations == []
    assert J.drive_spec_met
    assert J.connected


def test_device_params_converge_to_floors():
    assert J.device.w_finger == pytest.approx(CFG.w_min_total / CFG.nf, abs=2e-2)
    assert J.device.l == pytest.approx(RULES.min_l, abs=5e-3)
    assert J.device.finger_pitch == pytest.approx(RULES.min_poly_pitch, abs=5e-3)
    assert J.device.guard_gap == pytest.approx(RULES.min_gr_gap, abs=5e-3)
    assert J.device.gr_width == pytest.approx(RULES.min_gr_width, abs=5e-3)


def test_routing_params_converge_to_floors():
    exp_w = max(RRULES.min_m_width, RRULES.min_via + 2 * RRULES.min_via_enclosure)
    assert J.routing.via_size == pytest.approx(RRULES.min_via, abs=5e-3)
    assert J.routing.rail_width == pytest.approx(exp_w, abs=8e-3)
    assert J.routing.rail_pitch == pytest.approx(exp_w + RRULES.min_m_spacing, abs=8e-3)


def test_total_area_exceeds_device_only():
    # The true cell area (incl. interconnect) is strictly larger than the
    # device-only area; ignoring routing underestimates the cell.
    device_only = optimize_device(maxiter=120).result.area
    assert J.total_area > device_only + 0.1
    assert J.total_area > J.device_area


def test_joint_beats_a_loose_layout():
    loose = routed_layout(
        DesignParams(w_finger=0.6, l=0.10, finger_pitch=0.35,
                     guard_gap=0.40, gr_width=0.12),
        RoutingParams(rail_width=0.20, rail_pitch=0.45, via_size=0.10),
        CFG, RRULES,
    ).bbox_area()
    assert J.total_area < loose
