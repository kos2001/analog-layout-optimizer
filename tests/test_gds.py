"""GDSII export of the placed+routed flow."""

import gdstk

from layout_opt.placement import run_flow
from layout_opt.gds import flow_to_gds, flow_to_gds_bytes, MET, VIA, DIFF


def test_gds_is_valid_and_has_expected_layers(tmp_path):
    f = run_flow("sa", seed=1)
    out = str(tmp_path / "ota.gds")
    stats = flow_to_gds(f, out)
    assert stats["polygons"] > 0 and stats["counts"]["device"] == 15

    lib = gdstk.read_gds(out)            # round-trips as a valid GDS
    top = lib.top_level()[0]
    assert top.name == "OTA_TOP"
    layers = {(p.layer, p.datatype) for p in top.get_polygons()}
    assert MET[0] in layers and DIFF in layers     # met1 + device marker present


def test_gds_bytes_have_gds_magic():
    f = run_flow("sa", seed=1)
    data, stats = flow_to_gds_bytes(f)
    # GDSII starts with a HEADER record (length 0x0006, record type 0x0002).
    assert data[:4] == b"\x00\x06\x00\x02"
    assert stats["bbox_um"] is not None and stats["area_um2"] > 0


def test_vias_emitted_where_nets_change_layer():
    f = run_flow("sa", seed=1)
    _, stats = flow_to_gds_bytes(f)
    # the multi-layer router uses vias, so the GDS must contain via cuts
    assert stats["counts"]["via"] >= 1
    assert {"layer": VIA[0], "datatype": VIA[1]} in stats["layers"]
