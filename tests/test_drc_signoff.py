"""Routing DRC + sign-off (DRC + LVS + connectivity)."""

from layout_opt.drc import check_routing, payload, DRCRules
from layout_opt.signoff import lvs, run_signoff
from layout_opt.placement import run_flow


def _net(cells, routed=True):
    return {"cells": cells, "routed": routed}


# --- DRC ---
def test_drc_detects_short():
    nets = {"A": _net([[2, 2, 0], [3, 2, 0]]), "B": _net([[2, 2, 0], [2, 3, 0]])}
    r = check_routing(nets)
    assert r.counts["short"] >= 1 and not r.clean


def test_drc_detects_corner():
    nets = {"A": _net([[2, 2, 0]]), "B": _net([[3, 3, 0]])}
    r = check_routing(nets)
    assert r.counts["corner"] == 1


def test_drc_detects_open():
    nets = {"A": _net([[0, 0, 0]], routed=False)}
    r = check_routing(nets)
    assert r.counts["open"] == 1 and not r.clean


def test_drc_detects_via_spacing():
    nets = {"A": _net([[1, 1, 0], [1, 1, 1]]), "B": _net([[2, 1, 0], [2, 1, 1]])}
    r = check_routing(nets, DRCRules(check_corner=False))
    assert r.counts["via_spacing"] >= 1


def test_drc_clean_when_far_apart():
    nets = {"A": _net([[0, 0, 0], [1, 0, 0]]), "B": _net([[8, 8, 0], [9, 8, 0]])}
    r = check_routing(nets)
    assert r.clean


# --- LVS ---
def test_lvs_clean_route():
    nets = {"A": _net([[0, 0, 0], [1, 0, 0], [2, 0, 0]]),
            "B": _net([[0, 5, 0], [1, 5, 0], [2, 5, 0]])}
    pins = [{"id": "D1.A#0", "net": "A", "cell": [0, 0]},
            {"id": "D2.A#0", "net": "A", "cell": [2, 0]},
            {"id": "D1.B#0", "net": "B", "cell": [0, 5]},
            {"id": "D2.B#0", "net": "B", "cell": [2, 5]}]
    r = lvs(pins, nets)
    assert r["clean"] and not r["shorts"] and not r["opens"]


def test_lvs_flags_short_on_overlap():
    nets = {"A": _net([[0, 0, 0], [1, 0, 0]]), "B": _net([[1, 0, 0], [2, 0, 0]])}
    pins = [{"id": "D1.A#0", "net": "A", "cell": [0, 0]},
            {"id": "D1.B#0", "net": "B", "cell": [2, 0]}]
    r = lvs(pins, nets)
    assert r["shorts"] and not r["clean"]


def test_lvs_flags_open_when_net_fragmented():
    # net A's two terminals sit on disconnected metal -> open.
    nets = {"A": _net([[0, 0, 0], [9, 9, 0]])}
    pins = [{"id": "D1.A#0", "net": "A", "cell": [0, 0]},
            {"id": "D2.A#0", "net": "A", "cell": [9, 9]}]
    r = lvs(pins, nets)
    assert r["opens"] and not r["clean"]


# --- full sign-off on the real flow ---
def test_signoff_passes_for_sa_flow():
    f = run_flow("sa", seed=1)
    so = f["signoff"]
    assert so["verdict"] == "PASS"
    names = {c["name"] for c in so["checks"]}
    assert names == {"Connectivity", "LVS", "DRC"}
    assert so["lvs"]["clean"] and so["drcErrors"] == 0


def test_signoff_lvs_matches_schematic_device_count():
    f = run_flow("sa", seed=2)
    assert f["signoff"]["lvs"]["nDevicesChecked"] == 15      # M1-M7, Cc, 7 ports
    assert f["signoff"]["lvs"]["nSchematicNets"] == 10
