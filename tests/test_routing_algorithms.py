"""Negotiated-congestion + multi-layer routing, and the realistic scenarios.

Answers 'is fixed-order A* enough?': on a congested case it strands nets, while
PathFinder negotiation routes all of them order-independently.
"""

from layout_opt.maze import Grid, negotiated_route, route_diff_pair, route_all
from layout_opt.comparator import build_comparator
from layout_opt.mlroute import (
    Grid3, astar3, route_net3, route_all3, negotiated_route3,
)
from layout_opt.scenarios import run_case, CASES


# --- multi-layer A* kernel ---
def test_astar3_uses_a_via_to_cross():
    g = Grid3(5, 5, layers=2)
    # Wall off layer 0 with a vertical block; the only way past is via layer 1.
    g.block_rect_layer(2, 0, 2, 4, 0)
    path = astar3(g, {(0, 2, 0)}, {(4, 2, 0)}, g.blocked)
    assert path is not None
    assert any(c[2] == 1 for c in path)             # had to hop to layer 1


def test_route_net3_two_pins():
    g = Grid3(8, 8, layers=2)
    nr = route_net3(g, [(0, 0, 0), (7, 7, 0)], g.blocked)
    assert nr.routed and nr.wirelength >= 14


# --- negotiated congestion beats fixed order where it counts ---
def test_negotiated_routes_all_where_fixed_strands_a_net():
    r = run_case("macro_power_grid")
    fixed = r["algos"]["fixed"]
    neg = r["algos"]["negotiated"]
    assert len(fixed["failed"]) >= 1                # fixed order strands a net
    assert neg["failed"] == []                      # negotiation routes all
    assert neg["converged"] is True
    assert neg["overused"] == 0                     # no shorts left


def test_negotiated_routes_the_whole_bus():
    r = run_case("bus_channel")
    f, n = r["algos"]["fixed"], r["algos"]["negotiated"]
    assert n["failed"] == []                              # negotiation routes the whole bus
    # and is no worse than fixed order on (unrouted, vias)
    assert (len(n["failed"]), n["totalVias"]) <= (len(f["failed"]), f["totalVias"])


def test_negotiated_route3_converges_clean():
    from layout_opt.scenarios import macro_power_grid
    g, nets, _ = macro_power_grid()
    sol = negotiated_route3(g, nets)
    assert sol.converged and not sol.overused and not sol.failed


# --- differential-pair matching ---
def test_matched_pair_is_more_tightly_coupled():
    r = run_case("diff_pair")
    indep = r["variants"]["independent"]
    matched = r["variants"]["matched"]
    assert indep["routed"] and matched["routed"]
    assert matched["coupled"] > indep["coupled"]    # bundle hugs together
    assert matched["mismatch"] <= 4                 # near length-matched


# --- 2-D negotiated router still solves a feasible single-layer case ---
def test_negotiated_2d_routes_comparator():
    grid, nets = build_comparator()
    sol = negotiated_route(grid, nets)
    assert sol.failed == []


# --- payload shape for the webapp ---
def test_run_case_payload_shape():
    for c in CASES:
        r = run_case(c["key"])
        assert {"width", "height", "blocked", "info", "kind"} <= set(r)
        if r["kind"] == "multinet":
            assert set(r["algos"]) == {"fixed", "best", "negotiated"}
        else:
            assert set(r["variants"]) == {"independent", "matched"}
