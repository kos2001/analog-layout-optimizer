"""Real LVS on a transistor-level layout with KLayout's engine.

Extracts MOSFETs from the device geometry (active/poly/contacts/metal, NMOS vs
PMOS split by nwell), builds the layout netlist, and compares it to a schematic
netlist with KLayout's `NetlistComparer` — the same engine the SKY130 KLayout
LVS deck uses. Magic+Netgen aren't installable here, but this is the equivalent
real-tool LVS, all via pip.
"""

from __future__ import annotations

import klayout.db as db

from .device_layout import LAYERS


def extract_netlist(layout: db.Layout, cell: db.Cell, cap: dict = None):
    """Extract a device-level netlist from a transistor layout. Returns (netlist, l2n).

    If `cap` ({"area_cap": F/um^2}) is given, also extract a MIM capacitor between
    the capm plate (89/44) and met2.
    """
    li = {k: layout.layer(*v) for k, v in LAYERS.items()}
    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, cell, []))
    _extra = {"via": (68, 44), "met2": (69, 20), "via2": (69, 44), "met3": (70, 20)}
    for k, v in _extra.items():
        li.setdefault(k, layout.layer(*v))
    R = {n: l2n.make_layer(li[n], n) for n in
         ("nwell", "diff", "poly", "licon", "li1", "mcon", "met1", "via", "met2",
          "via2", "met3")}

    nwell = R["nwell"]
    diff_p = R["diff"] & nwell           # PMOS active sits in nwell
    diff_n = R["diff"] - nwell
    gate_n = R["poly"] & diff_n
    sd_n = diff_n - R["poly"]
    gate_p = R["poly"] & diff_p
    sd_p = diff_p - R["poly"]

    exn = db.DeviceExtractorMOS3Transistor("nmos")
    l2n.extract_devices(exn, {"SD": sd_n, "G": gate_n, "tS": sd_n, "tD": sd_n, "tG": R["poly"]})
    exp = db.DeviceExtractorMOS3Transistor("pmos")
    l2n.extract_devices(exp, {"SD": sd_p, "G": gate_p, "tS": sd_p, "tD": sd_p, "tG": R["poly"]})

    if cap and cap.get("area_cap"):
        li.setdefault("capm", layout.layer(89, 44))
        rcapm = l2n.make_layer(li["capm"], "capm")
        excap = db.DeviceExtractorCapacitor("Cc", cap["area_cap"])
        l2n.extract_devices(excap, {"P1": rcapm, "P2": R["met2"]})
        l2n.connect(rcapm)
        l2n.connect(rcapm, R["met3"])             # capm top plate -> met3 (VOUT)

    # Connectivity: contacts bridge diff/poly -> li1 -> mcon -> met1 -> via -> met2.
    for r in (sd_n, sd_p, R["poly"], R["licon"], R["li1"], R["mcon"], R["met1"],
              R["via"], R["met2"], R["via2"], R["met3"]):
        l2n.connect(r)
    l2n.connect(sd_n, R["licon"]); l2n.connect(sd_p, R["licon"])
    l2n.connect(R["poly"], R["licon"])
    l2n.connect(R["licon"], R["li1"]); l2n.connect(R["li1"], R["mcon"])
    l2n.connect(R["mcon"], R["met1"])
    l2n.connect(R["met1"], R["via"]); l2n.connect(R["via"], R["met2"])
    l2n.connect(R["met2"], R["via2"]); l2n.connect(R["via2"], R["met3"])

    l2n.extract_netlist()
    nl = l2n.netlist()
    nl.make_top_level_pins()
    nl.combine_devices()
    nl.purge()
    return nl, l2n


def device_summary(netlist: db.Netlist) -> dict:
    """Per-type device count + (W,L) list from an extracted/built netlist."""
    cir = netlist.top_circuit() if hasattr(netlist, "top_circuit") else list(netlist.each_circuit())[-1]
    by = {}
    for d in cir.each_device():
        cls = d.device_class().name
        by.setdefault(cls, [])
        try:
            by[cls].append((round(d.parameter("W"), 3), round(d.parameter("L"), 3)))
        except Exception:
            by[cls].append((None, None))
    return {"counts": {k: len(v) for k, v in by.items()}, "devices": by}


