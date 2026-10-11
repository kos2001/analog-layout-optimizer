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


# --- incremental PathFinder: QoR and legality on dense synthetic designs ---
def _synthetic(size, n_nets, seed):
    import random
    rng = random.Random(seed)
    g = Grid3(size, size, layers=2)
    for _ in range(size * size // 60):
        x, y = rng.randrange(size - 2), rng.randrange(size - 2)
        g.block_rect(x, y, x + 1, y + 1)
    used, nets = set(), {}
    for i in range(n_nets):
        pins = []
        while len(pins) < 3:
            c = (rng.randrange(size), rng.randrange(size), 0)
            if c not in g.blocked and c not in used:
                used.add(c)
                pins.append(c)
        nets[f"n{i}"] = pins
    return g, nets


def _shorts(sol):
    occ = {}
    for r in sol.routes.values():
        if r.routed:
            for c in r.cells:
                occ[c] = occ.get(c, 0) + 1
    return sum(1 for n in occ.values() if n > 1)


def test_negotiated_routes_dense_designs_without_shorts_or_foreign_pins():
    for seed in range(3):
        g, nets = _synthetic(60, 40, seed)
        sol = negotiated_route3(g, nets)
        assert sol.converged and not sol.failed and _shorts(sol) == 0, seed
        for net, r in sol.routes.items():
            foreign = {p for n, ps in nets.items() if n != net for p in ps}
            assert not (r.cells & foreign), (seed, net)


def test_walled_in_pin_still_converges():
    # 80x80 seed 0 has a pin whose every escape is taken by other nets' wires;
    # an incremental router that never moves legal nets deadlocks on it.
    g, nets = _synthetic(80, 60, 0)
    sol = negotiated_route3(g, nets)
    assert sol.converged and not sol.failed and _shorts(sol) == 0


def test_overcapacity_returns_opens_never_shorts():
    # Too many nets for the grid: whatever cannot route must come back as an
    # open, with no overlap, and no worse than the plain sequential pass.
    g, nets = _synthetic(40, 45, 1)
    sol = negotiated_route3(g, nets, max_iter=6)
    assert _shorts(sol) == 0 and not sol.overused
    seq = route_all3(g, nets, list(nets))
    assert len(sol.failed) <= len(seq.failed)


def test_astar_search_window_confines_the_path():
    from layout_opt.mlroute import _Surface, _route_net_idx
    g = Grid3(20, 20, layers=2)
    sf = _Surface(g)
    pins = [(5, 5, 0), (9, 5, 0)]
    inside = _route_net_idx(sf, pins, sf.base, bbox=(4, 4, 10, 6))
    assert inside.routed
    assert all(4 <= x <= 10 and 4 <= y <= 6 for x, y, _ in inside.cells)
    g.block_rect(7, 4, 7, 6)                     # wall across the window
    sf = _Surface(g)
    assert not _route_net_idx(sf, pins, sf.base, bbox=(4, 4, 10, 6)).routed
    assert _route_net_idx(sf, pins, sf.base).routed   # full grid detours
