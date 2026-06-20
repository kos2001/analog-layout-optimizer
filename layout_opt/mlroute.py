"""Multi-layer negotiated-congestion router — the realistic routing model.

Single-layer maze routing can't cross two nets (they'd short). Real chips use a
metal stack: alternating preferred directions per layer (M-even horizontal,
M-odd vertical) joined by vias. That, plus PathFinder negotiated congestion, is
how production global routers actually work — and it's the honest answer to
"is plain A* enough?": A* is the per-net kernel, but you need (a) extra layers
to let nets cross and (b) congestion negotiation to share tracks without a
fixed net order.

Cells are 3-D: (x, y, layer). A via is a move between layers at a fixed (x, y).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

Cell3 = tuple[int, int, int]

BEND_PENALTY = 0.5
VIA_COST = 2.0
OFFDIR_PENALTY = 0.6     # discourage against-grain wires (H on a V layer)
_PLANAR = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class Grid3:
    width: int
    height: int
    layers: int = 2
    blocked: set[Cell3] = field(default_factory=set)

    def in_bounds(self, c: Cell3) -> bool:
        x, y, l = c
        return 0 <= x < self.width and 0 <= y < self.height and 0 <= l < self.layers

    def block_column(self, x: int, y: int) -> None:
        for l in range(self.layers):
            self.blocked.add((x, y, l))

    def block_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                self.block_column(x, y)

    def block_rect_layer(self, x0: int, y0: int, x1: int, y1: int, layer: int) -> None:
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                if self.in_bounds((x, y, layer)):
                    self.blocked.add((x, y, layer))


def _pref_horizontal(layer: int) -> bool:
    return layer % 2 == 0


def _h(c: Cell3, targets: set[Cell3]) -> int:
    x, y, _ = c
    return min(abs(x - tx) + abs(y - ty) for tx, ty, _ in targets)


def astar3(grid: Grid3, sources: set[Cell3], targets: set[Cell3],
           hard_blocked: set[Cell3], cell_cost=None) -> list[Cell3] | None:
    """Shortest 3-D rectilinear path (planar moves + vias) source->target."""
    if not sources or not targets:
        return None
    tset = set(targets)
    open_heap: list = []
    came: dict = {}
    best_g: dict = {}
    for s in sources:
        if s in hard_blocked and s not in tset:
            continue
        key = (s, -1)
        best_g[key] = 0.0
        came[key] = None
        heapq.heappush(open_heap, (_h(s, tset), 0.0, s, -1))

    while open_heap:
        f, g, cell, d = heapq.heappop(open_heap)
        if cell in tset:
            path = [cell]
            key = (cell, d)
            while came.get(key) is not None:
                pcell, pdir = came[key]
                path.append(pcell)
                key = (pcell, pdir)
            path.reverse()
            return path
        if g > best_g.get((cell, d), float("inf")):
            continue
        x, y, l = cell
        # Planar moves on this layer.
        for di, (dx, dy) in enumerate(_PLANAR):
            nxt = (x + dx, y + dy, l)
            if not grid.in_bounds(nxt) or (nxt in hard_blocked and nxt not in tset):
                continue
            step = 1.0
            if d != -1 and di != d:
                step += BEND_PENALTY
            horiz = dx != 0
            if horiz != _pref_horizontal(l):
                step += OFFDIR_PENALTY
            if cell_cost is not None:
                step += cell_cost(nxt)
            ng = g + step
            nkey = (nxt, di)
            if ng < best_g.get(nkey, float("inf")):
                best_g[nkey] = ng
                came[nkey] = (cell, d)
                heapq.heappush(open_heap, (ng + _h(nxt, tset), ng, nxt, di))
        # Via moves (change layer, same x,y).
        for dl in (1, -1):
            nxt = (x, y, l + dl)
            if not grid.in_bounds(nxt) or (nxt in hard_blocked and nxt not in tset):
                continue
            step = VIA_COST + (cell_cost(nxt) if cell_cost is not None else 0.0)
            ng = g + step
            nkey = (nxt, d)            # via keeps the last planar direction
            if ng < best_g.get(nkey, float("inf")):
                best_g[nkey] = ng
                came[nkey] = (cell, d)
                heapq.heappush(open_heap, (ng + _h(nxt, tset), ng, nxt, d))
    return None


@dataclass
class NetRoute3:
    net: str
    cells: set[Cell3] = field(default_factory=set)
    wirelength: int = 0
    vias: int = 0
    routed: bool = True


def _count_vias(path: list[Cell3]) -> int:
    return sum(1 for i in range(1, len(path)) if path[i][2] != path[i - 1][2])


def route_net3(grid: Grid3, pins: list[Cell3], hard_blocked: set[Cell3],
               cell_cost=None) -> NetRoute3:
    nr = NetRoute3(net="")
    if not pins:
        return nr
    tree: set[Cell3] = {pins[0]}
    nr.cells = {pins[0]}
    remaining = list(pins[1:])
    while remaining:
        remaining.sort(key=lambda p: _h(p, tree))
        pin = remaining.pop(0)
        eff = hard_blocked - tree
        path = astar3(grid, set(tree), {pin}, eff, cell_cost=cell_cost)
        if path is None:
            nr.routed = False
            return nr
        nr.wirelength += sum(1 for i in range(1, len(path)) if path[i][2] == path[i - 1][2])
        nr.vias += _count_vias(path)
        for c in path:
            tree.add(c)
            nr.cells.add(c)
    return nr


@dataclass
class MLSolution:
    routes: dict[str, NetRoute3] = field(default_factory=dict)
    total_wirelength: int = 0
    total_vias: int = 0
    failed: list[str] = field(default_factory=list)
    iterations: int = 0
    converged: bool = False
    overused: list[Cell3] = field(default_factory=list)
    algo: str = ""


def route_all3(grid: Grid3, nets: dict[str, list[Cell3]], order: list[str]) -> MLSolution:
    """Fixed-order sequential routing: a routed net hard-blocks later nets."""
    sol = MLSolution(algo="fixed")
    occupied: set[Cell3] = set()
    for net in order:
        nr = route_net3(grid, nets[net], grid.blocked | occupied)
        nr.net = net
        sol.routes[net] = nr
        if nr.routed:
            occupied |= nr.cells
            sol.total_wirelength += nr.wirelength
            sol.total_vias += nr.vias
        else:
            sol.failed.append(net)
    return sol


def negotiated_route3(grid: Grid3, nets: dict[str, list[Cell3]],
                      max_iter: int = 24, pres_fac0: float = 0.5,
                      pres_growth: float = 1.7, hist_fac: float = 1.0) -> MLSolution:
    """PathFinder negotiated congestion on the multi-layer surface."""
    history: dict[Cell3, float] = {}
    pin_cells = {c for pins in nets.values() for c in pins}
    pres_fac = pres_fac0
    routes: dict[str, NetRoute3] = {}
    sol = MLSolution(algo="negotiated")

    for it in range(1, max_iter + 1):
        occ: dict[Cell3, int] = {}
        routes = {}
        for net, pins in nets.items():
            mine = set(pins)

            def cost(cell, _mine=mine):
                if cell in _mine:
                    return 0.0
                pres = pres_fac * occ.get(cell, 0)
                return history.get(cell, 0.0) + pres

            nr = route_net3(grid, pins, grid.blocked, cost)
            nr.net = net
            routes[net] = nr
            if nr.routed:
                for c in nr.cells:
                    occ[c] = occ.get(c, 0) + 1
        overused = [c for c, n in occ.items() if n > 1 and c not in pin_cells]
        for c in overused:
            history[c] = history.get(c, 0.0) + hist_fac
        pres_fac *= pres_growth
        sol.iterations = it
        if not overused and all(r.routed for r in routes.values()):
            sol.converged = True
            break

    sol.routes = routes
    sol.failed = [n for n, r in routes.items() if not r.routed]
    sol.total_wirelength = sum(r.wirelength for r in routes.values() if r.routed)
    sol.total_vias = sum(r.vias for r in routes.values() if r.routed)
    occ_final: dict[Cell3, int] = {}
    for r in routes.values():
        if r.routed:
            for c in r.cells:
                occ_final[c] = occ_final.get(c, 0) + 1
    sol.overused = sorted(c for c, n in occ_final.items()
                          if n > 1 and c not in pin_cells)
    return sol
