"""SKILL emission is verifiable offline: it is pure string building.

These tests pin the emitted SKILL against virtuoso_bridge's own ops builder,
proving the generate -> emit pipeline is correct without any Virtuoso.
"""

import pytest
from virtuoso_bridge.virtuoso.layout.ops import layout_create_rect

from layout_opt.generator import DiffPairConfig, DesignParams, generate_layout
from layout_opt.geometry import Layout, Rect
from layout_opt.skill import emit_skill, emit_skill_progn, snap_coord


def _params() -> DesignParams:
    return DesignParams(
        w_finger=0.5, l=0.03, finger_pitch=0.18, guard_gap=0.20, gr_width=0.05
    )


def test_emit_one_command_per_rect():
    lay = generate_layout(_params(), DiffPairConfig(nf=4))
    cmds = emit_skill(lay)
    assert len(cmds) == len(lay.rects)
    assert all(c.startswith("dbCreateRect(") for c in cmds)


def test_emit_matches_ops_builder_exactly():
    lay = generate_layout(_params(), DiffPairConfig(nf=4))
    cmds = emit_skill(lay)
    # First rect is the diffusion; reproduce its SKILL independently.
    r = lay.rects[0]
    assert cmds[0] == layout_create_rect(r.layer, r.purpose, r.x0, r.y0, r.x1, r.y1)


def test_progn_wraps_all_commands():
    lay = generate_layout(_params(), DiffPairConfig(nf=4))
    block = emit_skill_progn(lay)
    assert block.startswith("progn(")
    assert block.rstrip().endswith(")")
    assert block.count("dbCreateRect(") == len(lay.rects)


def test_progn_binds_and_saves_cv():
    lay = generate_layout(_params(), DiffPairConfig(nf=4))
    block = emit_skill_progn(lay, "LIB", "CELL")
    body = block.splitlines()
    # cv is bound before the first rect and saved after the last one, so the
    # block runs standalone (it used to reference an unbound cv)
    assert body[1].strip().startswith("cv = ")
    assert '"LIB"' in body[1] and '"CELL"' in body[1] and '"maskLayout"' in body[1]
    assert "dbSave(" in body[-2]
    # without lib/cell it binds the open edit window instead
    assert "cv = geGetEditCellView()" in emit_skill_progn(lay)
    assert "dbSave(" not in emit_skill_progn(lay, save=False)


def test_coordinates_beyond_1mm_survive_exactly():
    # the bridge builder formats with :g (6 significant digits), which turns
    # 1000.005 um into 1000 - emit_skill must not lose the grid step
    assert f"{1000.005:g}" == "1000"
    lay = Layout("big", [Rect("M1", "drawing", 1000.005, 2500.125, 1234.565, 2500.13)])
    (cmd,) = emit_skill(lay, grid=0.005)
    assert cmd == ('dbCreateRect(cv list("M1" "drawing") '
                   "list(list(1000.005 2500.125) list(1234.565 2500.13)))")
    # float noise is snapped to the grid, never printed
    noisy = Layout("n", [Rect("M1", "drawing", 0.1 + 0.2, 0, 0.16499999999999998, 1)])
    assert emit_skill(noisy)[0].endswith("list(list(0.165 0) list(0.3 1)))")


def test_off_grid_and_bad_coordinates_rejected():
    with pytest.raises(ValueError):
        emit_skill(Layout("z", [Rect("M1", "drawing", 0, 0, 0.002, 1)]), grid=0.005)
    with pytest.raises(ValueError):
        snap_coord(float("nan"))
    with pytest.raises(ValueError):
        snap_coord(1.0, grid=0.0)
