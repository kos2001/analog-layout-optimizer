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

W, H = 52, 36                      # placement / routing grid (cells)

# Fixed I/O + supply pads on the perimeter (top-level pins are placed at edges),
# spread out so each net has room to escape its device pin to its pad.
PORT_POS: dict[str, tuple[int, int]] = {
    "VINP": (0, 10), "VINN": (0, 26), "VOUT": (W - 1, 18),
    "VBIAS": (8, H - 1), "VBIASP": (W - 9, 0), "VDD": (W // 2, 0), "VSS": (W // 2, H - 1),
}
# Inner region the core devices are placed within (leave a routing margin).
_RX, _RY, _RW, _RH = 6, 5, 40, 26


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


# --- op-amp layout-quality knobs ---------------------------------------------
# High-impedance gain nodes: parasitic C here costs the most phase margin
# (post-layout), so keep their nets short.
CRITICAL_NETS = {"n1", "n2"}

# Nets routed before all others: the post-layout PM model keys on the n2 and
# VOUT parasitics, so they get first claim on the short, low-via paths.
ROUTE_PRIORITY = ("n2", "VOUT", "n1")
# Matched device pairs that want a symmetric / abutted placement for matching
# (random offsets between them => offset/CMRR and gain-error in a diff amp).
MATCHED_PAIRS = [("M1", "M2"), ("M3", "M4")]


def crit_hpwl(sch: Schematic, pos: dict) -> int:
    """HPWL over the gain-critical (high-impedance) nets only."""
    total = 0
    for net, cells in _abs_pins(sch, pos).items():
        if net in CRITICAL_NETS and len(cells) >= 2:
            xs = [c[0] for c in cells]; ys = [c[1] for c in cells]
            total += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return total


def symmetry_penalty(pos: dict, wh: dict) -> float:
    """Penalty for matched pairs not being mirror-symmetric (same row, centered)."""
    cx = _RX + _RW / 2
    pen = 0.0
    for a, b in MATCHED_PAIRS:
        if a in pos and b in pos:
            ca = pos[a][0] + wh[a][0] / 2
            cb = pos[b][0] + wh[b][0] / 2
            pen += abs((ca + cb) / 2 - cx)        # pair centroid on the symmetry axis
            pen += abs(pos[a][1] - pos[b][1])     # same row
    return pen


def matching_metrics(sch: Schematic, pos: dict) -> dict:
    """Op-amp layout-quality metrics: symmetry, matched-pair distance, crit-net WL."""
    wh = _wh(sch)
    pairs = {}
    for a, b in MATCHED_PAIRS:
        if a in pos and b in pos:
            ca = (pos[a][0] + wh[a][0] / 2, pos[a][1] + wh[a][1] / 2)
            cb = (pos[b][0] + wh[b][0] / 2, pos[b][1] + wh[b][1] / 2)
            pairs[f"{a}/{b}"] = round(((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5, 2)
    return {"symmetry_penalty": round(symmetry_penalty(pos, wh), 2),
            "critical_wl": crit_hpwl(sch, pos),
            "pair_distance": pairs}


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


def sa_place(sch: Schematic = None, seed: int = 0, iters: int = 6000,
             analog_aware: bool = False, w_crit: float = 12.0,
             w_sym: float = 6.0) -> dict[str, tuple[int, int]]:
    """Simulated-annealing placement minimizing HPWL + overlap penalty.

    `analog_aware` adds op-amp layout objectives: weight the gain-critical
    high-impedance nets (n1/n2) so they stay short (less parasitic -> more phase
    margin) and pull matched pairs (input pair, mirror) into a symmetric,
    abutted placement (matching -> lower offset / gain error).
    """
    sch = sch or two_stage_ota()
    rng = random.Random(seed)
    wh = _wh(sch)
    pos = random_place(sch, seed)
    OV = 50

    def cost(p):
        # analog_aware pulls devices together (symmetry/critical nets), which
        # starves the router of channels: demand one extra free cell between
        # devices (margin=2) so every net keeps a routing path.
        c = hpwl(sch, p) + OV * _overlap(p, wh, CORE_NAMES,
                                         margin=2 if analog_aware else 1)
        if analog_aware:
            c += w_crit * crit_hpwl(sch, p) + w_sym * symmetry_penalty(p, wh)
        return c

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
    # PM-critical nets route first (dict order == routing order downstream).
    rank = {n: i for i, n in enumerate(ROUTE_PRIORITY)}
    nets = {n: nets[n] for n in sorted(nets, key=lambda n: rank.get(n, len(rank)))}
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


def run_flow(place: str = "sa", seed: int = 0, sizing=None,
             analog_aware: bool = False) -> dict:
    """Schematic -> placement -> routing -> sign-off, end to end.

    `sizing` (OpAmpParams) is used for the post-layout re-sim; defaults to the
    representative DEMO_SIZING when not supplied by an upstream sizing stage.
    `analog_aware` turns on op-amp placement objectives (matching + critical-net).
    """
    sch = two_stage_ota()
    pos = (sa_place(sch, seed, analog_aware=analog_aware) if place == "sa"
           else random_place(sch, seed))
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
        "matching": matching_metrics(sch, pos),
        "analogAware": analog_aware,
    }
