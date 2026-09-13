"""Engine scaling benchmark: router, DRC and placement runtimes vs. design size.

Generates deterministic synthetic designs of increasing size and times each
engine. Use it to catch performance regressions before they reach a real flow:

    python scripts/bench_engines.py            # default size ladder
    python scripts/bench_engines.py --quick    # smallest sizes only
    python scripts/bench_engines.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from layout_opt import drc  # noqa: E402
from layout_opt.mlroute import Grid3, negotiated_route3  # noqa: E402
from layout_opt.placement import run_flow, sa_place  # noqa: E402


def synthetic_design(size: int, n_nets: int, seed: int = 0):
    """Square Grid3 with 2x2 blockages and 3-pin nets on unique free cells."""
    rng = random.Random(seed)
    g = Grid3(size, size, layers=2)
    for _ in range(size * size // 60):
        x, y = rng.randrange(size - 2), rng.randrange(size - 2)
        g.block_rect(x, y, x + 1, y + 1)
    used: set = set()
    nets = {}
    for i in range(n_nets):
        pins = []
        while len(pins) < 3:
            c = (rng.randrange(size), rng.randrange(size), 0)
            if c not in g.blocked and c not in used:
                used.add(c)
                pins.append(c)
        nets[f"n{i}"] = pins
    return g, nets


def via_heavy_payload(n_nets: int, vias_per_net: int, size: int, seed: int = 0):
    """Routing payload with many vias (both layers at one x,y) for DRC stress."""
    rng = random.Random(seed)
    nets = {}
    for i in range(n_nets):
        cells = []
        for _ in range(vias_per_net):
            x, y = rng.randrange(size), rng.randrange(size)
            cells += [[x, y, 0], [x, y, 1]]
        nets[f"n{i}"] = {"cells": cells, "routed": True}
    return nets


def _time(fn):
    t = time.perf_counter()
    out = fn()
    return time.perf_counter() - t, out


def bench(sizes):
    rows = []
    for size, n_nets in sizes:
        g, nets = synthetic_design(size, n_nets)
        t_route, sol = _time(lambda: negotiated_route3(g, nets))
        payload = {n: {"cells": list(r.cells), "routed": r.routed}
                   for n, r in sol.routes.items()}
        t_drc, res = _time(lambda: drc.payload(payload, drc.DRCRules(min_via_spacing=2)))
        rows.append({"grid": f"{size}x{size}x2", "nets": n_nets,
                     "route_s": round(t_route, 3), "drc_s": round(t_drc, 3),
                     "iterations": sol.iterations, "failed": len(sol.failed),
                     "wirelength": sol.total_wirelength, "drc_total": res["total"]})
        print(f"{rows[-1]['grid']:>12} nets={n_nets:<4} route={t_route:7.3f}s "
              f"drc={t_drc:6.3f}s iters={sol.iterations} failed={len(sol.failed)} "
              f"wl={sol.total_wirelength}", flush=True)
    for n_nets, vpn in ((50, 40), (100, 100)):
        payload = via_heavy_payload(n_nets, vpn, size=400)
        t_drc, res = _time(lambda: drc.payload(payload, drc.DRCRules(min_via_spacing=2)))
        rows.append({"drc_stress_vias": n_nets * vpn, "drc_s": round(t_drc, 3),
                     "drc_total": res["total"]})
        print(f"DRC stress vias={n_nets * vpn:<6} drc={t_drc:7.3f}s total={res['total']}",
              flush=True)
    t_sa, _ = _time(lambda: sa_place(seed=0, iters=20000, analog_aware=True))
    t_flow, _ = _time(lambda: run_flow(seed=0))
    print(f"sa_place(20k iters)={t_sa:.3f}s  run_flow={t_flow:.3f}s")
    return {"engines": rows, "sa_place_20k_s": round(t_sa, 3),
            "run_flow_s": round(t_flow, 3)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="small sizes only")
    ap.add_argument("--json", help="write results to this file")
    args = ap.parse_args(argv)
    sizes = [(40, 20)] if args.quick else [(40, 20), (80, 60)]
    result = bench(sizes)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