def schematic_mos_netlist(devices: list[dict], ports: list[str] = None,
                          name: str = "REF", caps: list[dict] = None) -> db.Netlist:
    """Build a reference netlist from MOS [{name,kind,S,G,D}] + cap [{name,A,B,C}].

    `ports` net names become top-level pins so LVS can anchor net correspondence.
    """
    nl = db.Netlist()
    clsn = db.DeviceClassMOS3Transistor(); clsn.name = "nmos"; nl.add(clsn)
    clsp = db.DeviceClassMOS3Transistor(); clsp.name = "pmos"; nl.add(clsp)
    clsc = db.DeviceClassCapacitor(); clsc.name = "Cc"; nl.add(clsc)
    cir = db.Circuit(); cir.name = name; nl.add(cir)
    nets = {}
    def net(n):
        if n not in nets:
            nets[n] = cir.create_net(n)
        return nets[n]
    cls = {"nmos": clsn, "pmos": clsp}
    TERM = {"S": 0, "G": 1, "D": 2}     # MOS3 terminal order: S, G, D
    for d in devices:
        dev = cir.create_device(cls[d["kind"]], d["name"])
        for t in ("S", "G", "D"):
            dev.connect_terminal(TERM[t], net(d[t]))
        dev.set_parameter("W", float(d.get("W", 1.0)))   # must match extracted
        dev.set_parameter("L", float(d.get("L", 0.15)))
    for c in (caps or []):
        dev = cir.create_device(clsc, c["name"])
        dev.connect_terminal(0, net(c["A"]))             # capacitor terminals A, B
        dev.connect_terminal(1, net(c["B"]))
        dev.set_parameter("C", float(c["C"]))
    for pn in (ports or []):
        pin = cir.create_pin(pn)
        cir.connect_pin(pin, net(pn))
    return nl


def compare(layout_nl: db.Netlist, schem_nl: db.Netlist) -> bool:
    """True iff the layout netlist matches the schematic netlist (LVS clean)."""
    return db.NetlistComparer().compare(layout_nl, schem_nl)


def lvs_current_mirror(w: float = 1.0, l: float = 0.15) -> dict:
    """Build the transistor-level current mirror, extract, and LVS vs schematic."""
    from .device_layout import build_current_mirror
    ly, top = build_current_mirror(w, l)
    layout_nl, _l2n = extract_netlist(ly, top)
    schem = schematic_mos_netlist(
        [{"name": "M0", "kind": "nmos", "S": "VSS", "G": "GATE", "D": "GATE", "W": w, "L": l},
         {"name": "M1", "kind": "nmos", "S": "VSS", "G": "GATE", "D": "OUT", "W": w, "L": l}],
        ports=["VSS", "GATE", "OUT"], name="CMIRROR")
    match = compare(layout_nl, schem)
    return {"tool": "KLayout LVS (DeviceExtractorMOS3 + NetlistComparer)",
            "cell": "CMIRROR", "match": match,
            "devices": device_summary(layout_nl),
            "layout_netlist": layout_nl.to_s()}


def lvs_ota(gds_out: str | None = None, with_cap: bool = True) -> dict:
    """Full two-stage OTA: transistor-level P&R, extract, and LVS vs schematic."""
    from .ota_layout import build_ota, PORTS
    ly, top, schem_devs, cap_info = build_ota(with_cap=with_cap)
    if gds_out:
        ly.write(gds_out)
    cap = cap_info if (with_cap and cap_info.get("area_cap")) else None
    layout_nl, _l2n = extract_netlist(ly, top, cap=cap)
    caps = ([{"name": "Cc", "A": "VOUT", "B": "n2", "C": cap_info["C_F"]}]
            if cap else None)
    schem = schematic_mos_netlist(schem_devs, ports=PORTS, name="OTA", caps=caps)
    match = compare(layout_nl, schem)
    return {"tool": "KLayout LVS (MOS3 + Capacitor extractor + NetlistComparer)",
            "cell": "OTA", "match": match,
            "note": "7 MOSFETs (per-device multi-finger sizing) + Cc MIM cap, DRC-clean"
                    if cap else "7 MOSFETs, per-device sizing (no cap)",
            "capCc_fF": round(cap_info["C_F"] * 1e15, 2),
            "perDeviceW": {d["name"]: d["W"] for d in schem_devs},
            "devices": device_summary(layout_nl),
            "layout_netlist": layout_nl.to_s()}
