"""Transistor-level SKY130 layout synthesis for the OTA devices.

Generates real device geometry (active / poly / licon / li1 / mcon / met1, plus
nwell for PMOS) so a real LVS engine can extract MOSFETs from it. Each device
exposes met1 terminal boxes (S, D, G) that downstream routing connects per the
netlist; KLayout's device extractor then recovers the transistors (type, W, L).

This is the bridge the abstract grid router didn't cross: from net-on-a-grid to
actual transistors a layout-vs-schematic tool can check.

Layer GDS numbers are SkyWater SKY130 stream layers.
"""

from __future__ import annotations

import klayout.db as db

LAYERS = {
    "nwell": (64, 20), "diff": (65, 20), "poly": (66, 20), "licon": (66, 44),
    "li1": (67, 20), "mcon": (67, 44), "met1": (68, 20), "via": (68, 44),
    "met2": (69, 20), "via2": (69, 44), "met3": (70, 20),
    "capm": (89, 44),                       # MIM cap top plate
    "nsdm": (93, 44), "psdm": (94, 20),
}

# Geometry constants (microns) — simplified but DRC-plausible.
SD_EXT = 0.30          # source/drain diffusion extension (contact room)
POLY_EXT = 0.13        # poly overhang past active
CON = 0.085            # half contact size (0.17 um cut)
GATE_TAB = 0.40        # poly gate-contact tab height above active


def layer_index(ly: db.Layout) -> dict:
    return {k: ly.layer(*v) for k, v in LAYERS.items()}


def add_device(cell: db.Cell, li: dict, x: float, y: float, w: float, l: float,
               kind: str) -> dict:
    """Place one MOSFET at origin (x,y); return met1 terminal boxes per pin.

    Active spans the device width `w` (in y); poly gate length `l` (in x).
    Returns {"S","D","G": (x0,y0,x1,y1)} met1 terminal boxes for routing.
    """
    def box(layer, x0, y0, x1, y1):
        cell.shapes(li[layer]).insert(db.DBox(x0, y0, x1, y1))

    ax0, ax1 = x, x + 2 * SD_EXT + l
    ay0, ay1 = y, y + w
    gx0, gx1 = x + SD_EXT, x + SD_EXT + l
    box("diff", ax0, ay0, ax1, ay1)
    box("poly", gx0, ay0 - POLY_EXT, gx1, ay1 + POLY_EXT)        # gate over active
    impl = "nsdm" if kind == "nmos" else "psdm"
    box(impl, ax0 - 0.1, ay0 - 0.1, ax1 + 0.1, ay1 + 0.1)
    if kind == "pmos":
        box("nwell", ax0 - 0.18, ay0 - 0.18, ax1 + 0.18, ay1 + 0.18)

    # Source/drain contact stacks: licon -> li1 -> mcon -> met1.
    terms = {}
    for name, (mx0, mx1, cx) in (
        ("S", (ax0, gx0, ax0 + SD_EXT / 2)),
        ("D", (gx1, ax1, gx1 + SD_EXT / 2)),
    ):
        cyc = (ay0 + ay1) / 2
        box("licon", cx - CON, cyc - CON, cx + CON, cyc + CON)
        box("li1", mx0 + 0.03, ay0 + 0.03, mx1 - 0.03, ay1 - 0.03)
        box("mcon", cx - CON, cyc - CON, cx + CON, cyc + CON)
        box("met1", mx0, ay0, mx1, ay1)
        terms[name] = (mx0, ay0, mx1, ay1)

    # Gate contact: poly tab above active -> licon -> li1 -> mcon -> met1.
    # Keep the gate met1 narrow so a neighbouring S/D drop can't graze it.
    ty0, ty1 = ay1 + POLY_EXT, ay1 + POLY_EXT + GATE_TAB
    box("poly", gx0 - 0.04, ay1 + POLY_EXT - 0.01, gx1 + 0.04, ty1)
    gcx = (gx0 + gx1) / 2
    gcy = (ty0 + ty1) / 2
    gm0, gm1 = gcx - (CON + 0.015), gcx + (CON + 0.015)     # tight gate metal
    box("licon", gcx - CON, gcy - CON, gcx + CON, gcy + CON)
    box("li1", gm0, ty0, gm1, ty1)
    box("mcon", gcx - CON, gcy - CON, gcx + CON, gcy + CON)
    box("met1", gm0, ty0, gm1, ty1)
    terms["G"] = (gm0, ty0, gm1, ty1)

    terms["kind"] = kind
    terms["W"] = w
    terms["L"] = l
    return terms


