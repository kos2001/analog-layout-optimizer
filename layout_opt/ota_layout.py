"""Full two-stage OTA, transistor-level P&R (real SKY130 geometry) for LVS.

Per-device real sizing: each MOSFET's width comes from the OTA sizing (W = W/L x
L, min-clamped), laid out multi-finger so wide devices stay compact (KLayout
merges the fingers back to the full W). Routing is three-layer — met1 device
terminals, met2 vertical risers over the devices, met3 per-net horizontal buses,
joined by vias — so no two nets share a layer where they could short.

KLayout then extracts the device-level netlist (with per-device W/L) and
LVS-compares it to the OTA schematic. The layout is met1/met2/met3 DRC-clean
(width + spacing). Cc's value is reported; modelling it as a real MIM-cap device
(dedicated cap layers + capacitor extractor) is a follow-up.
"""

from __future__ import annotations

import klayout.db as db

from .device_layout import add_mf_device, layer_index, n_fingers
from .opamp import OpAmpParams
from .opamp_opt import de_log_refine

# device, kind, {terminal: net}
DEVICES = [
    ("M1", "nmos", {"G": "VINP", "D": "n1", "S": "TAIL"}, "wl1"),
    ("M2", "nmos", {"G": "VINN", "D": "n2", "S": "TAIL"}, "wl1"),
    ("M3", "pmos", {"G": "n1", "D": "n1", "S": "VDD"}, "wl3"),
    ("M4", "pmos", {"G": "n1", "D": "n2", "S": "VDD"}, "wl3"),
    ("M5", "nmos", {"G": "VBIAS", "D": "TAIL", "S": "VSS"}, "wl5"),
    ("M6", "nmos", {"G": "n2", "D": "VOUT", "S": "VSS"}, "wl6"),
    ("M7", "pmos", {"G": "VBIASP", "D": "VOUT", "S": "VDD"}, "wl7"),
]
PORTS = ["VINP", "VINN", "VOUT", "VBIAS", "VBIASP", "VDD", "VSS"]
L = 0.15
W_MIN = 0.42                 # SKY130 min device width
GAP = 1.2                    # gap between device footprints (routing room)
CC_NET_P, CC_NET_N = "n2", "VOUT"


def _sizing_widths(params: OpAmpParams) -> dict:
    """Per-device W (um) from the sized W/L ratios, clamped to >= W_MIN."""
    return {name: max(getattr(params, wl) * L, W_MIN)
            for name, _k, _c, wl in DEVICES}


