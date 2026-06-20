"""Realistic routing scenarios — the cases that actually stress a router.

Multi-net cases (bus, macro+power-grid) route on a **2-layer** surface (H/V +
vias) because single-layer routing can't cross two nets. Three algorithms run
on each so the trade-offs are visible:

  * fixed-order A*           — naive sequential maze routing (order = net order)
  * best-order A*            — search net orderings (the NP-hard combinatorial fix)
  * negotiated (PathFinder)  — order-independent rip-up-and-reroute

The differential-pair case routes on one layer to compare *matched* vs
*independent* topology (length/skew, coupling).

These mirror real work: a bus squeezing through a channel between macros, global
signals dodging a power grid over hard IP blocks, and a length-matched pair.
"""

from __future__ import annotations

import math
import time
from itertools import permutations

from .maze import Cell, Grid, route_diff_pair
from .mlroute import Cell3, Grid3, route_all3, negotiated_route3


# --------------------------------------------------------------------------
# 1. Congested bus through a channel between two hard macros (2-layer)
# --------------------------------------------------------------------------
def bus_channel() -> tuple[Grid3, dict[str, list[Cell3]], dict]:
    W, H = 50, 30
    g = Grid3(W, H, layers=2)
    g.block_rect(16, 0, 27, 8)     # top macro (both layers)
    g.block_rect(16, 21, 27, 29)   # bottom macro
    nets: dict[str, list[Cell3]] = {}
    # 10-bit bus, source rows fanned wide -> must funnel through the channel and
    # fan back out. Endpoints on layer 0.
    rows_left = [2, 4, 6, 8, 11, 18, 21, 23, 25, 27]
    rows_right = [4, 6, 8, 10, 12, 17, 19, 21, 23, 25]
    for i, (rl, rr) in enumerate(zip(rows_left, rows_right)):
        nets[f"D{i}"] = [(0, rl, 0), (W - 1, rr, 0)]
    info = {"key": "bus_channel", "title": "Congested bus through a macro channel",
            "desc": "10-bit bus funnels through a narrow channel between two hard "
                    "macros. Net order decides who gets the short tracks; "
                    "negotiation shares them without an order."}
    return g, nets, info


# --------------------------------------------------------------------------
# 2. Hard macros + power grid; global signals route around (2-layer)
# --------------------------------------------------------------------------
def macro_power_grid() -> tuple[Grid3, dict[str, list[Cell3]], dict]:
    W, H = 44, 30
    g = Grid3(W, H, layers=2)
    # Four hard IP macros leave a '+'-shaped routing channel (cols 19..24,
    # rows 13..16) that every cross-chip signal must funnel through.
    g.block_rect(0, 0, 18, 12)
    g.block_rect(25, 0, 43, 12)
    g.block_rect(0, 17, 18, 29)
    g.block_rect(25, 17, 43, 29)

    def in_channel(x: int, y: int) -> bool:
        return (13 <= y <= 16) or (19 <= x <= 24)

    # Power grid: VDD straps on layer 0 (H), VSS on layer 1 (V), kept out of the
    # channel so it stays the bottleneck. Straps block their layer except gaps.
    for y in range(6, H, 7):
        for x in range(W):
            if x % 5 != 2 and not in_channel(x, y):
                g.blocked.add((x, y, 0))
    for x in range(5, W, 7):
        for y in range(H):
            if y % 7 != 3 and not in_channel(x, y):
                g.blocked.add((x, y, 1))

    nets: dict[str, list[Cell3]] = {}
    pairs = [((2, 14), (42, 14)), ((42, 15), (2, 16)), ((21, 1), (22, 28)),
             ((2, 13), (42, 16)), ((42, 13), (2, 15)), ((20, 2), (23, 27)),
             ((3, 15), (41, 13)), ((41, 16), (3, 13))]
    for i, (s, t) in enumerate(pairs):
        nets[f"S{i}"] = [_free_near(g, s), _free_near(g, t)]
    info = {"key": "macro_power_grid", "title": "Signals through a macro channel + power grid",
            "desc": "8 cross-chip signals funnel through the '+' channel between "
                    "four hard macros, over a 2-layer power grid. Fixed-order A* "
                    "clogs the channel and strands a net; negotiation reroutes all."}
    return g, nets, info


def _free_near(g: Grid3, xy: tuple[int, int]) -> Cell3:
    """Nearest unblocked layer-0 cell to (x,y)."""
    from collections import deque
    start = (xy[0], xy[1], 0)
    if g.in_bounds(start) and start not in g.blocked:
        return start
    seen = {start}
    q = deque([start])
    while q:
        x, y, l = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy, 0)
            if n in seen:
                continue
            seen.add(n)
            if g.in_bounds(n) and n not in g.blocked:
                return n
            q.append(n)
    return start


