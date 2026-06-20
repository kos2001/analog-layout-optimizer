"""Connectivity-driven placement + routing for a schematic.

Placement minimizes HPWL (half-perimeter wirelength) — the standard placement
cost — by simulated annealing, the classic analog/digital placer (TimberWolf
lineage). HPWL correlates with routed wirelength, so a better placement yields a
better route: that's the concrete link between *placement* and *routing*. The
netlist comes from `schematic` so all three stages stay consistent.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .interactive import Component
from .mlroute import Grid3, negotiated_route3
from .schematic import CORE_NAMES, PORT_NAMES, Schematic, two_stage_ota
from . import drc as _drc
from . import signoff as _signoff
from . import parasitics as _par

W, H = 40, 28                      # placement / routing grid (cells)

# Fixed I/O + supply pads on the perimeter (top-level pins are placed at edges).
PORT_POS: dict[str, tuple[int, int]] = {
    "VINP": (0, 6), "VINN": (0, 20), "VOUT": (39, 13),
    "VBIAS": (6, 27), "VBIASP": (33, 0), "VDD": (19, 0), "VSS": (19, 27),
}
# Inner region the core devices are placed within (leave a routing margin).
_RX, _RY, _RW, _RH = 4, 3, 32, 22


def _abs_pins(sch: Schematic, pos: dict[str, tuple[int, int]]) -> dict[str, list[tuple[int, int]]]:
    """net -> [pin cells] for the current placement."""
    nets: dict[str, list[tuple[int, int]]] = {}
    for c in sch.to_components(pos):
        for net, cell in c.abs_pins():
            nets.setdefault(net, []).append(cell)
    return nets


def hpwl(sch: Schematic, pos: dict[str, tuple[int, int]]) -> int:
    """Total half-perimeter wirelength over all nets."""
    total = 0
    for cells in _abs_pins(sch, pos).values():
        if len(cells) < 2:
            continue
        xs = [c[0] for c in cells]; ys = [c[1] for c in cells]
        total += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return total


def _wh(sch: Schematic) -> dict[str, tuple[int, int]]:
    return {d.name: (d.w, d.h) for d in sch.devices}


def _overlap(pos, wh, names, margin: int = 1) -> int:
    """Total overlapping area among the given devices (footprints + margin)."""
    over = 0
    items = [(n, pos[n], wh[n]) for n in names]
    for i in range(len(items)):
        ni, (xi, yi), (wi, hi) = items[i]
        for j in range(i + 1, len(items)):
            nj, (xj, yj), (wj, hj) = items[j]
            ox = min(xi + wi + margin, xj + wj + margin) - max(xi, xj)
            oy = min(yi + hi + margin, yj + hj + margin) - max(yi, yj)
            if ox > 0 and oy > 0:
                over += ox * oy
    return over


def _clamp_core(x, y, w, h):
    x = max(_RX, min(x, _RX + _RW - w))
    y = max(_RY, min(y, _RY + _RH - h))
    return x, y


def random_place(sch: Schematic = None, seed: int = 0) -> dict[str, tuple[int, int]]:
    sch = sch or two_stage_ota()
    rng = random.Random(seed)
    wh = _wh(sch)
    pos = dict(PORT_POS)
    for n in CORE_NAMES:
        w, h = wh[n]
        for _ in range(200):
            x = rng.randint(_RX, _RX + _RW - w)
            y = rng.randint(_RY, _RY + _RH - h)
            pos[n] = (x, y)
            if _overlap(pos, wh, [m for m in CORE_NAMES if m in pos]) == 0:
                break
    return pos


def sa_place(sch: Schematic = None, seed: int = 0, iters: int = 6000) -> dict[str, tuple[int, int]]:
    """Simulated-annealing placement minimizing HPWL + overlap penalty."""
    sch = sch or two_stage_ota()
    rng = random.Random(seed)
    wh = _wh(sch)
    pos = random_place(sch, seed)
    OV = 50

    def cost(p):
        return hpwl(sch, p) + OV * _overlap(p, wh, CORE_NAMES)

    cur = cost(pos)
    T0, T1 = 12.0, 0.05
    for k in range(iters):
        T = T0 * (T1 / T0) ** (k / iters)
        n = rng.choice(CORE_NAMES)
        w, h = wh[n]
        old = pos[n]
        if rng.random() < 0.5:                      # local perturbation
            nx, ny = old[0] + rng.randint(-3, 3), old[1] + rng.randint(-3, 3)
        else:                                       # global jump
            nx, ny = rng.randint(_RX, _RX + _RW - w), rng.randint(_RY, _RY + _RH - h)
        pos[n] = _clamp_core(nx, ny, w, h)
        new = cost(pos)
        if new <= cur or rng.random() < math.exp((cur - new) / max(T, 1e-6)):
            cur = new
        else:
            pos[n] = old
    return pos


# --------------------------------------------------------------------------
# Routing the placement (multi-layer negotiated)
# --------------------------------------------------------------------------
def _grid3_nets(comps: list[Component]):
    g = Grid3(W, H, layers=2)
    for c in comps:
        x = max(0, min(c.x, W - c.w)); y = max(0, min(c.y, H - c.h))
        g.block_rect(x, y, x + c.w - 1, y + c.h - 1)
    nets: dict[str, list[tuple[int, int, int]]] = {}
    for c in comps:
        for net, (px, py) in c.abs_pins():
            g.blocked.discard((px, py, 0))
            nets.setdefault(net, []).append((px, py, 0))
    nets = {n: ps for n, ps in nets.items() if len({(p[0], p[1]) for p in ps}) >= 2}
    return g, nets


def route_placement(comps: list[Component]) -> dict:
    g, nets = _grid3_nets(comps)
    sol = negotiated_route3(g, nets)
    net_payload = {n: {"pins": [list(p) for p in nets[n]],
                       "cells": [list(c) for c in sorted(r.cells)],
                       "wirelength": r.wirelength, "vias": r.vias, "routed": r.routed}
                   for n, r in sol.routes.items()}
    return {
        "blocked": [list(c) for c in sorted(g.blocked)],
        "netNames": list(nets.keys()),
        "totalWirelength": sol.total_wirelength, "totalVias": sol.total_vias,
        "failed": sol.failed, "converged": sol.converged, "iterations": sol.iterations,
        "nets": net_payload,
        "drc": _drc.payload(net_payload),
    }


def run_flow(place: str = "sa", seed: int = 0, sizing=None) -> dict:
    """Schematic -> placement -> routing -> sign-off, end to end.

    `sizing` (OpAmpParams) is used for the post-layout re-sim; defaults to the
    representative DEMO_SIZING when not supplied by an upstream sizing stage.
    """
    sch = two_stage_ota()
    pos = sa_place(sch, seed) if place == "sa" else random_place(sch, seed)
    comps = sch.to_components(pos)
    routing = route_placement(comps)
    netlist = {net: [f"{d}.{t}" for d, t in conns]
               for net, conns in sch.nets().items()}
    # Per-terminal pin list (device terminal + its net + layout cell) for LVS.
    lvs_pins = []
    for c in comps:
        for i, (net, cell) in enumerate(c.abs_pins()):
            lvs_pins.append({"id": f"{c.id}.{net}#{i}", "net": net, "cell": list(cell)})
    signoff = _signoff.run_signoff(lvs_pins, routing)
    return {
        "width": W, "height": H, "layers": 2, "place": place,
        "hpwl": hpwl(sch, pos),
        "netlist": netlist,
        "components": [{"id": c.id, "label": c.label, "x": c.x, "y": c.y,
                        "w": c.w, "h": c.h, "kind": next(d.kind for d in sch.devices if d.name == c.id),
                        "pins": [{"net": p.net, "dx": p.dx, "dy": p.dy} for p in c.pins]}
                       for c in comps],
        "routing": routing,
        "signoff": signoff,
        "postlayout": _par.post_layout_from_routing(
            routing, p=sizing) if sizing is not None
        else _par.post_layout_from_routing(routing),
    }
