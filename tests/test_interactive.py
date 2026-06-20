"""Interactive floorplan -> dynamic routing."""

from layout_opt.interactive import (
    GRID_W, GRID_H, Component, Pin, components_from_payload,
    components_to_grid_nets, default_floorplan, route_components,
)


def test_default_floorplan_routes_clean():
    comps = default_floorplan()
    r = route_components(GRID_W, GRID_H, comps, optimize=True)
    assert r["failed"] == []                       # every net connects
    assert r["totalWirelength"] > 0
    assert set(r["netNames"]) == {"VINP", "VINN", "CLK", "TAIL", "OUTN", "OUTP"}


def test_pins_are_carved_out_of_blockage():
    comps = default_floorplan()
    g, nets = components_to_grid_nets(GRID_W, GRID_H, comps)
    for pins in nets.values():
        for cell in pins:
            assert cell not in g.blocked          # terminal must be routable


def test_moving_a_component_changes_wirelength():
    comps = default_floorplan()
    base = route_components(GRID_W, GRID_H, comps)["totalWirelength"]
    # Pull the latch halves far from their drains -> longer OUTN/OUTP.
    moved = [Component(c.id, c.label, c.x, c.y, c.w, c.h, c.pins) for c in comps]
    for c in moved:
        if c.id == "latchL":
            c.x, c.y = 0, 0
    after = route_components(GRID_W, GRID_H, moved)["totalWirelength"]
    assert after != base


def test_optimize_order_not_worse_than_naive():
    comps = default_floorplan()
    naive = route_components(GRID_W, GRID_H, comps, optimize=False)
    opt = route_components(GRID_W, GRID_H, comps, optimize=True)
    assert (len(opt["failed"]), opt["totalWirelength"]) <= (
        len(naive["failed"]), naive["totalWirelength"])


def test_clamp_keeps_component_in_bounds():
    comps = [Component("x", "x", 100, 100, 4, 4, [Pin("A", 0, 0)])]
    g, _ = components_to_grid_nets(GRID_W, GRID_H, comps)
    assert comps[0].x == GRID_W - 4 and comps[0].y == GRID_H - 4


def test_from_payload_roundtrip():
    body = [{"id": "m1", "label": "M1", "x": 3, "y": 7, "w": 5, "h": 4,
             "pins": [{"net": "VINP", "dx": 0, "dy": 1}]}]
    comps = components_from_payload(body)
    assert comps[0].id == "m1" and comps[0].pins[0].net == "VINP"
