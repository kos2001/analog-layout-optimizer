"""Maze router: A* grid routing for nets, with net-order optimization.

This is the *combinatorial* side of routing-as-optimization (the structured
router in routing.py only tuned continuous knobs). Here:

  * the routing surface is a grid with static obstacles (blockages, keep-outs);
  * each net is connected as a rectilinear tree by repeatedly running A* from
    the net's growing tree to its nearest unconnected pin (Lee/maze routing);
  * A* minimizes wirelength with a small bend penalty (fewer corners);
  * nets are routed sequentially - a routed net becomes an obstacle for later
    nets, so the *order* nets are routed in changes the total wirelength and
    even feasibility. Choosing that order is itself a discrete optimization.

Pure Python, no Virtuoso. Grid coordinates are integers (x, y).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from itertools import permutations

Cell = tuple[int, int]

BEND_PENALTY = 0.5   # extra cost for a 90-degree turn (prefers straight wires)
_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class Grid:
    width: int
    height: int
    blocked: set[Cell] = field(default_factory=set)

    def in_bounds(self, c: Cell) -> bool:
        x, y = c
        return 0 <= x < self.width and 0 <= y < self.height

    def block_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                if self.in_bounds((x, y)):
                    self.blocked.add((x, y))


def _manhattan_to_nearest(c: Cell, targets: set[Cell]) -> int:
    x, y = c
    return min(abs(x - tx) + abs(y - ty) for tx, ty in targets)


def astar(
    grid: Grid,
    sources: set[Cell],
    targets: set[Cell],
    blocked: set[Cell],
) -> list[Cell] | None:
    """Shortest rectilinear path from any source to any target avoiding blocked.

    Returns the path (inclusive of endpoints) or None if unreachable.
    State is (cell, incoming-direction) so the bend penalty can be applied.
    """
    if not sources or not targets:
        return None
    tset = set(targets)
    # Priority queue of (f, g, cell, dir_index, parent_key)
    start_items = []
    for s in sources:
        if s in blocked and s not in tset:
            continue
        h = _manhattan_to_nearest(s, tset)
        start_items.append((h, 0.0, s, -1))
    if not start_items:
        return None

    open_heap: list = []
    came_from: dict = {}
    best_g: dict = {}
    for h, g, s, d in start_items:
        key = (s, d)
        best_g[key] = g
        came_from[key] = None
        heapq.heappush(open_heap, (h, g, s, d))

    while open_heap:
        f, g, cell, d = heapq.heappop(open_heap)
        if cell in tset:
            # Reconstruct.
            path = [cell]
            key = (cell, d)
            while came_from.get(key) is not None:
                pcell, pdir = came_from[key]
                path.append(pcell)
                key = (pcell, pdir)
            path.reverse()
            return path
        if g > best_g.get((cell, d), float("inf")):
            continue
        x, y = cell
        for di, (dx, dy) in enumerate(_DIRS):
            nxt = (x + dx, y + dy)
            if not grid.in_bounds(nxt):
                continue
            if nxt in blocked and nxt not in tset:
                continue
            step = 1.0 + (BEND_PENALTY if (d != -1 and di != d) else 0.0)
            ng = g + step
            nkey = (nxt, di)
            if ng < best_g.get(nkey, float("inf")):
                best_g[nkey] = ng
                came_from[nkey] = (cell, d)
                nh = _manhattan_to_nearest(nxt, tset)
                heapq.heappush(open_heap, (ng + nh, ng, nxt, di))
    return None


@dataclass
class NetRoute:
    net: str
    cells: set[Cell] = field(default_factory=set)
    wirelength: int = 0          # number of wire segments (edges)
    bends: int = 0
    routed: bool = True


def _count_bends(path: list[Cell]) -> int:
    bends = 0
    for i in range(2, len(path)):
        ax, ay = path[i - 2]
        bx, by = path[i - 1]
        cx, cy = path[i]
        if (bx - ax, by - ay) != (cx - bx, cy - by):
            bends += 1
    return bends


def route_net(grid: Grid, pins: list[Cell], blocked: set[Cell]) -> NetRoute:
    """Connect all *pins* into one rectilinear tree, avoiding *blocked*.

    Grows the tree by routing the nearest still-unconnected pin to the current
    tree each step (a simple, deterministic Steiner-tree heuristic).
    """
    nr = NetRoute(net="")
    if not pins:
        return nr
    tree: set[Cell] = {pins[0]}
    nr.cells = {pins[0]}
    remaining = list(pins[1:])

    while remaining:
        # Pick the unconnected pin closest (Manhattan) to the current tree.
        remaining.sort(key=lambda p: _manhattan_to_nearest(p, tree))
        pin = remaining.pop(0)
        # Other nets' wires block us, but our own tree is routable.
        eff_blocked = blocked - tree
        path = astar(grid, set(tree), {pin}, eff_blocked)
        if path is None:
            nr.routed = False
            return nr
        nr.bends += _count_bends(path)
        nr.wirelength += len(path) - 1
        for c in path:
            tree.add(c)
            nr.cells.add(c)
    return nr


@dataclass
class RouteSolution:
    order: list[str]
    routes: dict[str, NetRoute] = field(default_factory=dict)
    total_wirelength: int = 0
    total_bends: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def all_routed(self) -> bool:
        return not self.failed


def route_all(
    grid: Grid,
    nets: dict[str, list[Cell]],
    order: list[str],
) -> RouteSolution:
    """Route nets sequentially in *order*; each routed net blocks later ones."""
    sol = RouteSolution(order=list(order))
    occupied: set[Cell] = set()
    for net in order:
        blocked = grid.blocked | occupied
        nr = route_net(grid, nets[net], blocked)
        nr.net = net
        sol.routes[net] = nr
        if nr.routed:
            # The net's wires (minus its own pins, which other nets won't use)
            # become obstacles for subsequent nets.
            occupied |= nr.cells
            sol.total_wirelength += nr.wirelength
            sol.total_bends += nr.bends
        else:
            sol.failed.append(net)
    return sol


def optimize_net_order(
    grid: Grid,
    nets: dict[str, list[Cell]],
    max_perm: int = 720,
) -> RouteSolution:
    """Search net orderings; minimize (failures, wirelength, bends).

    Brute-forces all permutations when there are few nets (<= 6 -> 720), else
    falls back to a greedy nearest-first heuristic ordering.
    """
    keys = list(nets.keys())
    best: RouteSolution | None = None

    def score(s: RouteSolution):
        return (len(s.failed), s.total_wirelength, s.total_bends)

    import math
    if math.factorial(len(keys)) <= max_perm:
        candidates = permutations(keys)
    else:
        # Greedy: order by span (largest bounding-box pin spread first).
        def span(net: str) -> int:
            xs = [p[0] for p in nets[net]]
            ys = [p[1] for p in nets[net]]
            return (max(xs) - min(xs)) + (max(ys) - min(ys))
        candidates = [sorted(keys, key=span, reverse=True)]

    for order in candidates:
        sol = route_all(grid, nets, list(order))
        if best is None or score(sol) < score(best):
            best = sol
    assert best is not None
    return best
