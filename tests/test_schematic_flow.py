"""Schematic -> placement -> routing connected flow."""

from layout_opt.schematic import two_stage_ota, CORE_NAMES, PORT_NAMES
from layout_opt.placement import (
    hpwl, random_place, sa_place, run_flow, route_placement,
)


def test_netlist_groups_terminals_by_net():
    nets = two_stage_ota().nets()
    # VOUT ties the 2nd-stage output devices, the Miller cap, and the port.
    assert set(nets["VOUT"]) == {("M6", "D"), ("M7", "D"), ("Cc", "N"), ("VOUT", "T")}
    # n1 is the mirror diode node.
    assert ("M3", "D") in nets["n1"] and ("M3", "G") in nets["n1"]


def test_components_pins_match_netlist():
    sch = two_stage_ota()
    pos = random_place(sch, seed=0)
    comps = sch.to_components(pos)
    netlist = sch.nets()
    for c in comps:
        for net, _cell in c.abs_pins():
            assert net in netlist                      # every pin lives on a real net


def test_sa_improves_hpwl_over_random():
    sch = two_stage_ota()
    r = hpwl(sch, random_place(sch, seed=2))
    s = hpwl(sch, sa_place(sch, seed=2))
    assert s < r                                       # annealing tightens placement


def test_better_placement_gives_better_route():
    rnd = run_flow("random", seed=3)
    sa = run_flow("sa", seed=3)
    assert sa["hpwl"] < rnd["hpwl"]
    assert sa["routing"]["totalWirelength"] < rnd["routing"]["totalWirelength"]


def test_flow_routes_every_net():
    r = run_flow("sa", seed=1)
    assert r["routing"]["failed"] == []
    assert r["routing"]["converged"] is True
    assert set(r["routing"]["netNames"]) <= set(r["netlist"].keys())


def test_ports_fixed_core_moves():
    sch = two_stage_ota()
    a = sa_place(sch, seed=4)
    b = sa_place(sch, seed=5)
    for p in PORT_NAMES:
        assert a[p] == b[p]                            # I/O pads pinned to edges
    assert any(a[c] != b[c] for c in CORE_NAMES)       # core placement varies
