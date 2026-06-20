"""Parasitic extraction → post-layout re-simulation.

Routing isn't free: every wire adds resistance and capacitance. Extracting R/C
from the routed geometry and feeding it back into the OTA model closes the last
loop — *layout* now affects *performance*:

  * C on the output node       adds to the load CL  -> lowers p2 -> phase margin
  * C on a high-impedance node adds a parasitic pole 1/(R·C); on the first-stage
    output (node n2, R = r1 ≈ hundreds of kΩ) even a few fF can wreck PM.

So a sloppy (long) route degrades the very specs the sizing met on the
schematic — and a tighter placement/route degrades them less. This is the
"schematic vs post-layout" gap real designers chase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .opamp import (
    CL, KP_N, KP_P, LAMBDA_N, LAMBDA_P, VDD, OpAmpParams, evaluate_opamp, _gm,
)


@dataclass(frozen=True)
class Tech:
    r_per_cell: float = 2.0        # ohm per routed cell (sheet R × 1 square)
    r_via: float = 6.0             # ohm per via
    c_area_fF: float = 0.25        # fF per cell (wire-to-substrate)
    c_couple_fF: float = 0.1       # fF per adjacent diff-net cell (coupling)


_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


def extract_parasitics(routing: dict, tech: Tech = Tech()) -> dict:
    """Per-net R/C extracted from routed cells (+ inter-net coupling)."""
    nets = routing["nets"]
    # occupancy for coupling
    owner: dict[tuple, str] = {}
    for net, nr in nets.items():
        for c in nr.get("cells", []):
            owner[(int(c[0]), int(c[1]), int(c[2]) if len(c) > 2 else 0)] = net

    out = {}
    for net, nr in nets.items():
        cells = [(int(c[0]), int(c[1]), int(c[2]) if len(c) > 2 else 0)
                 for c in nr.get("cells", [])]
        wl = nr.get("wirelength", max(0, len(cells) - 1))
        vias = nr.get("vias", 0)
        cset = set(cells)
        couple = 0
        for (x, y, l) in cells:
            for dx, dy in _ORTHO:
                n = (x + dx, y + dy, l)
                o = owner.get(n)
                if o and o != net and n not in cset:
                    couple += 1
        r_ohm = wl * tech.r_per_cell + vias * tech.r_via
        c_ff = len(cells) * tech.c_area_fF + couple * tech.c_couple_fF
        out[net] = {"R_ohm": round(r_ohm, 1), "C_fF": round(c_ff, 2),
                    "wirelength": wl, "vias": vias, "coupling": couple}
    return out


def _r1_r2(p: OpAmpParams) -> tuple[float, float]:
    i1 = p.itail / 2.0
    r1 = 1.0 / ((LAMBDA_N + LAMBDA_P) * i1)
    r2 = 1.0 / ((LAMBDA_N + LAMBDA_P) * p.i6)
    return r1, r2


def post_layout_specs(p: OpAmpParams, c_out_F: float, c_n2_F: float) -> dict:
    """Recompute gain/GBW/PM with parasitic caps on VOUT (load) and n2 (internal)."""
    i1 = p.itail / 2.0
    gm1 = _gm(KP_N, p.wl1, i1)
    gm6 = _gm(KP_N, p.wl6, p.i6)
    r1, r2 = _r1_r2(p)
    a0 = gm1 * r1 * gm6 * r2
    gbw = gm1 / p.cc                              # rad/s (set by Cc, unchanged)
    z = gm6 / p.cc
    p2 = gm6 / (CL + c_out_F)                     # heavier load -> lower p2
    pm = 90.0 - math.degrees(math.atan(gbw / p2)) - math.degrees(math.atan(gbw / z))
    p_n2 = 1.0 / (r1 * c_n2_F) if c_n2_F > 0 else float("inf")   # internal parasitic pole
    if math.isfinite(p_n2):
        pm -= math.degrees(math.atan(gbw / p_n2))
    return {"gain_db": round(20.0 * math.log10(max(a0, 1e-12)), 2),
            "gbw_mhz": round(gbw / (2 * math.pi) / 1e6, 2),
            "pm_deg": round(pm, 1),
            "p_n2_mhz": round(p_n2 / (2 * math.pi) / 1e6, 2) if math.isfinite(p_n2) else None}


# A representative feasible sizing (PM ≈ 65° on the schematic) for the demo.
DEMO_SIZING = OpAmpParams(wl1=60, wl3=24, wl5=40, wl6=200, wl7=90,
                          itail=40e-6, i6=200e-6, cc=2.4e-12)

# Which schematic net maps to which performance-critical node.
OUT_NET, N2_NET = "VOUT", "n2"


def post_layout_from_routing(routing: dict, p: OpAmpParams = DEMO_SIZING,
                             tech: Tech = Tech()) -> dict:
    """Extract parasitics from a routed flow and report pre vs post specs."""
    par = extract_parasitics(routing, tech)
    c_out = par.get(OUT_NET, {}).get("C_fF", 0.0) * 1e-15
    c_n2 = par.get(N2_NET, {}).get("C_fF", 0.0) * 1e-15
    pre_s = evaluate_opamp(p)
    pre = {"gain_db": round(pre_s.gain_db, 2),
           "gbw_mhz": round(pre_s.gbw_hz / 1e6, 2), "pm_deg": round(pre_s.pm_deg, 1)}
    post = post_layout_specs(p, c_out, c_n2)
    return {
        "pre": pre, "post": post,
        "deltaPM": round(post["pm_deg"] - pre["pm_deg"], 1),
        "critical": {"VOUT": par.get(OUT_NET, {}), "n2": par.get(N2_NET, {})},
        "parasitics": par,
        "stable": post["pm_deg"] > 45.0,
    }