# --------------------------------------------------------------------------
# 3. Differential pair: matched vs independent (single layer)
# --------------------------------------------------------------------------
def diff_pair() -> tuple[Grid, list[Cell], list[Cell], dict]:
    W, H = 40, 22
    g = Grid(W, H)
    # A device the pair must run past (lower region). Pins are symmetric, so the
    # contrast is *coupling*: independent A* routes INP and INN on non-adjacent
    # tracks (a gap between them -> loose, asymmetric coupling); matched routing
    # pulls INN to hug INP as a tightly-coupled bundle, for a tiny length cost.
    g.block_rect(18, 12, 24, 16)
    pins_p = [(1, 8), (W - 1, 8)]
    pins_n = [(1, 10), (W - 1, 10)]
    info = {"key": "diff_pair", "title": "Differential pair: matched vs independent",
            "desc": "INP/INN from source to load. Independent A* leaves them on "
                    "non-adjacent tracks (coupling 0 -> skew/CMRR loss); matched "
                    "routing keeps them a tightly-coupled bundle for +2 length."}
    return g, pins_p, pins_n, info


# --------------------------------------------------------------------------
# Run the algorithms
# --------------------------------------------------------------------------
def _best_order3(g: Grid3, nets: dict[str, list[Cell3]]):
    keys = list(nets.keys())
    if math.factorial(len(keys)) <= 24:        # <=4 nets: brute force is cheap
        cands = permutations(keys)
    else:
        def span(n):
            xs = [p[0] for p in nets[n]]; ys = [p[1] for p in nets[n]]
            return (max(xs) - min(xs)) + (max(ys) - min(ys))
        cands = [sorted(keys, key=span, reverse=True)]
    best = None
    for o in cands:
        s = route_all3(g, nets, list(o))
        key = (len(s.failed), s.total_wirelength, s.total_vias)
        if best is None or key < best[0]:
            best = (key, s, list(o))
    return best[1], best[2]


def _ml_payload(g: Grid3, nets: dict[str, list[Cell3]], algo: str) -> dict:
    t0 = time.perf_counter()
    order = None
    if algo == "fixed":
        s = route_all3(g, nets, list(nets.keys())); order = s.algo and list(nets.keys())
    elif algo == "best":
        s, order = _best_order3(g, nets)
    else:
        s = negotiated_route3(g, nets)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    out = {"algo": algo, "ms": ms, "totalWirelength": s.total_wirelength,
           "totalVias": s.total_vias, "failed": s.failed,
           "nets": {n: {"pins": [list(p) for p in nets[n]],
                        "cells": [list(c) for c in sorted(r.cells)],
                        "wirelength": r.wirelength, "vias": r.vias,
                        "routed": r.routed}
                    for n, r in s.routes.items()}}
    if algo == "negotiated":
        out.update(iterations=s.iterations, converged=s.converged,
                   overused=len(s.overused))
    else:
        out["order"] = order
    return out


def run_case(key: str) -> dict:
    if key == "diff_pair":
        g, pp, pn, info = diff_pair()
        out = {"width": g.width, "height": g.height,
               "blocked": [list(c) for c in sorted(g.blocked)],
               "info": info, "kind": "diffpair", "variants": {}}
        for matched in (False, True):
            pr = route_diff_pair(g, pp, pn, g.blocked, matched=matched)
            out["variants"]["matched" if matched else "independent"] = {
                "matched": matched, "mismatch": pr.mismatch, "coupled": pr.coupled,
                "routed": pr.routed, "lenA": pr.a.wirelength, "lenB": pr.b.wirelength,
                "nets": {
                    "INP": {"pins": [list(p) for p in pp],
                            "cells": [list(c) for c in sorted(pr.a.cells)],
                            "wirelength": pr.a.wirelength, "routed": pr.a.routed},
                    "INN": {"pins": [list(p) for p in pn],
                            "cells": [list(c) for c in sorted(pr.b.cells)],
                            "wirelength": pr.b.wirelength, "routed": pr.b.routed},
                }}
        return out

    builders = {"bus_channel": bus_channel, "macro_power_grid": macro_power_grid}
    g, nets, info = builders[key]()
    return {"width": g.width, "height": g.height, "layers": g.layers,
            "blocked": [list(c) for c in sorted(g.blocked)],
            "info": info, "kind": "multinet", "netNames": list(nets.keys()),
            "algos": {a: _ml_payload(g, nets, a)
                      for a in ("fixed", "best", "negotiated")}}


CASES = [
    {"key": "bus_channel", "title": "Congested bus / channel"},
    {"key": "macro_power_grid", "title": "Macros + power grid"},
    {"key": "diff_pair", "title": "Differential pair matching"},
]
