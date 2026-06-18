#!/usr/bin/env python3
"""Demo: joint device + routing co-optimization (no Virtuoso).

Run:  python run_joint_demo.py

Optimizes device geometry and interconnect together over the FULL cell area,
and shows that optimizing the device alone underestimates the real area.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout_opt.joint import optimize_joint
from layout_opt.optimize import optimize as optimize_device
from layout_opt.skill import emit_skill
from layout_opt.routing import routed_layout


def main() -> int:
    dev = optimize_device(maxiter=120)
    print("=== Device-only optimization (ignores interconnect) ===")
    print(f"  device bbox area : {dev.result.area:.4f} µm²  <- underestimate\n")

    print("=== Joint device + routing co-optimization (8 params) ===")
    j = optimize_joint(seed=0, maxiter=150)
    print(f"  evaluations      : {j.n_evals}")
    print("  device : w=%.4f l=%.4f pitch=%.4f gap=%.4f grw=%.4f" % (
        j.device.w_finger, j.device.l, j.device.finger_pitch,
        j.device.guard_gap, j.device.gr_width))
    print("  routing: rail_w=%.4f pitch=%.4f via=%.4f" % (
        j.routing.rail_width, j.routing.rail_pitch, j.routing.via_size))
    print(f"  wirelength       : {j.wirelength:.3f} µm")
    print(f"  device part area : {j.device_area:.4f} µm²")
    print(f"  TOTAL cell area  : {j.total_area:.4f} µm²  <- the real cell")
    clean = "clean" if j.is_clean else "NOT clean"
    print(f"  status           : {clean} (device DRC ✓ routing DRC ✓ "
          f"drive-spec {'✓' if j.drive_spec_met else '✗'} "
          f"connected {'✓' if j.connected else '✗'})")

    pct = 100 * (j.total_area - dev.result.area) / dev.result.area
    print(f"\n  => the interconnect makes the real cell {pct:.0f}% larger than the")
    print(f"     device-only estimate; joint search minimizes the TRUE total.")

    lay = routed_layout(j.device, j.routing)
    print(f"\n  full routed cell = {len(lay.rects)} shapes, "
          f"{len(emit_skill(lay))} SKILL commands (ready for client.layout.edit).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
