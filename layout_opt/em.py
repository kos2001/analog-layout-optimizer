"""Electromigration (EM) check: DC current density vs metal width.

A wire carrying steady current degrades by electromigration if its current
density exceeds the metal's limit. The foundry gives a max DC current per unit
width (J_max, mA/um) per layer; a net's routed width must satisfy
    width >= I_dc / J_max.

This check ties the *layout* back to the *sizing*: the OTA's bias currents set
each net's DC current, and we measure the narrowest metal the router used on
that net. Power/bias rails (VDD, VSS, tail) carry the most current and are the
ones at risk if routed on minimum-width metal.

J_max values are illustrative (order-of-magnitude SKY130 DC limits); the check
itself — current from sizing, width from geometry, density vs limit — is real.
"""

from __future__ import annotations

import klayout.db as db

from .klayout_lvs import extract_netlist
from .opamp import OpAmpParams

# Illustrative DC current-density limits (mA per um of width).
JMAX_PER_UM = {"met1": 1.0, "met2": 1.0, "met3": 2.0}
_VIA_MAX_UM = 0.25                    # ignore via-sized squares when measuring wire width


def branch_currents(p: OpAmpParams) -> dict:
    """DC current (A) per OTA net from the sizing (two-stage Miller OTA topology)."""
    i1 = p.itail / 2.0                # each input/mirror branch
    return {
        "VDD": p.itail + p.i6,        # M3+M4 sources + M7 source
        "VSS": p.itail + p.i6,        # M5 source + M6 source (return)
        "TAIL": p.itail,              # M5 drain -> M1/M2 sources
        "n1": i1, "n2": i1,           # mirror / input-pair drains
        "VOUT": p.i6,                 # output branch (M6/M7)
    }


def _min_wire_width(region: db.Region, dbu: float) -> float | None:
    """Narrowest wire dimension (um) on a net's layer, ignoring via-sized squares."""
    widths = []
    for poly in region.merged().each():
        b = poly.bbox()
        w, h = b.width() * dbu, b.height() * dbu
        if w <= _VIA_MAX_UM and h <= _VIA_MAX_UM:
            continue                  # via/contact stub, not a routing wire
        widths.append(min(w, h))
    return min(widths) if widths else None


def em_check(params: OpAmpParams = None) -> dict:
    """Measure each current-carrying net's narrowest metal and check J vs J_max."""
    from .ota_layout import build_ota
    params = params or _default_params()
    ly, top, _s, _c = build_ota(params=params, with_cap=True)
    nl, l2n = extract_netlist(ly, top)
    dbu = ly.dbu
    currents = branch_currents(params)

    cir = nl.circuit_by_name(top.name) or next(iter(nl.each_circuit()))
    by_name = {net.expanded_name(): net for net in cir.each_net()}

    nets, worst = [], 0.0
    for name, i_a in sorted(currents.items(), key=lambda kv: -kv[1]):
        net = by_name.get(name)
        if net is None:
            continue
        i_ma = i_a * 1e3
        per_layer, cap_ma = [], None
        for ln, jmax in JMAX_PER_UM.items():
            w = _min_wire_width(l2n.shapes_of_net(net, l2n.layer_by_name(ln)), dbu)
            if w is None:
                continue
            layer_cap = w * jmax
            cap_ma = layer_cap if cap_ma is None else min(cap_ma, layer_cap)
            per_layer.append({"layer": ln, "min_width_um": round(w, 3),
                              "capacity_mA": round(layer_cap, 4)})
        if cap_ma is None:
            continue
        density = i_ma / cap_ma
        worst = max(worst, density)
        nets.append({"net": name, "current_mA": round(i_ma, 4),
                     "capacity_mA": round(cap_ma, 4),
                     "density_pct": round(density * 100, 1),
                     "violation": density > 1.0, "layers": per_layer})
    return {"tool": "EM DC current-density check (I from sizing, width from layout)",
            "jmax_per_um_mA": JMAX_PER_UM,
            "clean": all(not n["violation"] for n in nets),
            "worst_density_pct": round(worst * 100, 1),
            "violations": sum(n["violation"] for n in nets), "nets": nets}


def _default_params() -> OpAmpParams:
    from .opamp_opt import de_log_refine
    return de_log_refine(seed=0).params
