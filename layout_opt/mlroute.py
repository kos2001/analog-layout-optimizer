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
           hard_blocked: set[Cell3], cell_cost=None,
           passable: set[Cell3] = frozenset()) -> list[Cell3] | None:
    """Shortest 3-D rectilinear path (planar moves + vias) source->target.

    ``passable`` cells are exempt from ``hard_blocked`` (e.g. the net's own
    tree), which avoids materializing ``hard_blocked - passable`` per call.
    """
    if not sources or not targets:
        return None
    tset = set(targets)
    open_heap: list = []
    came: dict = {}
    best_g: dict = {}
    push, pop = heapq.heappush, heapq.heappop
    inf = float("inf")
    W, H, L = grid.width, grid.height, grid.layers
    if len(tset) == 1:
        (tx0, ty0, _), = tset

        def hfun(x, y):
            return abs(x - tx0) + abs(y - ty0)
    else:
        tpts = [(tx, ty) for tx, ty, _ in tset]

        def hfun(x, y):
            return min(abs(x - tx) + abs(y - ty) for tx, ty in tpts)

    def blocked(c):
        return c in hard_blocked and c not in tset and c not in passable

    for s in sources:
        if blocked(s):
            continue
        key = (s, -1)
        best_g[key] = 0.0
        came[key] = None
        push(open_heap, (hfun(s[0], s[1]), 0.0, s, -1))

    while open_heap:
        f, g, cell, d = pop(open_heap)
        if cell in tset:
            path = [cell]
            key = (cell, d)
            while came.get(key) is not None:
                pcell, pdir = came[key]
                path.append(pcell)
                key = (pcell, pdir)
            path.reverse()
            return path
        if g > best_g.get((cell, d), inf):
            continue
        x, y, l = cell
        pref_h = l % 2 == 0
        # Planar moves on this layer.
        for di, (dx, dy) in enumerate(_PLANAR):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < W and 0 <= ny < H):
                continue
            nxt = (nx, ny, l)
            if blocked(nxt):
                continue
            step = 1.0
            if d != -1 and di != d:
                step += BEND_PENALTY
            if (dx != 0) != pref_h:
                step += OFFDIR_PENALTY
            if cell_cost is not None:
                step += cell_cost(nxt)
            ng = g + step
            nkey = (nxt, di)
            if ng < best_g.get(nkey, inf):
                best_g[nkey] = ng
                came[nkey] = (cell, d)
                push(open_heap, (ng + hfun(nx, ny), ng, nxt, di))
        # Via moves (change layer, same x,y).
        for dl in (1, -1):
            nl = l + dl
            if not 0 <= nl < L:
                continue
            nxt = (x, y, nl)
            if blocked(nxt):
                continue
            step = VIA_COST + (cell_cost(nxt) if cell_cost is not None else 0.0)
            ng = g + step
            nkey = (nxt, d)            # via keeps the last planar direction
            if ng < best_g.get(nkey, inf):
                best_g[nkey] = ng
                came[nkey] = (cell, d)
                push(open_heap, (ng + hfun(x, y), ng, nxt, d))
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
        path = astar3(grid, tree, {pin}, hard_blocked, cell_cost=cell_cost,
                      passable=tree)
        if path is None:
            # An unroutable net is an OPEN — it has no manufactured geometry, so
            # drop the partial tree (else its stub fakes a short against others).
            nr.routed = False
            nr.cells = set()
            nr.wirelength = 0
            nr.vias = 0
            return nr
        nr.wirelength += sum(1 for i in range(1, len(path)) if path[i][2] == path[i - 1][2])
        nr.vias += _count_vias(path)
        for c in path:
            tree.add(c)
            nr.cells.add(c)
    return nr


