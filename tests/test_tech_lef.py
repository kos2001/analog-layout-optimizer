"""Tech-LEF rule extraction vs the hardcoded SKY130 literals.

Parser tests run on an inline LEF fragment; the foundry comparisons skip when
the SKY130 tech LEF is not installed (PDK_ROOT / ~/pdk).
"""

import pytest

from layout_opt import tech_lef
from layout_opt.klayout_drc import METAL_RULES
from layout_opt.parasitics import Tech

_FRAGMENT = """\
VERSION 5.7 ;
UNITS
  DATABASE MICRONS 1000 ;
END UNITS
MANUFACTURINGGRID 0.005 ;

LAYER met1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.34 ;
  WIDTH 0.14 ;                     # Met1 1
  # SPACING 0.99 ;                 # superseded, must be ignored
  SPACINGTABLE
     PARALLELRUNLENGTH 0
     WIDTH 0 0.14
     WIDTH 3 0.28 ;
  AREA 0.083 ;
  THICKNESS 0.35 ;
  MINENCLOSEDAREA 0.14 ;
  EDGECAPACITANCE 40.567E-6 ;
  CAPACITANCE CPERSQDIST 25.7784E-6 ;
  DCCURRENTDENSITY AVERAGE 2.8 ;
  MAXIMUMDENSITY 70 ;
  RESISTANCE RPERSQ 0.125 ;
END met1

LAYER via
  TYPE CUT ;
  WIDTH 0.15 ;
  SPACING 0.17 ;
  ENCLOSURE BELOW 0.055 0.085 ;
  ENCLOSURE ABOVE 0.055 0.085 ;
  RESISTANCE 4.50 ;
END via

LAYER met2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.46 ;
  WIDTH 0.2 ;
  SPACING 0.21 ;
END met2
"""


@pytest.fixture
def fragment(tmp_path):
    p = tmp_path / "frag.tlef"
    p.write_text(_FRAGMENT)
    return p


def test_parse_fragment(fragment):
    r = tech_lef.read_tech_lef(fragment)
    assert r["manufacturing_grid_um"] == 0.005
    assert r["database_units_per_um"] == 1000.0
    m1 = r["routing_layers"]["met1"]
    assert m1["direction"] == "horizontal" and m1["pitch_um"] == 0.34
    assert m1["min_width_um"] == 0.14
    assert m1["min_spacing_um"] == 0.14          # first SPACINGTABLE entry, not the comment
    assert m1["min_area_um2"] == 0.083           # AREA, not MINENCLOSEDAREA
    assert m1["thickness_um"] == 0.35 and m1["max_density_pct"] == 70.0
    assert m1["resistance_ohm_per_sq"] == 0.125
    assert m1["dc_current_ma_per_um"] == 2.8
    assert m1["cap_pf_per_um2"] == pytest.approx(25.7784e-6)
    assert m1["edge_cap_pf_per_um"] == pytest.approx(40.567e-6)
    assert r["routing_layers"]["met2"]["min_spacing_um"] == 0.21   # plain SPACING
    via = r["cut_layers"]["via"]
    assert via == {"width_um": 0.15, "spacing_um": 0.17, "resistance_ohm": 4.5,
                   "enclosure_um": {"below": (0.055, 0.085), "above": (0.055, 0.085)}}


def test_missing_or_empty_lef_raises(tmp_path):
    with pytest.raises(tech_lef.TechLefError):
        tech_lef.read_tech_lef(tmp_path / "nope.tlef")
    empty = tmp_path / "empty.tlef"
    empty.write_text("VERSION 5.7 ;\n")
    with pytest.raises(tech_lef.TechLefError):
        tech_lef.read_tech_lef(empty)


def test_metal_rules_needs_every_drc_layer(fragment):
    # The fragment has no met3: an incomplete deck must fail loudly.
    with pytest.raises(tech_lef.TechLefError):
        tech_lef.metal_rules(fragment)


def test_fallbacks_without_a_lef(monkeypatch):
    monkeypatch.setattr(tech_lef, "find_tech_lef", lambda *a, **k: None)
    assert tech_lef.metal_rules() == METAL_RULES
    assert tech_lef.parasitic_tech() == Tech()
    from layout_opt.em import JMAX_PER_UM
    assert tech_lef.em_limits() == JMAX_PER_UM


def test_parasitic_tech_from_fragment(fragment):
    t = tech_lef.parasitic_tech(fragment, pitch_um=0.5, track_um=0.25)
    assert t.r_per_cell == pytest.approx(0.125 * 0.5 / 0.25)
    assert t.r_via == 4.5
    assert t.c_area_fF == pytest.approx((25.7784e-6 * 0.125 + 2 * 40.567e-6 * 0.5) * 1e3)
    assert t.c_couple_fF == Tech().c_couple_fF    # not in a LEF


# --- the real SKY130 tech LEF --------------------------------------------------
_LEF = tech_lef.find_tech_lef()
needs_lef = pytest.mark.skipif(_LEF is None, reason="SKY130 tech LEF not installed")


@needs_lef
def test_sky130_metal_rules_match_klayout_deck():
    """The DRC deck's met1..met3 width/space equal the foundry LEF."""
    assert tech_lef.metal_rules(_LEF) == METAL_RULES


@needs_lef
def test_sky130_routing_layers_and_grid():
    r = tech_lef.read_tech_lef(_LEF)
    assert r["manufacturing_grid_um"] == 0.005
    rl = r["routing_layers"]
    assert [rl[m]["direction"] for m in ("met1", "met2", "met3")] == \
        ["horizontal", "vertical", "horizontal"]
    assert (rl["met1"]["pitch_um"], rl["met2"]["pitch_um"], rl["met3"]["pitch_um"]) == \
        (0.34, 0.46, 0.68)
    assert rl["met1"]["resistance_ohm_per_sq"] == 0.125
    assert rl["met3"]["resistance_ohm_per_sq"] == 0.047


@needs_lef
def test_sky130_no_geometry_errors_only_documented_conservatism():
    """No hardcoded literal is *less* safe than the LEF; the known pessimistic
    ones (EM limits, parasitic R/C estimate) are reported, not hidden."""
    diffs = tech_lef.compare_to_hardcoded(_LEF)
    errors = [d for d in diffs if d["severity"] == "error"]
    assert errors == []
    conservative = {(d["where"], d["item"]) for d in diffs}
    assert ("em.JMAX_PER_UM", "met1") in conservative       # 1.0 vs LEF 2.8 mA/um
    assert ("parasitics.Tech", "r_per_cell (ohm/cell)") in conservative