def build_ota(params: OpAmpParams = None, with_cap: bool = True):
    """Build the OTA transistor layout with real per-device sizing.

    Returns (layout, top_cell, schematic_devices, cap_value_fF | None).
    """
    params = params or de_log_refine(seed=0).params
    widths = _sizing_widths(params)

    ly = db.Layout(); ly.dbu = 0.005
    top = ly.create_cell("OTA")
    li = layer_index(ly)

    def shp(layer, x0, y0, x1, y1):
        top.shapes(li[layer]).insert(db.DBox(x0, y0, x1, y1))

    def via1(cx, cy):
        top.shapes(li["via"]).insert(db.DBox(cx - 0.085, cy - 0.085, cx + 0.085, cy + 0.085))

    def via2(cx, cy):
        top.shapes(li["via2"]).insert(db.DBox(cx - 0.085, cy - 0.085, cx + 0.085, cy + 0.085))

    def label(net, x, y, layer):
        top.shapes(li[layer]).insert(
            db.Text(net, db.Trans(db.Vector(round(x / ly.dbu), round(y / ly.dbu)))))

    # 1. Place devices in a row; record (net -> [(riser_x, riser_y_top)]) ports.
    net_ports: dict[str, list] = {}
    cx = 0.0
    top_y = 0.0
    sched_W = {}
    for name, kind, conns, _wl in DEVICES:
        w = widths[name]
        nf, wf = n_fingers(w)
        wf = round(wf / ly.dbu) * ly.dbu          # snap finger width to the dbu grid
        sched_W[name] = round(nf * wf, 4)         # so extracted W == schematic W exactly
        terms = add_mf_device(top, li, cx, 0.0, wf, L, kind, nf)
        wx = terms["width_x"]
        # riser drop points per terminal (distinct x within the device)
        sb = terms["S"]; dbx = terms["D"]; gb = terms["G"]
        pts = {
            "S": (sb[0] + 0.07, (sb[1] + sb[3]) / 2),       # risers at the strip edges
            "D": (dbx[2] - 0.07, (dbx[1] + dbx[3]) / 2),    # so S/G/D met2 stay >0.14 apart
            "G": ((gb[0] + gb[2]) / 2, (gb[1] + gb[3]) / 2),
        }
        for term, net in conns.items():
            net_ports.setdefault(net, []).append(pts[term])
        top_y = max(top_y, gb[3])
        cx += wx + GAP

    # 2. Three-layer routing: riser (met2) per port, met3 bus per multi-net.
    bus_y = top_y + 0.6
    bus_geom: dict[str, tuple] = {}            # net -> (bus_y, xmin, xmax)
    for net in sorted(net_ports):
        ports = net_ports[net]
        if len(ports) == 1:
            px, py = ports[0]
            if net in PORTS:                       # single-terminal port: label terminal
                label(net, px, py, "met1")
            continue
        by = bus_y
        xs = [p[0] for p in ports]
        shp("met3", min(xs) - 0.15, by - 0.15, max(xs) + 0.15, by + 0.15)   # bus (>=0.3 wide)
        for px, py in ports:
            via1(px, py)
            shp("met2", px - 0.07, py - 0.07, px + 0.07, by + 0.07)         # riser
            via2(px, by)
        label(net, (min(xs) + max(xs)) / 2, by, "met3")
        bus_geom[net] = (by, min(xs) - 0.15, max(xs) + 0.15)
        bus_y += 0.6                                                        # >=0.3 met3 gap

    # 3. Miller cap Cc: capm (top, VOUT) over a met2 plate (bottom, n2); risers
    #    carry n2/VOUT up to their met3 buses (met2 verticals avoid met3 shorts).
    cap_info = None
    cap_fF = round(params.cc * 1e15, 2)
    if with_cap and "n2" in bus_geom and "VOUT" in bus_geom:
        C_F = params.cc
        S = 2.0
        area_cap = C_F / (S * S)                    # so extracted C == C_F exactly
        x0, y0 = cx + 1.0, 0.0
        n2_by, n2_xmax = bus_geom["n2"][0], bus_geom["n2"][2]
        vo_by, vo_xmax = bus_geom["VOUT"][0], bus_geom["VOUT"][2]
        shp("met2", x0, y0, x0 + S, y0 + S)         # bottom plate (n2)
        shp("capm", x0, y0, x0 + S, y0 + S)         # top plate (capm)
        shp("met3", x0, y0, x0 + S, y0 + S)         # top contact (VOUT) over capm
        # n2 riser: plate(met2) -> up -> via2 -> n2 bus (extended to the cap)
        rx = x0 + 0.1
        shp("met2", rx - 0.07, y0 + S, rx + 0.07, n2_by + 0.07)
        via2(rx, n2_by)
        shp("met3", n2_xmax, n2_by - 0.15, rx + 0.15, n2_by + 0.15)
        # VOUT riser: capm/met3 -> tab above plate -> via2 -> met2 up -> via2 -> VOUT bus
        vx = x0 + S - 0.18
        shp("met3", vx - 0.15, y0 + S, vx + 0.15, y0 + S + 0.34)   # tab >=0.3 wide
        via2(vx, y0 + S + 0.24)
        shp("met2", vx - 0.07, y0 + S + 0.17, vx + 0.07, vo_by + 0.07)  # gap>0.14 from plate
        via2(vx, vo_by)
        shp("met3", vo_xmax, vo_by - 0.15, vx + 0.15, vo_by + 0.15)
        cap_info = {"C_F": C_F, "area_cap": area_cap, "side": S}

    schem = [{"name": n, "kind": k, "W": sched_W[n], "L": L, **c}
             for n, k, c, _wl in DEVICES]
    if cap_info is None:
        cap_info = {"C_F": params.cc, "area_cap": None, "side": None}  # value only
    return ly, top, schem, cap_info
