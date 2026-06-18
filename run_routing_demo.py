#!/usr/bin/env python3
"""Demo: routing optimization for the differential pair (no Virtuoso).

Run:  python run_routing_demo.py

Routes the interdigitated diff pair with net rails + stubs + vias, then
optimizes the routing parameters (rail width / pitch / via size) to minimize
wirelength + metal area subject to metal DRC and connectivity.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout_opt.generator import DesignParams, DiffPairConfig
from layout_opt.routing import (
    RoutingParams,
    connectivity_ok,
    optimize_routing,
    route,
    routed_layout,
    routing_violations,
)
from layout_opt.skill import emit_skill

CFG = DiffPairConfig(nf=4)
P = DesignParams(w_finger=0.5, l=0.03, finger_pitch=0.18, guard_gap=0.20, gr_width=0.05)


def report(tag: str, rp: RoutingParams) -> None:
    res = route(P, rp, CFG)
    viols = routing_violations(rp)
    print(f"  [{tag}] rail_w={rp.rail_width:.3f} pitch={rp.rail_pitch:.3f} "
          f"via={rp.via_size:.3f}")
    print(f"        wirelength={res.wirelength:.3f} µm  metal_area={res.metal_area:.4f} µm²  "
          f"vias={res.via_count}  connected={connectivity_ok(res, CFG)}  "
          f"DRC={'clean' if not viols else viols}")


def main() -> int:
    print("=== Differential-pair routing (nets: VINP/VINN gates, VOUTN/VOUTP "
          "drains, VTAIL source) ===\n")

    loose = RoutingParams(rail_width=0.20, rail_pitch=0.45, via_size=0.10)
    print("Before optimization (loose, DRC-clean but wasteful):")
    report("loose", loose)

    print("\nOptimizing routing (minimize wirelength + metal area s.t. DRC)…")
    opt = optimize_routing(P, CFG, seed=0, maxiter=120)
    print("After optimization:")
    report("opt", opt.params)

    base = route(P, loose, CFG)
    print(f"\n  => wirelength {base.wirelength:.2f} → {opt.wirelength:.2f} µm "
          f"({100*(1-opt.wirelength/base.wirelength):.0f}% shorter), "
          f"metal area {base.metal_area:.3f} → {opt.metal_area:.3f} µm² "
          f"({100*(1-opt.metal_area/base.metal_area):.0f}% less).")

    lay = routed_layout(P, opt.params, CFG)
    cmds = emit_skill(lay)
    print(f"\n=== Full routed layout: {len(lay.rects)} shapes "
          f"(device {len(lay.rects)-5-48}, rails 5, stubs 24, vias 24) ===")
    print(f"  emits {len(cmds)} SKILL commands; first routing rail:")
    rail_cmd = emit_skill_first_on(lay, "M2")
    print(f"    {rail_cmd}")
    print("\n  (Same swap-the-backend story: real routing parasitics/DRC would "
          "come from\n   Virtuoso PEX + DRC; this loop optimizes the geometry "
          "without it.)")
    return 0


def emit_skill_first_on(lay, layer: str) -> str:
    from layout_opt.skill import emit_skill
    for r, cmd in zip(lay.rects, emit_skill(lay)):
        if r.layer == layer:
            return cmd
    return "(none)"


if __name__ == "__main__":
    raise SystemExit(main())