# --------------------------------------------------------------------------
# Flat-index kernel. The router's hot loop spends most of its time hashing
# (x, y, layer) tuples and calling a Python cost closure. Here a cell is the
# integer (x*H + y)*L + layer — which sorts exactly like the tuple, so heap
# tie-breaking and therefore every routed path are unchanged — blockages are a
# bytearray, and negotiated-congestion costs are read from flat lists.
# --------------------------------------------------------------------------
class _Surface:
    """Flat-array view of a Grid3 shared by all nets of one routing run."""

    def __init__(self, grid: Grid3):
        self.W, self.H, self.L = grid.width, grid.height, grid.layers
        self.n = self.W * self.H * self.L
        self.base = self.blockmap(grid.blocked)

    def idx(self, c: Cell3) -> int:
        return (c[0] * self.H + c[1]) * self.L + c[2]

    def cell(self, i: int) -> Cell3:
        xy, l = divmod(i, self.L)
        x, y = divmod(xy, self.H)
        return (x, y, l)

    def in_bounds(self, c: Cell3) -> bool:
        return 0 <= c[0] < self.W and 0 <= c[1] < self.H and 0 <= c[2] < self.L

    def blockmap(self, cells, into: bytearray | None = None) -> bytearray:
        blk = into if into is not None else bytearray(self.n)
        for c in cells:
            if self.in_bounds(c):
                blk[self.idx(c)] = 1
        return blk


