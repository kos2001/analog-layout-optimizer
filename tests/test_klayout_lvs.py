"""Transistor-level layout synthesis + real KLayout LVS."""

import klayout.db as db
import pytest

from layout_opt.device_layout import add_device, layer_index, build_current_mirror
from layout_opt.klayout_lvs import (
    extract_netlist, device_summary, schematic_mos_netlist, compare,
    lvs_current_mirror, lvs_ota,
)


def test_single_nfet_extracts_with_correct_size():
    ly = db.Layout(); ly.dbu = 0.005
    top = ly.create_cell("D"); li = layer_index(ly)
    add_device(top, li, 0, 0, w=1.0, l=0.15, kind="nmos")
    nl, _l2n = extract_netlist(ly, top)
    s = device_summary(nl)
    assert s["counts"].get("nmos") == 1
    assert s["devices"]["nmos"][0] == (1.0, 0.15)


def test_current_mirror_lvs_matches_schematic():
    r = lvs_current_mirror()
    assert r["match"] is True
    assert r["devices"]["counts"]["nmos"] == 2


def test_lvs_fails_on_wrong_schematic():
    # Build the mirror layout, compare to a *wrong* schematic (3 devices) -> mismatch.
    ly, top = build_current_mirror()
    nl, _l2n = extract_netlist(ly, top)
    wrong = schematic_mos_netlist(
        [{"name": "M0", "kind": "nmos", "S": "VSS", "G": "GATE", "D": "GATE", "W": 1.0, "L": 0.15},
         {"name": "M1", "kind": "nmos", "S": "VSS", "G": "GATE", "D": "OUT", "W": 1.0, "L": 0.15},
         {"name": "M2", "kind": "nmos", "S": "VSS", "G": "OUT", "D": "OUT", "W": 1.0, "L": 0.15}],
        ports=["VSS", "GATE", "OUT"], name="CMIRROR")
    assert compare(nl, wrong) is False


def test_full_ota_lvs_matches_schematic():
    r = lvs_ota()
    assert r["match"] is True                      # full OTA transistor P&R is LVS-clean
    assert r["devices"]["counts"] == {"nmos": 4, "pmos": 3}


def test_full_ota_gds_export(tmp_path):
    import gdstk
    out = str(tmp_path / "ota_tr.gds")
    r = lvs_ota(gds_out=out)
    assert r["match"] is True
    lib = gdstk.read_gds(out)                       # real, re-readable GDS
    assert lib.top_level()[0].name == "OTA"


def test_lvs_detects_wrong_width():
    ly, top = build_current_mirror(w=1.0, l=0.15)
    nl, _l2n = extract_netlist(ly, top)
    wrongW = schematic_mos_netlist(
        [{"name": "M0", "kind": "nmos", "S": "VSS", "G": "GATE", "D": "GATE", "W": 2.0, "L": 0.15},
         {"name": "M1", "kind": "nmos", "S": "VSS", "G": "GATE", "D": "OUT", "W": 2.0, "L": 0.15}],
        ports=["VSS", "GATE", "OUT"], name="CMIRROR")
    assert compare(nl, wrongW) is False     # parameter mismatch caught
