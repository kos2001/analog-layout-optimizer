#!/usr/bin/env python3
"""End-to-end demo of the Virtuoso-free analog layout optimization flow.

Run:  python run_demo.py

Does four things, none of which need Virtuoso:
  1. Optimize the differential-pair geometry (area s.t. DRC + drive spec).
  2. Report the best parameters and the resulting area / DRC status.
  3. Generate the layout and print its shape inventory.
  4. Emit the SKILL that *would* build it in Virtuoso (the only deferred step).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout_opt.evaluate import evaluate
from layout_opt.generator import DiffPairConfig, PDKRules, generate_layout
from layout_opt.optimize import optimize
from layout_opt.skill import emit_skill


def main() -> int:
    cfg = DiffPairConfig(nf=4)
    rules = PDKRules()

    print("=== 1. Optimize (no Virtuoso) ===")
    opt = optimize(cfg=cfg, rules=rules, seed=0, maxiter=200)
    p = opt.params
    print(f"  evaluations : {opt.n_evals}")
    print(f"  w_finger    : {p.w_finger:.4f} um   (spec floor {cfg.w_min_total/cfg.nf:.4f})")
    print(f"  L           : {p.l:.4f} um   (DRC floor {rules.min_l})")
    print(f"  poly_pitch  : {p.finger_pitch:.4f} um   (DRC floor {rules.min_poly_pitch})")
    print(f"  guard_gap   : {p.guard_gap:.4f} um   (DRC floor {rules.min_gr_gap})")
    print(f"  gr_width    : {p.gr_width:.4f} um   (DRC floor {rules.min_gr_width})")

    print("\n=== 2. Result ===")
    r = opt.result
    print(f"  bbox area   : {r.area:.4f} um^2")
    print(f"  DRC clean   : {r.is_clean}   penalty={r.penalty:.3g}")
    if r.violations:
        for v in r.violations:
            print(f"    - {v}")

    print("\n=== 3. Generated layout ===")
    lay = generate_layout(p, cfg)
    x0, y0, x1, y1 = lay.bbox()
    print(f"  cell name   : {lay.name}")
    print(f"  shapes      : {len(lay.rects)}  "
          f"(OD={len(lay.rects_on('OD'))}, PO={len(lay.rects_on('PO'))}, M1={len(lay.rects_on('M1'))})")
    print(f"  bbox        : ({x0:.3f}, {y0:.3f}) -> ({x1:.3f}, {y1:.3f})")

    print("\n=== 4. SKILL to build it in Virtuoso (deferred step) ===")
    cmds = emit_skill(lay)
    for c in cmds[:4]:
        print(f"  {c}")
    print(f"  ... ({len(cmds)} commands total)")
    print("\n  To run for real once a Virtuoso server is reachable:")
    print("    from virtuoso_bridge import VirtuosoClient")
    print("    client = VirtuosoClient.from_env()")
    print("    with client.layout.edit(lib, cell) as lay:")
    print("        for cmd in emit_skill(layout): lay.add(cmd)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
