#!/usr/bin/env python3
"""Demo: maze-route a StrongARM comparator's nets (no Virtuoso).

Run:  python run_maze_comparator_demo.py

A StrongARM comparator: a clocked tail device, a differential input pair, and a
cross-coupled latch driving OUTP/OUTN. We place the devices as blockages on a
routing grid, give each net its pins, and route them with the A* maze router.

Because nets are routed sequentially (a routed net blocks later ones), the net
ORDER changes total wirelength and feasibility -> net ordering is itself a
discrete optimization, which optimize_net_order searches.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout_opt.comparator import W, H, build_comparator
from layout_opt.maze import Grid, route_all, optimize_net_order


def render(grid: Grid, sol) -> str:
    """ASCII picture: '#' blockage, net initial for its wire, '*' pin, '.' free."""
    glyph = {n: n[0] for n in sol.routes}  # first letter per net
    chars = [["." for _ in range(grid.width)] for _ in range(grid.height)]
    for (x, y) in grid.blocked:
        chars[y][x] = "#"
    for net, nr in sol.routes.items():
        if not nr.routed:
            continue
        for (x, y) in nr.cells:
            if chars[y][x] in (".",):
                chars[y][x] = glyph[net].lower()
    # pins on top
    g2, nets = build_comparator()
    for net, pins in nets.items():
        for (x, y) in pins:
            chars[y][x] = glyph[net].upper()
    # y increasing downward for display
    return "\n".join("".join(row) for row in chars)


def main() -> int:
    grid, nets = build_comparator()
    print(f"=== StrongARM comparator routing on a {W}x{H} grid "
          f"({len(nets)} nets) ===\n")

    naive = route_all(grid, nets, list(nets.keys()))
    print(f"Naive order {naive.order}:")
    print(f"  total wirelength = {naive.total_wirelength}, bends = {naive.total_bends}, "
          f"failed = {naive.failed or 'none'}\n")

    best = optimize_net_order(grid, nets)
    print(f"Optimized order {best.order}:")
    print(f"  total wirelength = {best.total_wirelength}, bends = {best.total_bends}, "
          f"failed = {best.failed or 'none'}")

    # Worst feasible order, for contrast (the routing-quality spread).
    from itertools import permutations
    worst = max(
        (route_all(grid, nets, list(o)) for o in permutations(nets.keys())),
        key=lambda s: (len(s.failed), s.total_wirelength),
    )
    print(f"\nWorst order {worst.order}: wirelength = {worst.total_wirelength}, "
          f"failed = {worst.failed or 'none'}")
    if best.all_routed:
        delta = worst.total_wirelength - best.total_wirelength
        print(f"  => choosing the net order saves {delta} segments "
              f"({100*delta/max(worst.total_wirelength,1):.0f}%) vs the worst ordering.")

    print("\nPer-net (optimized):")
    for net in best.order:
        nr = best.routes[net]
        status = f"wl={nr.wirelength} bends={nr.bends}" if nr.routed else "FAILED"
        print(f"  {net:5} : {status}")

    print("\nLayout (#=device, lowercase=net wire, UPPER=pin):")
    print(render(grid, best))
    print("\n(A* shortest-path per net + net-order search = the discrete "
          "routing-optimization layer; real routers add layers/vias and "
          "rip-up & reroute.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
