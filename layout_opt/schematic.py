"""Schematic ↔ placement ↔ routing — the netlist as single source of truth.

A schematic is devices + a netlist: which device terminals are tied together.
That same connectivity drives everything downstream:

    schematic (netlist)
        │  to_components(positions)   each device → a placeable block,
        ▼                             each terminal → a pin on net N
    placement (Components with pins)
        │  components_to_grid_nets    pins on the same net → one router net
        ▼
    routing (maze / negotiated)

So editing the netlist changes both the placement pins and the router's nets in
lockstep — they can't drift out of sync. Here the schematic is the two-stage
Miller OTA used elsewhere in the project (sizing / ngspice / PPA), now placed
and routed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .interactive import Component, Pin

# Footprint (w,h in cells) and terminal→boundary-offset by device kind.
# MOSFET: gate on the left edge, drain on top, source on bottom.
_KIND = {
    "nmos": {"w": 3, "h": 3, "term": {"G": (0, 1), "D": (1, 0), "S": (1, 2)}},
    "pmos": {"w": 3, "h": 3, "term": {"G": (0, 1), "D": (1, 2), "S": (1, 0)}},
    "cap":  {"w": 3, "h": 2, "term": {"P": (1, 0), "N": (1, 1)}},
    "port": {"w": 1, "h": 1, "term": {"T": (0, 0)}},
}


@dataclass(frozen=True)
class Device:
    name: str
    kind: str                       # nmos | pmos | cap | port
    conns: dict[str, str]           # terminal -> net name

    @property
    def w(self) -> int:
        return _KIND[self.kind]["w"]

    @property
    def h(self) -> int:
        return _KIND[self.kind]["h"]


@dataclass
class Schematic:
    name: str
    devices: list[Device] = field(default_factory=list)

    def nets(self) -> dict[str, list[tuple[str, str]]]:
        """net -> [(device, terminal), ...] (the netlist)."""
        out: dict[str, list[tuple[str, str]]] = {}
        for d in self.devices:
            for term, net in d.conns.items():
                out.setdefault(net, []).append((d.name, term))
        return out

    def to_components(self, positions: dict[str, tuple[int, int]]) -> list[Component]:
        """Build placeable Components; each terminal becomes a Pin on its net."""
        comps = []
        for d in self.devices:
            x, y = positions[d.name]
            pins = [Pin(net, *_KIND[d.kind]["term"][term])
                    for term, net in d.conns.items()]
            comps.append(Component(id=d.name, label=d.name, x=x, y=y,
                                   w=d.w, h=d.h, pins=pins))
        return comps


def two_stage_ota() -> Schematic:
    """Two-stage Miller OTA: input pair + mirror load, gain stage, Miller cap."""
    d = Device
    devs = [
        d("M1", "nmos", {"G": "VINP", "D": "n1", "S": "TAIL"}),
        d("M2", "nmos", {"G": "VINN", "D": "n2", "S": "TAIL"}),
        d("M3", "pmos", {"G": "n1", "D": "n1", "S": "VDD"}),
        d("M4", "pmos", {"G": "n1", "D": "n2", "S": "VDD"}),
        d("M5", "nmos", {"G": "VBIAS", "D": "TAIL", "S": "VSS"}),
        d("M6", "nmos", {"G": "n2", "D": "VOUT", "S": "VSS"}),
        d("M7", "pmos", {"G": "VBIASP", "D": "VOUT", "S": "VDD"}),
        d("Cc", "cap",  {"P": "n2", "N": "VOUT"}),
        # I/O + supply ports
        d("VINP", "port", {"T": "VINP"}),
        d("VINN", "port", {"T": "VINN"}),
        d("VOUT", "port", {"T": "VOUT"}),
        d("VBIAS", "port", {"T": "VBIAS"}),
        d("VBIASP", "port", {"T": "VBIASP"}),
        d("VDD", "port", {"T": "VDD"}),
        d("VSS", "port", {"T": "VSS"}),
    ]
    return Schematic(name="two_stage_ota", devices=devs)


# Which devices are fixed I/O pads (placed on the perimeter) vs. SA-placed core.
PORT_NAMES = ("VINP", "VINN", "VOUT", "VBIAS", "VBIASP", "VDD", "VSS")
CORE_NAMES = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "Cc")