def device_extent(w: float, l: float) -> tuple[float, float]:
    """(width_x, height_y) footprint of a device, including the gate tab."""
    return (2 * SD_EXT + l, w + 2 * POLY_EXT + GATE_TAB)


def n_fingers(w_total: float, wf_max: float = 2.5) -> tuple[int, float]:
    """Split a total width into (nf, finger_width) keeping each finger <= wf_max."""
    import math
    nf = max(1, math.ceil(w_total / wf_max))
    return nf, w_total / nf


def add_mf_device(cell: db.Cell, li: dict, x: float, y: float, wf: float, l: float,
                  kind: str, nf: int = 1) -> dict:
    """Multi-finger MOSFET: nf gates over one active, S/D combs tied, gates tied.

    Total width = nf * wf. Sources tie to a met1 strip below the active, drains
    to a strip above; gates tie via a poly bridge to a contact at the top.
    Returns {"S","D","G"} met1 terminal boxes. KLayout extracts the nf parallel
    fingers and merges them into one device of width nf*wf.
    """
    def box(layer, x0, y0, x1, y1):
        cell.shapes(li[layer]).insert(db.DBox(x0, y0, x1, y1))

    sd = SD_EXT
    ax0, ay0, ay1 = x, y, y + wf
    ax1 = x + nf * l + (nf + 1) * sd
    box("diff", ax0, ay0, ax1, ay1)
    box("nsdm" if kind == "nmos" else "psdm", ax0 - 0.1, ay0 - 0.1, ax1 + 0.1, ay1 + 0.1)
    if kind == "pmos":
        box("nwell", ax0 - 0.18, ay0 - 0.18, ax1 + 0.18, ay1 + 0.18)

    s_y0, s_y1 = ay0 - 0.34, ay0 - 0.14          # source comb strip (below)
    d_y0, d_y1 = ay1 + 0.14, ay1 + 0.34          # drain comb strip (above)
    box("met1", ax0, s_y0, ax1, s_y1)
    box("met1", ax0, d_y0, ax1, d_y1)

    for j in range(nf + 1):                       # S/D regions (alternate S,D)
        rx0 = x + j * (l + sd)
        cx = rx0 + sd / 2
        cy = (ay0 + ay1) / 2
        box("licon", cx - CON, cy - CON, cx + CON, cy + CON)
        box("li1", rx0 + 0.03, ay0 + 0.03, rx0 + sd - 0.03, ay1 - 0.03)
        box("mcon", cx - CON, cy - CON, cx + CON, cy + CON)
        box("met1", rx0, ay0, rx0 + sd, ay1)
        if j % 2 == 0:                            # source -> down stub to S strip
            box("met1", rx0, s_y1, rx0 + sd, ay0)
        else:                                     # drain -> up stub to D strip
            box("met1", rx0, ay1, rx0 + sd, d_y0)

    for i in range(nf):                           # gate polys
        gx0 = x + sd + i * (l + sd)
        box("poly", gx0, ay0 - POLY_EXT, gx0 + l, d_y1 + 0.12)   # tab up past D strip
    bridge_y0, bridge_y1 = d_y1 + 0.08, d_y1 + 0.16              # poly bridge (gates tied)
    box("poly", x + sd, bridge_y0, x + nf * l + nf * sd, bridge_y1)
    gcx = (x + sd + x + nf * l + nf * sd) / 2                    # gate contact
    gcy0, gcy1 = bridge_y1, bridge_y1 + GATE_TAB
    box("poly", gcx - 0.04, bridge_y0, gcx + 0.04, gcy1)
    box("licon", gcx - CON, (gcy0 + gcy1) / 2 - CON, gcx + CON, (gcy0 + gcy1) / 2 + CON)
    box("li1", gcx - (CON + 0.015), gcy0, gcx + (CON + 0.015), gcy1)
    box("mcon", gcx - CON, (gcy0 + gcy1) / 2 - CON, gcx + CON, (gcy0 + gcy1) / 2 + CON)
    box("met1", gcx - (CON + 0.015), gcy0, gcx + (CON + 0.015), gcy1)

    return {"S": (ax0, s_y0, ax1, s_y1), "D": (ax0, d_y0, ax1, d_y1),
            "G": (gcx - (CON + 0.015), gcy0, gcx + (CON + 0.015), gcy1),
            "width_x": ax1 - ax0, "kind": kind, "W": nf * wf, "L": l}


