"""Export a placed-and-routed flow to real GDSII.

Bridges the abstract routing grid to a manufacturable format: each grid cell
becomes metal on the corresponding SKY130 layer, vias where a net changes layer,
device footprints as a marker layer with a text label per device. The result
opens in KLayout / Magic and can be DRC'd against the SKY130 deck — the next
fidelity step beyond the in-house grid DRC.

Uses `gdstk` (pip, no PDK needed). SKY130 GDS layer/datatype numbers:
    met1 68/20, met2 69/20, via 68/44, diff 65/20, met1-pin 68/16, text 68/5
"""

from __future__ import annotations

import gdstk

PITCH_UM = 0.5                     # microns per routing-grid cell

# (layer, datatype) — SKY130 stream numbers.
MET = {0: (68, 20), 1: (69, 20)}   # routing layer index -> metal layer
VIA = (68, 44)
DIFF = (65, 20)
PIN = (68, 16)
TEXT = (68, 5)


def _cells_by_layer(nr: dict):
    by = {}
    for c in nr.get("cells", []):
        layer = c[2] if len(c) > 2 else 0
        by.setdefault(layer, []).append((c[0], c[1]))
    return by


def flow_to_gds(flow: dict, out_path: str, pitch: float = PITCH_UM) -> dict:
    """Write GDSII for a flow result (components + routing); return stats."""
    lib = gdstk.Library("analog_ota")
    top = lib.new_cell("OTA_TOP")
    p = pitch
    counts = {"metal": 0, "via": 0, "device": 0}

    # Device footprints (marker layer) + a label per device.
    for c in flow["components"]:
        x0, y0 = c["x"] * p, c["y"] * p
        x1, y1 = (c["x"] + c["w"]) * p, (c["y"] + c["h"]) * p
        top.add(gdstk.rectangle((x0, y0), (x1, y1), layer=DIFF[0], datatype=DIFF[1]))
        top.add(gdstk.Label(c["label"], ((x0 + x1) / 2, (y0 + y1) / 2),
                            layer=TEXT[0], texttype=TEXT[1]))
        counts["device"] += 1

    # Routed metal per net, per layer; vias where a net spans both layers.
    for net, nr in flow["routing"]["nets"].items():
        if not nr.get("routed", True):
            continue
        by = _cells_by_layer(nr)
        for layer, cells in by.items():
            lay = MET.get(layer, MET[0])
            for (x, y) in cells:
                top.add(gdstk.rectangle((x * p, y * p), ((x + 1) * p, (y + 1) * p),
                                        layer=lay[0], datatype=lay[1]))
                counts["metal"] += 1
            # net-name label on the metal
            if cells:
                cx, cy = cells[0]
                top.add(gdstk.Label(net, ((cx + 0.5) * p, (cy + 0.5) * p),
                                    layer=TEXT[0], texttype=TEXT[1]))
        # via cuts: (x,y) present on more than one layer
        xy_layers = {}
        for layer, cells in by.items():
            for c in cells:
                xy_layers.setdefault(c, set()).add(layer)
        for (x, y), ls in xy_layers.items():
            if len(ls) > 1:
                vx, vy = (x + 0.5) * p, (y + 0.5) * p
                top.add(gdstk.rectangle((vx - p * 0.2, vy - p * 0.2),
                                        (vx + p * 0.2, vy + p * 0.2),
                                        layer=VIA[0], datatype=VIA[1]))
                counts["via"] += 1

    lib.write_gds(out_path)

    # Stats.
    polys = top.get_polygons()
    bb = top.bounding_box()
    layers = sorted({(pp.layer, pp.datatype) for pp in polys})
    return {
        "path": out_path,
        "topCell": "OTA_TOP",
        "polygons": len(polys),
        "counts": counts,
        "layers": [{"layer": l, "datatype": d} for l, d in layers],
        "bbox_um": [list(bb[0]), list(bb[1])] if bb else None,
        "area_um2": round((bb[1][0] - bb[0][0]) * (bb[1][1] - bb[0][1]), 3) if bb else 0.0,
        "pitch_um": pitch,
    }


def flow_to_gds_bytes(flow: dict, pitch: float = PITCH_UM):
    """Return (gds_bytes, stats) without leaving a file behind."""
    import tempfile
    import os
    fd, path = tempfile.mkstemp(suffix=".gds")
    os.close(fd)
    try:
        stats = flow_to_gds(flow, path, pitch)
        with open(path, "rb") as f:
            data = f.read()
        return data, stats
    finally:
        os.unlink(path)
