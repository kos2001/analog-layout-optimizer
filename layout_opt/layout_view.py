"""Dump a layout's shapes per SKY130 layer for an in-browser viewer.

Turns the actual transistor-level GDS geometry into per-layer polygon lists (in
microns) so the web app can *render* the layout — diffusion, poly, contacts,
metal stack — not just offer a download.
"""

from __future__ import annotations

import klayout.db as db

# SKY130 (layer, datatype) -> (display name, fill colour). Drawing order = list order.
SKY_LAYERS = [
    ((64, 20), "nwell", "#3a2f0b"),
    ((65, 20), "diff", "#43a047"),
    ((94, 20), "psdm", "#7a4f9e"),
    ((93, 44), "nsdm", "#2f6f9e"),
    ((66, 20), "poly", "#e53935"),
    ((66, 44), "licon", "#ffd54f"),
    ((67, 20), "li1", "#9e9e9e"),
    ((67, 44), "mcon", "#fff176"),
    ((68, 20), "met1", "#42a5f5"),
    ((68, 44), "via", "#fdd835"),
    ((69, 20), "met2", "#ce93d8"),
    ((69, 44), "via2", "#fff176"),
    ((70, 20), "met3", "#ffb300"),
]


def _shape_pts(s: db.Shape, dbu: float):
    """Return the shape's hull as [[x,y],...] in microns, or None."""
    if s.is_box():
        b = s.box
        return [[b.left * dbu, b.bottom * dbu], [b.right * dbu, b.bottom * dbu],
                [b.right * dbu, b.top * dbu], [b.left * dbu, b.top * dbu]]
    if s.is_polygon() or s.is_simple_polygon() or s.is_path():
        poly = s.polygon
        if poly is None:
            return None
        return [[p.x * dbu, p.y * dbu] for p in poly.each_point_hull()]
    return None


def layout_shapes(which: str = "ota") -> dict:
    """Per-layer polygons (um) + labels + bbox for a layout."""
    if which == "mirror":
        from .device_layout import build_current_mirror
        ly, top = build_current_mirror()
    else:
        from .ota_layout import build_ota
        ly, top, _s, _c = build_ota(with_cap=False)
    dbu = ly.dbu

    out_layers = []
    for (lyr, dt), name, color in SKY_LAYERS:
        idx = ly.find_layer(lyr, dt)
        if idx is None:
            continue
        polys, labels = [], []
        for s in top.shapes(idx).each():
            pts = _shape_pts(s, dbu)
            if pts:
                polys.append(pts)
            elif s.is_text():
                t = s.text
                labels.append({"text": t.string, "x": t.x * dbu, "y": t.y * dbu})
        if polys or labels:
            out_layers.append({"layer": lyr, "datatype": dt, "name": name,
                               "color": color, "polys": polys, "labels": labels})

    bb = top.dbbox()
    return {"which": which, "topCell": top.name, "dbu": dbu,
            "bbox": [bb.left, bb.bottom, bb.right, bb.top],
            "layers": out_layers,
            "nPolygons": sum(len(L["polys"]) for L in out_layers)}
