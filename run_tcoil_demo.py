#!/usr/bin/env python3
"""Demo: T-coil bandwidth extension (analytic, no Virtuoso).

Run:  python run_tcoil_demo.py

Compares the bare RC load, shunt peaking, and an optimized bridged T-coil, and
draws their magnitude responses as an ASCII Bode plot.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout_opt.tcoil import TCoilParams, bandwidth, bw_extension, optimize_tcoil, transimpedance


def ascii_bode(curves: dict[str, TCoilParams], width=60, height=16) -> str:
    w = np.logspace(-1, 1.2, width)  # 0.1 .. ~16 rad/s
    rows = []
    # dB grid from +3 to -12 dB
    top_db, bot_db = 3.0, -15.0
    mags = {name: 20 * np.log10(np.abs(transimpedance(p, w)) + 1e-12)
            for name, p in curves.items()}
    glyph = {name: name[0] for name in curves}
    grid = [[" " for _ in range(width)] for _ in range(height)]
    for name, mdb in mags.items():
        for xi in range(width):
            yv = (top_db - mdb[xi]) / (top_db - bot_db) * (height - 1)
            yi = int(round(yv))
            if 0 <= yi < height:
                grid[yi][xi] = glyph[name]
    # -3 dB line
    y3 = int(round((top_db - (-3.0)) / (top_db - bot_db) * (height - 1)))
    for xi in range(width):
        if grid[y3][xi] == " ":
            grid[y3][xi] = "."
    for yi, row in enumerate(grid):
        db = top_db - yi / (height - 1) * (top_db - bot_db)
        label = f"{db:5.1f}dB " if yi % 3 == 0 or yi == y3 else "        "
        rows.append(label + "".join(row))
    rows.append("        " + "0.1" + " " * (width - 9) + "16 rad/s")
    return "\n".join(rows)


def main() -> int:
    none = TCoilParams(0.0, 0.0, 0.0)
    shunt = TCoilParams(0.5, 0.0, 0.0)
    flat = optimize_tcoil(peak_limit_db=0.1, seed=0)
    peaky = optimize_tcoil(peak_limit_db=3.0, seed=0)

    print("=== T-coil bandwidth extension (R = C_L = 1, reference BW = 1) ===\n")
    rows = [
        ("no coil (RC)", none, bw_extension(none)),
        ("shunt peaking", shunt, bw_extension(shunt)),
        ("T-coil, max-flat", flat.params, flat.bw_extension),
        ("T-coil, 3dB peak", peaky.params, peaky.bw_extension),
    ]
    print(f"  {'config':18}{'L':>7}{'k':>7}{'Cb':>7}{'BW(x)':>9}")
    for name, p, ext in rows:
        print(f"  {name:18}{p.L:7.3f}{p.k:7.3f}{p.Cb:7.3f}{ext:9.2f}")

    print(f"\n  max-flat T-coil: {flat.bw_extension:.2f}x bandwidth, "
          f"peaking {flat.peaking_db:.2f} dB (textbook T-coil ~2.8-3x).")

    print("\nMagnitude response (n=no coil, s=shunt, T=max-flat T-coil):")
    print(ascii_bode({"none": none, "shunt": shunt, "Tcoil": flat.params}))
    print("\n(Closed-form Z(s)=V_T/I_in derived analytically; bandwidth read off "
          "the -3dB crossing. Real coils need EM/Spectre for L,k,Q extraction.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
