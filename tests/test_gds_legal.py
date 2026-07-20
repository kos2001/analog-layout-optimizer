"""GDS emission must be SKY130-legal by construction (BEOL metal/via rules)."""

import gdstk
import pytest

from layout_opt.gds import flow_to_gds, VIA, MET
from layout_opt.klayout_drc import run_drc, klayout_available
from layout_opt.placement import run_flow


@pytest.fixture(scope="module")
def gds_path(tmp_path_factory):
    flow = run_flow(place="sa", seed=0)
    path = tmp_path_factory.mktemp("gds") / "ota.gds"
    flow_to_gds(flow, str(path))
    return str(path)


def test_vias_are_sky130_exact_size(gds_path):
    # SKY130 rule via.1a: met1-met2 via cuts must be exactly 0.15 x 0.15 um.
    lib = gdstk.read_gds(gds_path)
    top = [c for c in lib.cells if c.name == "OTA_TOP"][0]
    vias = [p for p in top.get_polygons()
            if (p.layer, p.datatype) == VIA]
    assert vias, "expected via cuts in the routed GDS"
    for v in vias:
        (x0, y0), (x1, y1) = v.points.min(axis=0), v.points.max(axis=0)
        assert (round(x1 - x0, 3), round(y1 - y0, 3)) == (0.15, 0.15)


def test_metal_tracks_narrower_than_grid_pitch(gds_path):
    # Full-pitch metal squares give zero spacing to neighbouring nets; tracks
    # must leave >= 0.14 um of space inside each 0.5 um grid cell.
    lib = gdstk.read_gds(gds_path)
    top = [c for c in lib.cells if c.name == "OTA_TOP"][0]
    for layer in MET.values():
        for p in top.get_polygons():
            if (p.layer, p.datatype) != layer:
                continue
            (x0, y0), (x1, y1) = p.points.min(axis=0), p.points.max(axis=0)
            assert min(x1 - x0, y1 - y0) <= 0.36 + 1e-9, \
                f"metal rect {x1-x0:.2f}x{y1-y0:.2f} fills the grid pitch"


@pytest.mark.skipif(not klayout_available(), reason="klayout not installed")
def test_exported_gds_is_metal_drc_clean(gds_path):
    # KLayout min-width/min-space on met1/met2 must be clean by construction.
    rep = run_drc(gds_path)
    assert rep["clean"], f"metal DRC violations: {rep['total']}"
