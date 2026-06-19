"""Process-change adaptation: NL parsing + re-optimized placement/routing."""

import pytest

from layout_opt.generator import PDKRules
from layout_opt.process_change import (
    ProcessOverrides,
    adapt,
    apply_overrides,
    parse_process_nl,
)

# One coarser-process adaptation, shared across the (slow) adapt tests.
NL = ("Process migration: min poly pitch is now 0.30 um, metal spacing 0.12 um, "
      "gate length 0.06, and the drive spec needs total W/L 3.0")
R = adapt(parse_process_nl(NL), seed=0, maxiter=90)


# --- NL parsing (fast) -----------------------------------------------------
def test_nl_extracts_values_with_units():
    ov = parse_process_nl(NL)
    assert ov.values["min_poly_pitch"] == pytest.approx(0.30)
    assert ov.values["min_m_spacing"] == pytest.approx(0.12)
    assert ov.values["min_l"] == pytest.approx(0.06)
    assert ov.values["w_min_total"] == pytest.approx(3.0)


def test_nl_nm_unit_conversion():
    ov = parse_process_nl("metal spacing 120 nm, min poly 250 nm")
    assert ov.values["min_m_spacing"] == pytest.approx(0.12)
    assert ov.values["min_poly_pitch"] == pytest.approx(0.25)


def test_apply_overrides_builds_new_rules():
    cfg, rules, rrules = apply_overrides(ProcessOverrides({"min_poly_pitch": 0.3,
                                                           "min_m_spacing": 0.12,
                                                           "w_min_total": 3.0}))
    assert rules.min_poly_pitch == 0.3
    assert rrules.min_m_spacing == 0.12
    assert cfg.w_min_total == 3.0
    # untouched fields keep defaults
    assert rules.min_l == PDKRules().min_l


def test_unknown_override_raises():
    with pytest.raises(KeyError):
        apply_overrides(ProcessOverrides({"nonsense": 1.0}))


# --- adaptation (uses shared R) --------------------------------------------
def test_coarser_process_grows_area_drc_clean():
    assert R.after["total_area_um2"] > R.before["total_area_um2"]   # coarser -> bigger
    assert R.after["drc_clean"]
    assert R.area_delta_pct > 0


def test_adapted_design_meets_new_floors():
    # placement + routing adjusted to the new DRC floors
    assert R.after["device"]["finger_pitch"] >= 0.30 - 5e-3
    assert R.after["device"]["l"] >= 0.06 - 5e-3
    # routing rail spacing must clear the new metal spacing 0.12
    gap = R.after["routing"]["rail_pitch"] - R.after["routing"]["rail_width"]
    assert gap >= 0.12 - 1e-2


def test_topology_is_fixed():
    assert R.topology_fixed["total_fingers"] == 8
    assert R.topology_fixed["nets"] == ["VINP", "VINN", "VOUTN", "VOUTP", "VTAIL"]


def test_empty_overrides_is_near_baseline():
    r = adapt(ProcessOverrides({}), seed=0, maxiter=90)
    assert r.after["total_area_um2"] == pytest.approx(r.before["total_area_um2"], rel=0.02)