def _astar_idx(sf: _Surface, sources, t: int, blk: bytearray, passable,
               hist=None, occ=None, pres_fac: float = 0.0, mine=()):
    """astar3 on flat indices; with ``hist`` set, applies the negotiated cost
    ``history + pres_fac * occupancy`` (0 on the net's own pins)."""
    H, L = sf.H, sf.L
    HL = H * L
    maxx, maxy = sf.W - 1, H - 1
    push, pop = heapq.heappush, heapq.heappop
    inf = float("inf")
    tx, ty = divmod(t // L, H)
    open_heap: list = []
    came: dict = {}
    best_g: dict = {}
    for s in sources:
        if blk[s] and s != t and s not in passable:
            continue
        key = s * 5                       # (cell, dir=-1) -> cell*5 + 0
        best_g[key] = 0.0
        came[key] = None
        sxy = s // L
        push(open_heap, (abs(sxy // H - tx) + abs(sxy % H - ty), 0.0, s, -1))

    while open_heap:
        f, g, i, d = pop(open_heap)
        if i == t:
            path = [i]
            key = i * 5 + d + 1
            while came[key] is not None:
                key = came[key]
                path.append(key // 5)
            path.reverse()
            return path
        key = i * 5 + d + 1
        if g > best_g.get(key, inf):
            continue
        xy, l = divmod(i, L)
        x, y = divmod(xy, H)
        horiz_pref = l % 2 == 0
        # Planar moves in _PLANAR order: +x, -x, +y, -y.
        for di in range(4):
            if di == 0:
                if x == maxx:
                    continue
                j = i + HL; nx, ny = x + 1, y
            elif di == 1:
                if x == 0:
                    continue
                j = i - HL; nx, ny = x - 1, y
            elif di == 2:
                if y == maxy:
                    continue
                j = i + L; nx, ny = x, y + 1
            else:
                if y == 0:
                    continue
                j = i - L; nx, ny = x, y - 1
            if blk[j] and j != t and j not in passable:
                continue
            step = 1.0
            if d != -1 and di != d:
                step += BEND_PENALTY
            if (di < 2) != horiz_pref:
                step += OFFDIR_PENALTY
            if hist is not None:
                step += 0.0 if j in mine else hist[j] + pres_fac * occ[j]
            ng = g + step
            nkey = j * 5 + di + 1
            if ng < best_g.get(nkey, inf):
                best_g[nkey] = ng
                came[nkey] = key
                push(open_heap, (ng + (abs(nx - tx) + abs(ny - ty)), ng, j, di))
        # Via moves (change layer, same x,y): up then down.
        for dl in (1, -1):
            nl = l + dl
            if not 0 <= nl < L:
                continue
            j = i + dl
            if blk[j] and j != t and j not in passable:
                continue
            step = VIA_COST + ((0.0 if j in mine else hist[j] + pres_fac * occ[j])
                               if hist is not None else 0.0)
            ng = g + step
            nkey = j * 5 + d + 1           # via keeps the last planar direction
            if ng < best_g.get(nkey, inf):
                best_g[nkey] = ng
                came[nkey] = key
                push(open_heap, (ng + (abs(x - tx) + abs(y - ty)), ng, j, d))
    return None


def _route_net_idx(sf: _Surface, pins: list[Cell3], blk: bytearray,
                   hist=None, occ=None, pres_fac: float = 0.0) -> NetRoute3:
    """route_net3 on the flat surface (same tree-growth order and result)."""
    nr = NetRoute3(net="")
    if not pins:
        return nr
    mine = {sf.idx(p) for p in pins} if hist is not None else ()
    tree: set[Cell3] = {pins[0]}
    tree_i: set[int] = {sf.idx(pins[0])}
    nr.cells = {pins[0]}
    remaining = list(pins[1:])
    while remaining:
        remaining.sort(key=lambda p: _h(p, tree))
        pin = remaining.pop(0)
        ipath = _astar_idx(sf, tree_i, sf.idx(pin), blk, tree_i,
                           hist, occ, pres_fac, mine)
        if ipath is None:
            nr.routed = False
            nr.cells = set()
            nr.wirelength = 0
            nr.vias = 0
            return nr
        path = [sf.cell(i) for i in ipath]
        nr.wirelength += sum(1 for i in range(1, len(path)) if path[i][2] == path[i - 1][2])
        nr.vias += _count_vias(path)
        tree_i.update(ipath)
        for c in path:
            tree.add(c)
            nr.cells.add(c)
    return nr


def _pins_in_bounds(grid: Grid3, nets: dict[str, list[Cell3]]) -> bool:
    return all(grid.in_bounds(p) for pins in nets.values() for p in pins)


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


def _pin_sets(nets: dict[str, list[Cell3]]):
    """Per-net pin set + all pin cells (to reserve foreign pins)."""
    by_net = {net: set(pins) for net, pins in nets.items()}
    allp: set[Cell3] = set()
    for s in by_net.values():
        allp |= s
    return by_net, allp


def route_all3(grid: Grid3, nets: dict[str, list[Cell3]], order: list[str]) -> MLSolution:
    """Fixed-order sequential routing: a routed net hard-blocks later nets.

    Every net's pins are reserved from all other nets, so no net can route
    *through* a foreign pin (which would otherwise create an LVS short).
    """
    sol = MLSolution(algo="fixed")
    by_net, allp = _pin_sets(nets)
    fast = _pins_in_bounds(grid, nets)
    sf = _Surface(grid) if fast else None
    occupied_blk = bytearray(sf.base) if fast else None   # blocked | occupied
    occupied: set[Cell3] = set()
    for net in order:
        foreign = allp - by_net[net]
        if fast:
            nr = _route_net_idx(sf, nets[net], sf.blockmap(foreign, bytearray(occupied_blk)))
        else:
            nr = route_net3(grid, nets[net], grid.blocked | occupied | foreign)
        nr.net = net
        sol.routes[net] = nr
        if nr.routed:
            occupied |= nr.cells
            if fast:
                sf.blockmap(nr.cells, occupied_blk)
            sol.total_wirelength += nr.wirelength
            sol.total_vias += nr.vias
        else:
            sol.failed.append(net)
    return sol


def negotiated_route3(grid: Grid3, nets: dict[str, list[Cell3]],
                      max_iter: int = 24, pres_fac0: float = 0.5,
                      pres_growth: float = 1.7, hist_fac: float = 1.0,
                      legalize_rounds: int = 16) -> MLSolution:
    """PathFinder negotiated congestion on the multi-layer surface.

    Soft cost-based negotiation resolves most contention; a final legalization
    phase hard-assigns any still-contested cell to one net and forces the others
    to detour (or fail), so a converged result has zero overlaps — a real short
    can't slip through as a "warning"."""
    by_net, allp = _pin_sets(nets)
    pres_fac = pres_fac0
    routes: dict[str, NetRoute3] = {}
    sol = MLSolution(algo="negotiated")
    fast = _pins_in_bounds(grid, nets)
    if fast:
        sf = _Surface(grid)
        hist = [0.0] * sf.n
    else:
        history: dict[Cell3, float] = {}

    for it in range(1, max_iter + 1):
        routes = {}
        if fast:
            occ_a = [0] * sf.n
            touched: set[int] = set()
        else:
            occ: dict[Cell3, int] = {}
        for net, pins in nets.items():
            # Soft loop prices contention (incl. crossing a foreign pin); any
            # residual overlap is caught below and legalized/sequentialized.
            if fast:
                nr = _route_net_idx(sf, pins, sf.base, hist, occ_a, pres_fac)
            else:
                mine = by_net[net]

                def cost(cell, _mine=mine):
                    if cell in _mine:
                        return 0.0
                    pres = pres_fac * occ.get(cell, 0)
                    return history.get(cell, 0.0) + pres

                nr = route_net3(grid, pins, grid.blocked, cost)
            nr.net = net
            routes[net] = nr
            if nr.routed:
                if fast:
                    for c in nr.cells:
                        i = sf.idx(c)
                        occ_a[i] += 1
                        touched.add(i)
                else:
                    for c in nr.cells:
                        occ[c] = occ.get(c, 0) + 1
        # Foreign pins are reserved, so any shared cell now is a real wire short.
        if fast:
            overused = [i for i in touched if occ_a[i] > 1]
            for i in overused:
                hist[i] += hist_fac
        else:
            overused = [c for c, n in occ.items() if n > 1]
            for c in overused:
                history[c] = history.get(c, 0.0) + hist_fac
        pres_fac *= pres_growth
        sol.iterations = it
        if not overused and all(r.routed for r in routes.values()):
            sol.converged = True
            break

    # Legalization: deterministically give each contested cell to one net and
    # hard-block it for the rest, rerouting them, until no overlap remains.
    if not sol.converged:
        forbidden: dict[str, set[Cell3]] = {n: set() for n in nets}
        for _ in range(legalize_rounds):
            occ_l: dict[Cell3, set] = {}
            for n, r in routes.items():
                if r.routed:
                    for c in r.cells:
                        occ_l.setdefault(c, set()).add(n)
            overused_l = {c: ns for c, ns in occ_l.items() if len(ns) > 1}
            if not overused_l and all(r.routed for r in routes.values()):
                sol.converged = True
                break
            for c, ns in overused_l.items():
                winner = min(ns)                 # deterministic owner
                for n in ns:
                    if n != winner:
                        forbidden[n].add(c)
            for net, pins in nets.items():
                foreign = allp - by_net[net]
                if fast:
                    blk = sf.blockmap(forbidden[net], sf.blockmap(foreign, bytearray(sf.base)))
                    nr = _route_net_idx(sf, pins, blk)
                else:
                    nr = route_net3(grid, pins, grid.blocked | foreign | forbidden[net])
                nr.net = net
                routes[net] = nr
        sol.iterations += 1

    # Hard guarantee: never emit a short. If any overlap survives legalization,
    # fall back to a sequential pass (each net hard-blocks prior ones -> zero
    # overlap by construction); an unroutable net becomes an honest open, never
    # a hidden short that masquerades as a clean sign-off.
    occ_chk: dict[Cell3, int] = {}
    for r in routes.values():
        if r.routed:
            for c in r.cells:
                occ_chk[c] = occ_chk.get(c, 0) + 1
    if any(n > 1 for n in occ_chk.values()):
        def _span(net):
            xs = [p[0] for p in nets[net]]; ys = [p[1] for p in nets[net]]
            return (max(xs) - min(xs)) + (max(ys) - min(ys))
        seq = route_all3(grid, nets, sorted(nets, key=_span))
        routes = seq.routes
        sol.converged = not seq.failed

    sol.routes = routes
    sol.failed = [n for n, r in routes.items() if not r.routed]
    sol.total_wirelength = sum(r.wirelength for r in routes.values() if r.routed)
    sol.total_vias = sum(r.vias for r in routes.values() if r.routed)
    occ_final: dict[Cell3, int] = {}
    for r in routes.values():
        if r.routed:
            for c in r.cells:
                occ_final[c] = occ_final.get(c, 0) + 1
    sol.overused = sorted(c for c, n in occ_final.items() if n > 1)
    return sol
