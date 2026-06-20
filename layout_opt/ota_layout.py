"""Full two-stage OTA, transistor-level P&R (real SKY130 geometry) for LVS.

All seven MOSFETs are placed in one row so every terminal's met1 drop rises into
an empty channel above the devices; each net gets a met2 bus there, with vias
where a drop meets its bus. met1 (vertical drops) and met2 (horizontal buses) on
separate layers can't short across nets, and the single row keeps a drop from
ever crossing a foreign device terminal. KLayout then extracts the device-level
netlist and LVS-compares it to the OTA schematic.

Cc (Miller cap) is omitted from this MOS LVS — it's a capacitor device; the seven
transistors define every net on their own, so the connectivity check is intact.
"""

from __future__ import annotations

import klayout.db as db

from .device_layout import add_device, layer_index, device_extent

# device, kind, and {terminal: net}
DEVICES = [
    ("M1", "nmos", {"G": "VINP", "D": "n1", "S": "TAIL"}),
    ("M2", "nmos", {"G": "VINN", "D": "n2", "S": "TAIL"}),
    ("M3", "pmos", {"G": "n1", "D": "n1", "S": "VDD"}),
    ("M4", "pmos", {"G": "n1", "D": "n2", "S": "VDD"}),
    ("M5", "nmos", {"G": "VBIAS", "D": "TAIL", "S": "VSS"}),
    ("M6", "nmos", {"G": "n2", "D": "VOUT", "S": "VSS"}),
    ("M7", "pmos", {"G": "VBIASP", "D": "VOUT", "S": "VDD"}),
]
PORTS = ["VINP", "VINN", "VOUT", "VBIAS", "VBIASP", "VDD", "VSS"]
W, L = 1.0, 0.15
PITCH = 1.4                  # device-to-device spacing (x)


def _anchor(box):
    """(center_x, top_y) of a terminal met1 box."""
    x0, y0, x1, y1 = box
    return (x0 + x1) / 2.0, y1


def build_ota():
    """Build the OTA transistor layout. Returns (layout, top_cell, schematic_devices)."""
    ly = db.Layout(); ly.dbu = 0.005
    top = ly.create_cell("OTA")
    li = layer_index(ly)

    def met1(x0, y0, x1, y1):
        top.shapes(li["met1"]).insert(db.DBox(x0, y0, x1, y1))

    def met2(x0, y0, x1, y1):
        top.shapes(li["met2"]).insert(db.DBox(x0, y0, x1, y1))

    def via(cx, cy):
        top.shapes(li["via"]).insert(db.DBox(cx - 0.085, cy - 0.085, cx + 0.085, cy + 0.085))

    def label(net, x, y, layer="met2"):
        top.shapes(li[layer]).insert(
            db.Text(net, db.Trans(db.Vector(round(x / ly.dbu), round(y / ly.dbu)))))

    # 1. Place devices in a row; collect terminal anchors per net.
    _, dh = device_extent(W, L)
    net_anchors: dict[str, list] = {}
    for i, (name, kind, conns) in enumerate(DEVICES):
        terms = add_device(top, li, i * PITCH, 0.0, W, L, kind)
        for term, net in conns.items():
            net_anchors.setdefault(net, []).append((name, term, _anchor(terms[term])))

    # 2. Route each net: single-terminal -> label; multi-terminal -> met2 bus + drops.
    bus_y = dh + 0.6
    for net in sorted(net_anchors):
        anchors = net_anchors[net]
        if len(anchors) == 1:
            _, _, (ax, ay) = anchors[0]
            if net in PORTS:
                label(net, ax, ay, "met1")          # port pin on the terminal
            continue
        xs = [a[2][0] for a in anchors]
        by = bus_y
        met2(min(xs) - 0.1, by - 0.1, max(xs) + 0.1, by + 0.1)   # horizontal bus
        for _, _, (ax, ay) in anchors:
            met1(ax - 0.09, ay - 0.06, ax + 0.09, by + 0.09)     # vertical drop
            via(ax, by)                                          # met1->met2
        label(net, (min(xs) + max(xs)) / 2, by, "met2")
        bus_y += 0.5                                             # next net on its own track

    schem = [{"name": n, "kind": k, "W": W, "L": L, **c} for n, k, c in DEVICES]
    return ly, top, schem
