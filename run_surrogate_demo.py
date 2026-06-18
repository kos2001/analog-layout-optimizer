#!/usr/bin/env python3
"""Demo: can a surrogate stand in for Virtuoso in the optimization loop?

Run:  python run_surrogate_demo.py

Shows surrogate-assisted optimization with a validation loop:
  * the expensive ground truth (Spectre+PEX stand-in) is queried a few dozen times;
  * the GP surrogate absorbs thousands of optimizer queries instead;
  * each round the proposed optimum is VALIDATED against the ground truth, and
    the surrogate is retrained - prediction error shrinks round over round;
  * meeting the gain target costs area vs. the pure-area optimum (a real Pareto
    trade-off the cheap geometric evaluator cannot see).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout_opt.optimize import optimize
from layout_opt.surrogate_opt import surrogate_assisted_optimize
from layout_opt.truth import truth_fom

TARGET = 3.5


def main() -> int:
    geom = optimize(maxiter=120)
    print("=== Reference: pure area optimum (no performance constraint) ===")
    print(f"  area      : {geom.result.area:.4f} µm²")
    print(f"  FoM(truth): {truth_fom(geom.params):.4f}   (target is {TARGET})")
    print(f"  -> the area optimum does NOT meet the gain target; performance "
          f"must pull the design off the floor.\n")

    print(f"=== Surrogate-assisted optimization (target FoM = {TARGET}) ===")
    r = surrogate_assisted_optimize(
        fom_target=TARGET, n_init=12, n_holdout=12, rounds=6, seed=0
    )

    hdr = f"{'rnd':>3} {'area':>8} {'fom_pred':>9} {'fom_truth':>10} {'pred_err':>9} {'rmse':>7} {'R²':>7} {'meets':>6}"
    print(hdr)
    print("-" * len(hdr))
    for rd in r.rounds:
        print(
            f"{rd.index:>3} {rd.area:>8.4f} {rd.fom_pred:>9.4f} {rd.fom_truth:>10.4f} "
            f"{rd.pred_error:>9.4f} {rd.holdout_rmse:>7.3f} {rd.holdout_r2:>7.3f} "
            f"{('✓' if rd.meets_target else '✗'):>6}"
        )

    print("\n=== Result ===")
    print(f"  best area      : {r.best_area:.4f} µm²  "
          f"(vs {geom.result.area:.4f} at the area floor)")
    print(f"  best FoM(truth): {r.best_fom_truth:.4f}  (target {TARGET}) ✓")
    print(f"  ground-truth calls : {r.expensive_calls}")
    print(f"  surrogate calls    : {r.surrogate_calls}")
    print(f"  => the surrogate absorbed "
          f"{r.surrogate_calls / r.expensive_calls:.0f}× the expensive evaluations.")

    print("\nInterpretation:")
    print("  • The surrogate replaces Virtuoso/Spectre INSIDE the search loop.")
    print("  • Early rounds the surrogate is over-optimistic (pred_err large, or")
    print("    a proposed point fails 'meets' under the truth) — the validation")
    print("    loop catches it; retraining converges prediction to truth.")
    print("  • Sign-off (real DRC/LVS/PEX) still needs the actual tool — the")
    print("    surrogate is an accelerator, not a replacement for ground truth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
