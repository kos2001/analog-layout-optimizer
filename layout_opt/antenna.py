"""Antenna check: per-net metal-to-gate area ratio (a real sign-off rule).

During fabrication, metal connected to a transistor gate before that net reaches
a diffusion (which would clamp it) collects plasma charge across the whole metal
area and dumps it through the thin gate oxide — too much area per gate area can
rupture the oxide. Foundries cap the ratio of *connected metal area* to
*connected gate area*, cumulatively as each metal layer is etched.

Here we extract the routed netlist and, for every gate net, accumulate metal area
(met1 -> met1+met2 -> met1+met2+met3) over the gate-oxide area (poly ∩ diff) on
that net, flagging any net over the limit. Pure geometry from the real layout —
the same quantity a foundry antenna deck computes.
"""

from __future__ import annotations

import klayout.db as db

from .klayout_lvs import extract_netlist

DEFAULT_RATIO_LIMIT = 400.0          # cumulative metal/gate area (illustrative)
_METALS = ("met1", "met2", "met3")


def _top_circuit(nl: db.Netlist, cell_name: str):
    c = nl.circuit_by_name(cell_name)
    if c is not None:
        return c
    return next(iter(nl.each_circuit()))      # fallback: first circuit


def antenna_check(layout: db.Layout, cell: db.Cell,
                  ratio_limit: float = DEFAULT_RATIO_LIMIT) -> dict:
    """Per-gate-net cumulative metal/gate-oxide area ratios vs the antenna limit."""
    nl, l2n = extract_netlist(layout, cell)
    dbu2 = layout.dbu ** 2
    poly = l2n.layer_by_name("poly")
    metals = [(n, l2n.layer_by_name(n)) for n in _METALS]
    diff_idx = layout.find_layer(65, 20)
    diff = db.Region(cell.begin_shapes_rec(diff_idx)); diff.merge()

    nets, worst = [], 0.0
    for net in _top_circuit(nl, cell.name).each_net():
        gate_area = (l2n.shapes_of_net(net, poly) & diff).area() * dbu2
        if gate_area <= 0:                    # not a gate net -> no antenna risk
            continue
        cum, layers = 0.0, []
        for name, ml in metals:
            cum += l2n.shapes_of_net(net, ml).area() * dbu2
            ratio = cum / gate_area
            layers.append({"upto": name, "metal_um2": round(cum, 4), "ratio": round(ratio, 1)})
        net_max = max(l["ratio"] for l in layers)
        worst = max(worst, net_max)
        nets.append({"net": net.expanded_name(), "gate_um2": round(gate_area, 4),
                     "max_ratio": round(net_max, 1),
                     "violation": net_max > ratio_limit, "layers": layers})
    nets.sort(key=lambda r: -r["max_ratio"])
    return {"tool": "KLayout antenna (per-net metal/gate area ratio)",
            "cell": cell.name, "ratio_limit": ratio_limit,
            "clean": all(not n["violation"] for n in nets),
            "worst_ratio": round(worst, 1),
            "violations": sum(n["violation"] for n in nets), "nets": nets}


def antenna_ota(ratio_limit: float = DEFAULT_RATIO_LIMIT) -> dict:
    from .ota_layout import build_ota
    ly, top, _s, _c = build_ota(with_cap=True)
    return antenna_check(ly, top, ratio_limit)
