"""Engine speedups must not change results.

The fast kernels (flat-index A*, incremental SA cost, spatially hashed via DRC)
are checked against straightforward reference implementations, and DRC is
checked to be reproducible across interpreter hash seeds.
"""

import math
import os
import random
import subprocess
import sys
from pathlib import Path

from layout_opt import drc
from layout_opt.mlroute import Grid3, _route_net_idx, _Surface, route_net3
from layout_opt.placement import (
    CORE_NAMES, _RH, _RW, _RX, _RY, _clamp_core, _overlap, _wh,
    crit_hpwl, hpwl, random_place, sa_place, symmetry_penalty,
)
from layout_opt.schematic import two_stage_ota

ROOT = Path(__file__).resolve().parent.parent


def _random_grid(seed, size=24, n_nets=8):
    rng = random.Random(seed)
    g = Grid3(size, size, layers=2)
    for _ in range(size):
        x, y = rng.randrange(size - 1), rng.randrange(size - 1)
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


def test_flat_router_matches_tuple_router_hard_blocked():
    for seed in range(5):
        g, nets = _random_grid(seed)
        sf = _Surface(g)
        occupied: set = set()
        for pins in nets.values():
            blocked = g.blocked | occupied
            ref = route_net3(g, pins, blocked)
            fast = _route_net_idx(sf, pins, sf.blockmap(blocked))
            assert (fast.routed, fast.cells, fast.wirelength, fast.vias) == \
                   (ref.routed, ref.cells, ref.wirelength, ref.vias)
            occupied |= ref.cells


def test_flat_router_matches_tuple_router_with_congestion_cost():
    for seed in range(5):
        g, nets = _random_grid(seed)
        sf = _Surface(g)
        rng = random.Random(seed)
        hist_d = {(x, y, l): float(rng.randrange(3)) for x in range(g.width)
                  for y in range(g.height) for l in range(2) if rng.random() < 0.2}
        occ_d = {c: rng.randrange(3) for c in hist_d if rng.random() < 0.5}
        hist, occ = [0.0] * sf.n, [0] * sf.n
        for c, v in hist_d.items():
            hist[sf.idx(c)] = v
        for c, v in occ_d.items():
            occ[sf.idx(c)] = v
        for pins in nets.values():
            mine = set(pins)

            def cost(c, _mine=mine):
                return 0.0 if c in _mine else hist_d.get(c, 0.0) + 0.85 * occ_d.get(c, 0)

            ref = route_net3(g, pins, g.blocked, cost)
            fast = _route_net_idx(sf, pins, sf.base, hist, occ, 0.85)
            assert (fast.routed, fast.cells, fast.wirelength, fast.vias) == \
                   (ref.routed, ref.cells, ref.wirelength, ref.vias)


def _reference_sa(seed, iters, analog_aware, w_crit=12.0, w_sym=6.0):
    """The original full-recompute annealer the incremental version replaced."""
    sch = two_stage_ota()
    rng = random.Random(seed)
    wh = _wh(sch)
    pos = random_place(sch, seed)

    def cost(p):
        c = hpwl(sch, p) + 50 * _overlap(p, wh, CORE_NAMES, margin=2 if analog_aware else 1)
        if analog_aware:
            c += w_crit * crit_hpwl(sch, p) + w_sym * symmetry_penalty(p, wh)
        return c

    cur = cost(pos)
    for k in range(iters):
        T = 12.0 * (0.05 / 12.0) ** (k / iters)
        n = rng.choice(CORE_NAMES)
        w, h = wh[n]
        old = pos[n]
        if rng.random() < 0.5:
            nx, ny = old[0] + rng.randint(-3, 3), old[1] + rng.randint(-3, 3)
        else:
            nx, ny = rng.randint(_RX, _RX + _RW - w), rng.randint(_RY, _RY + _RH - h)
        pos[n] = _clamp_core(nx, ny, w, h)
        new = cost(pos)
        if new <= cur or rng.random() < math.exp((cur - new) / max(T, 1e-6)):
            cur = new
        else:
            pos[n] = old
    return pos


def test_incremental_sa_matches_full_recompute():
    for seed in (0, 3):
        for aa in (False, True):
            assert sa_place(seed=seed, iters=1500, analog_aware=aa) == \
                   _reference_sa(seed, 1500, aa)


def _brute_via_spacing(nets, min_sp):
    vias = {}
    for net, nr in nets.items():
        layers = {}
        for x, y, l in nr["cells"]:
            layers.setdefault((x, y), set()).add(l)
        vias[net] = {xy for xy, ls in layers.items() if len(ls) > 1}
    items = [(n, xy) for n, xys in vias.items() for xy in xys]
    return sum(1 for i in range(len(items)) for j in range(i + 1, len(items))
               if items[i][0] != items[j][0]
               and max(abs(items[i][1][0] - items[j][1][0]),
                       abs(items[i][1][1] - items[j][1][1])) < min_sp)


def test_hashed_via_spacing_matches_pairwise():
    rng = random.Random(11)
    nets = {}
    for i in range(12):
        cells = []
        for _ in range(30):
            x, y = rng.randrange(40), rng.randrange(40)
            cells += [[x, y, 0], [x, y, 1]]
        nets[f"n{i}"] = {"cells": cells, "routed": True}
    for sp in (1, 2, 3, 5):
        got = drc.check_routing(nets, drc.DRCRules(min_via_spacing=sp)).counts["via_spacing"]
        assert got == _brute_via_spacing(nets, sp)


_DRC_SNIPPET = """
import random
from layout_opt import drc
rng = random.Random(5)
nets = {}
for i in range(20):
    cells = []
    for _ in range(40):
        x, y = rng.randrange(30), rng.randrange(30)
        cells += [[x, y, 0], [x, y, 1]]
    nets[f"net{i}"] = {"cells": cells, "routed": True}
print(drc.payload(nets)["counts"])
"""


def test_drc_counts_do_not_depend_on_hash_seed():
    outs = set()
    for seed in ("1", "2", "3", "4"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(ROOT))
        outs.add(subprocess.run([sys.executable, "-c", _DRC_SNIPPET], env=env,
                                capture_output=True, text=True, check=True).stdout)
    assert len(outs) == 1