def build_current_mirror(w: float = 1.0, l: float = 0.15):
    """A merged-diffusion NMOS current mirror (M0 diode ref, M1 output).

    One shared source diffusion, both gates tied (poly bridge), ref drain tied to
    the gate (diode). Nets labeled VSS/GATE/OUT. Returns (layout, top_cell).
    """
    ly = db.Layout(); ly.dbu = 0.005
    top = ly.create_cell("CMIRROR")
    li = layer_index(ly)

    def box(layer, x0, y0, x1, y1):
        top.shapes(li[layer]).insert(db.DBox(x0, y0, x1, y1))

    def label(net, x, y):
        top.shapes(li["met1"]).insert(
            db.Text(net, db.Trans(db.Vector(round(x / ly.dbu), round(y / ly.dbu)))))

    sd, ctr = SD_EXT, 0.30
    xs = [0, sd, sd + l, sd + l + ctr, sd + l + ctr + l, sd + l + ctr + l + sd]
    box("diff", xs[0], 0, xs[5], w)
    box("nsdm", xs[0] - 0.1, -0.1, xs[5] + 0.1, w + 0.1)
    box("poly", xs[1], -POLY_EXT, xs[2], w + POLY_EXT)       # gate 0
    box("poly", xs[3], -POLY_EXT, xs[4], w + POLY_EXT)       # gate 1
    box("poly", xs[1], w + POLY_EXT, xs[4], w + 0.30)        # poly bridge (gates tied)

    def stack(cx, m0, m1):                                    # S/D contact stack
        cy = w / 2
        box("licon", cx - CON, cy - CON, cx + CON, cy + CON)
        box("li1", m0 + 0.03, 0.03, m1 - 0.03, w - 0.03)
        box("mcon", cx - CON, cy - CON, cx + CON, cy + CON)
        box("met1", m0, 0, m1, w)
    stack((xs[0] + xs[1]) / 2, xs[0], xs[1])                  # ref drain (-> GATE)
    stack((xs[2] + xs[3]) / 2, xs[2], xs[3])                  # shared source (VSS)
    stack((xs[4] + xs[5]) / 2, xs[4], xs[5])                  # output drain (OUT)

    gcx = (xs[1] + xs[4]) / 2; g0, g1 = w + 0.30, w + 0.62    # gate contact
    box("poly", gcx - 0.1, w + 0.30, gcx + 0.1, g1)
    box("licon", gcx - CON, (g0 + g1) / 2 - CON, gcx + CON, (g0 + g1) / 2 + CON)
    box("li1", gcx - 0.12, g0, gcx + 0.12, g1)
    box("mcon", gcx - CON, (g0 + g1) / 2 - CON, gcx + CON, (g0 + g1) / 2 + CON)
    box("met1", gcx - 0.15, g0, gcx + 0.15, g1)
    box("met1", xs[0], w, xs[0] + 0.2, g1)                    # diode riser (ref drain up)
    box("met1", xs[0], g1 - 0.16, gcx + 0.15, g1)            # to gate met1

    label("VSS", (xs[2] + xs[3]) / 2, w / 2)
    label("GATE", gcx, (g0 + g1) / 2)
    label("OUT", (xs[4] + xs[5]) / 2, w / 2)
    return ly, top
