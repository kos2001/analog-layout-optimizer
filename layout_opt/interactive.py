"""Interactive floorplan -> dynamic maze routing.

The static `comparator` demo fixes device placement and only varies net order.
Here the *placement* is the free variable: each component carries its own pins,
and moving a component moves its pins, so the router must re-solve. This backs
the drag-to-place webapp page — every placement change re-runs the maze router.

A component is a rectangle (a device / pad keep-out) plus terminals on its
boundary. The footprint blocks the routing grid; the terminal cells are carved
back out so wires can connect. Pins that share a `net` name are one net.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .maze import Cell, Grid, optimize_net_order, route_all


@dataclass(frozen=True)
class Pin:
    net: str
    dx: int          # offset from the component origin (cells), on its boundary
    dy: int


@dataclass
class Component:
    id: str
    label: str
    x: int
    y: int
    w: int
    h: int
    pins: list[Pin] = field(default_factory=list)

    def abs_pins(self) -> list[tuple[str, Cell]]:
        return [(p.net, (self.x + p.dx, self.y + p.dy)) for p in self.pins]


# Default comparator-style floorplan: input pair, tail/clk source, latch halves,
# and edge pads. Grid is 28x20 cells. Pins sit on component boundaries.
GRID_W, GRID_H = 28, 20


def default_floorplan() -> list[Component]:
    # Each pin sits on the edge facing its net partners, so the default placement
    # routes cleanly; dragging a component away forces the router to detour.
    return [
        Component("m1", "M1 (in+)", 3, 7, 5, 4, [
            Pin("VINP", 0, 1), Pin("OUTN", 0, 3), Pin("TAIL", 4, 3)]),
        Component("m2", "M2 (in-)", 20, 7, 5, 4, [
            Pin("VINN", 4, 1), Pin("OUTP", 4, 3), Pin("TAIL", 0, 3)]),
        Component("tail", "tail/CLK", 11, 2, 5, 3, [
            Pin("CLK", 2, 0), Pin("TAIL", 2, 2)]),
        Component("latchL", "latch L", 3, 14, 5, 4, [Pin("OUTN", 0, 0)]),
        Component("latchR", "latch R", 20, 14, 5, 4, [Pin("OUTP", 4, 0)]),
        Component("padVINP", "VINP pad", 0, 4, 2, 1, [Pin("VINP", 1, 0)]),
        Component("padVINN", "VINN pad", 26, 4, 2, 1, [Pin("VINN", 0, 0)]),
        Component("padCLK", "CLK pad", 13, 0, 2, 1, [Pin("CLK", 0, 0)]),
        Component("padOUTN", "OUTN pad", 0, 18, 2, 1, [Pin("OUTN", 1, 0)]),
        Component("padOUTP", "OUTP pad", 26, 18, 2, 1, [Pin("OUTP", 0, 0)]),
    ]


def _clamp(c: Component, w: int, h: int) -> Component:
    c.x = max(0, min(c.x, w - c.w))
    c.y = max(0, min(c.y, h - c.h))
    return c


def components_to_grid_nets(
    width: int, height: int, components: list[Component]
) -> tuple[Grid, dict[str, list[Cell]]]:
    """Block each footprint; carve out pin cells; group pins into nets."""
    g = Grid(width, height)
    for c in components:
        _clamp(c, width, height)
        g.block_rect(c.x, c.y, c.x + c.w - 1, c.y + c.h - 1)

    nets: dict[str, list[Cell]] = {}
    for c in components:
        for net, cell in c.abs_pins():
            g.blocked.discard(cell)          # a terminal must be routable
            nets.setdefault(net, []).append(cell)

    # A net needs >= 2 distinct terminals to route.
    nets = {n: pins for n, pins in nets.items() if len(set(pins)) >= 2}
    return g, nets


def route_components(
    width: int, height: int, components: list[Component], *, optimize: bool = False
) -> dict:
    """Route the given placement; return a JSON-able payload for the webapp."""
    grid, nets = components_to_grid_nets(width, height, components)
    if optimize and nets:
        sol = optimize_net_order(grid, nets)
    else:
        sol = route_all(grid, nets, list(nets.keys()))

    return {
        "width": width,
        "height": height,
        "blocked": sorted(grid.blocked),
        "components": [
            {"id": c.id, "label": c.label, "x": c.x, "y": c.y, "w": c.w, "h": c.h,
             "pins": [{"net": p.net, "dx": p.dx, "dy": p.dy} for p in c.pins]}
            for c in components
        ],
        "netNames": list(nets.keys()),
        "order": sol.order,
        "optimized": optimize,
        "totalWirelength": sol.total_wirelength,
        "totalBends": sol.total_bends,
        "failed": sol.failed,
        "nets": {
            net: {
                "pins": nets[net],
                "cells": sorted(nr.cells),
                "wirelength": nr.wirelength,
                "bends": nr.bends,
                "routed": nr.routed,
            }
            for net, nr in sol.routes.items()
        },
    }


def components_from_payload(items: list[dict]) -> list[Component]:
    """Rebuild Component objects from a webapp POST body."""
    out: list[Component] = []
    for it in items:
        out.append(Component(
            id=str(it["id"]), label=str(it.get("label", it["id"])),
            x=int(it["x"]), y=int(it["y"]), w=int(it["w"]), h=int(it["h"]),
            pins=[Pin(str(p["net"]), int(p["dx"]), int(p["dy"]))
                  for p in it.get("pins", [])],
        ))
    return out
