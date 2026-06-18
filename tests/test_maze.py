"""Maze router: A* correctness, obstacle avoidance, and net-order optimization."""

from layout_opt.maze import (
    Grid,
    astar,
    optimize_net_order,
    route_all,
    route_net,
)

from layout_opt.comparator import build_comparator


# --- A* ---------------------------------------------------------------------
def test_astar_straight_line():
    g = Grid(10, 3)
    path = astar(g, {(0, 1)}, {(7, 1)}, set())
    assert path is not None
    assert len(path) - 1 == 7  # wirelength = manhattan on an open grid


def test_astar_routes_around_wall():
    g = Grid(7, 5)
    g.block_rect(3, 0, 3, 3)  # wall col3 rows0-3, only row4 open
    path = astar(g, {(0, 0)}, {(6, 0)}, g.blocked)
    assert path is not None
    assert len(path) - 1 > 6   # forced detour longer than the Manhattan 6
    # path avoids every blocked cell
    assert all(c not in g.blocked for c in path)


def test_astar_unreachable_returns_none():
    g = Grid(5, 5)
    g.block_rect(2, 0, 2, 4)   # full vertical wall splits the grid
    assert astar(g, {(0, 0)}, {(4, 0)}, g.blocked) is None


# --- single-net tree --------------------------------------------------------
def test_route_net_connects_all_pins():
    g = Grid(10, 10)
    pins = [(0, 0), (9, 0), (0, 9), (9, 9)]
    nr = route_net(g, pins, set())
    assert nr.routed
    assert all(p in nr.cells for p in pins)


# --- multi-net sequential blocking -----------------------------------------
def test_earlier_net_forces_later_to_detour():
    # Net B's straight path crosses net A; routing A first makes B longer.
    # A spans rows 1-5 of a 7-tall grid, so rows 0/6 stay open for B to detour.
    g = Grid(11, 7)
    nets = {"A": [(5, 1), (5, 5)], "B": [(0, 3), (10, 3)]}
    b_alone = route_all(g, {"B": nets["B"]}, ["B"]).total_wirelength
    after = route_all(g, nets, ["A", "B"])
    assert after.routes["B"].routed         # B still routes...
    assert after.routes["B"].wirelength > b_alone   # ...but detours around A


# --- net-order optimization -------------------------------------------------
def test_net_order_changes_total_and_optimizer_minimizes():
    g, nets = build_comparator()
    best = optimize_net_order(g, nets)
    naive = route_all(g, nets, list(nets.keys()))
    assert best.all_routed
    # Optimizer is no worse than the naive ordering.
    assert (len(best.failed), best.total_wirelength) <= (
        len(naive.failed), naive.total_wirelength
    )
    # And some ordering is strictly worse than the optimum (order matters).
    from itertools import permutations
    worst = max(
        (route_all(g, nets, list(o)) for o in permutations(nets.keys())),
        key=lambda s: (len(s.failed), s.total_wirelength),
    )
    assert worst.total_wirelength > best.total_wirelength


def test_routing_is_deterministic():
    g, nets = build_comparator()
    a = route_all(g, nets, list(nets.keys()))
    b = route_all(g, nets, list(nets.keys()))
    assert a.total_wirelength == b.total_wirelength
    assert a.total_bends == b.total_bends
