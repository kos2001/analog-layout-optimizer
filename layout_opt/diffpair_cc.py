"""Common-centroid input-pair layout (the canonical op-amp matching technique).

The differential input pair M1/M2 is the matching-critical device in an op-amp:
a process gradient across it converts to input offset and CMRR loss. The fix is
a **common-centroid** finger array — M1 and M2 are split into fingers laid
ABBA so both devices share the same centroid, and any *linear* gradient cancels.

Here each finger is a real SKY130 device; A-fingers tie to VINP/n1, B-fingers to
VINN/n2, with a common source (TAIL) and a substrate **guard ring**. KLayout
extracts the array as two matched transistors (W = nf x wf) and LVS-matches the
diff-pair schematic; the gradient-cancellation metric confirms centroid offset 0.
"""

from __future__ import annotations

import klayout.db as db

from .device_layout import add_device, layer_index, device_extent
from .common_centroid import gradient_mismatch

W_DEFAULT, L_DEFAULT = 1.0, 0.15
PORTS = ["VINP", "VINN", "n1", "n2", "TAIL"]
# ABBA per device-pair: A and B share a centroid (linear gradient cancels).
PATTERN = ["A", "B", "B", "A"]
DEV_NETS = {  # finger device -> {terminal: net}
    "A": {"G": "VINP", "D": "n1", "S": "TAIL"},
    "B": {"G": "VINN", "D": "n2", "S": "TAIL"},
}


def build_cc_diffpair(wf: float = W_DEFAULT, l: float = L_DEFAULT, pattern=None,
                      guard: bool = True):
    """Build the common-centroid input pair. Returns (layout, top, schem, metrics)."""
    pattern = pattern or PATTERN
    ly = db.Layout(); ly.dbu = 0.005
    top = ly.create_cell("DIFFPAIR_CC")
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

    # 1. Place the fingers in a row (ABBA); collect net -> riser points.
    fw, _fh = device_extent(wf, l)
    pitch = fw + 0.9
    net_ports: dict[str, list] = {}
    centroids: dict[str, list] = {"A": [], "B": []}
    top_y = 0.0
    for i, dev in enumerate(pattern):
        terms = add_device(top, li, i * pitch, 0.0, wf, l, "nmos")
        sb, dbx, gb = terms["S"], terms["D"], terms["G"]
        pts = {"S": (sb[0] + 0.07, (sb[1] + sb[3]) / 2),
               "D": (dbx[2] - 0.07, (dbx[1] + dbx[3]) / 2),
               "G": ((gb[0] + gb[2]) / 2, (gb[1] + gb[3]) / 2)}
        for term, net in DEV_NETS[dev].items():
            net_ports.setdefault(net, []).append(pts[term])
        centroids[dev].append(i)
        top_y = max(top_y, gb[3])

    # 2. Three-layer routing: met2 risers + met3 per-net buses.
    bus_y = top_y + 0.7
    bus_info: dict[str, tuple] = {}
    for net in sorted(net_ports):
        ports = net_ports[net]
        xs = [p[0] for p in ports]
        by = bus_y
        shp("met3", min(xs) - 0.15, by - 0.15, max(xs) + 0.15, by + 0.15)
        for px, py in ports:
            via1(px, py)
            shp("met2", px - 0.07, py - 0.07, px + 0.07, by + 0.07)
            via2(px, by)
        label(net, (min(xs) + max(xs)) / 2, by, "met3")
        bus_info[net] = (by, min(xs), max(xs))
        bus_y += 0.7

    # 3. Substrate guard ring (p+ tap + contacts + met1) framing the array.
    # Tied into TAIL: the ring is pure substrate contact (no poly => not a device),
    # so joining its metal to an existing net adds no device pin and LVS still matches.
    if guard:
        span_x = (len(pattern) - 1) * pitch + fw
        gx0, gy0, gx1, gy1 = -0.6, -0.9, span_x + 0.6, top_y + 0.55
        for (rx0, ry0, rx1, ry1) in (                # 4 tap bars framing the cell
            (gx0, gy0, gx1, gy0 + 0.34), (gx0, gy1 - 0.34, gx1, gy1),
            (gx0, gy0, gx0 + 0.34, gy1), (gx1 - 0.34, gy0, gx1, gy1),
        ):
            shp("diff", rx0, ry0, rx1, ry1)
            shp("psdm", rx0 - 0.05, ry0 - 0.05, rx1 + 0.05, ry1 + 0.05)
            shp("li1", rx0 + 0.03, ry0 + 0.03, rx1 - 0.03, ry1 - 0.03)
            shp("met1", rx0, ry0, rx1, ry1)
        # tie the top guard bar up into the TAIL bus (met1 -> via -> met2 -> via2 -> met3)
        tby, txmin, _ = bus_info["TAIL"]
        cx = txmin
        cy = gy1 - 0.17
        top.shapes(li["via"]).insert(db.DBox(cx - 0.085, cy - 0.085, cx + 0.085, cy + 0.085))
        shp("met2", cx - 0.07, cy - 0.07, cx + 0.07, tby + 0.07)
        via2(cx, tby)

    # 4. Matching metrics from the finger pattern (1-D centroid / gradient).
    grid = [["A" if p == "A" else "B" for p in pattern]]
    ca = sum(centroids["A"]) / len(centroids["A"])
    cb = sum(centroids["B"]) / len(centroids["B"])
    nf = pattern.count("A")
    schem = [{"name": "M1", "kind": "nmos", "W": round(nf * wf, 4), "L": l, **DEV_NETS["A"]},
             {"name": "M2", "kind": "nmos", "W": round(nf * wf, 4), "L": l, **DEV_NETS["B"]}]
    # Contrast: the naive segregated (AABB) order with the same fingers — its
    # centroids are offset, so a linear gradient leaves a residual mismatch.
    seg = [sorted(pattern)]                          # ['A','A','B','B']
    seg_mm = gradient_mismatch(seg, 1.0, 0.0)
    cc_mm = gradient_mismatch(grid, 1.0, 0.0)
    metrics = {"pattern": "".join(pattern), "centroid_A": ca, "centroid_B": cb,
               "centroid_offset": round(abs(ca - cb), 3),
               "gradient_mismatch": round(cc_mm, 4),
               "segregated_mismatch": round(seg_mm, 4),
               "improvement_x": round(seg_mm / cc_mm, 1) if cc_mm > 1e-9 else None,
               "fingers_per_device": nf}
    return ly, top, schem, metrics
