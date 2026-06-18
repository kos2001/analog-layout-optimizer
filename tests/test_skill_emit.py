"""SKILL emission is verifiable offline: it is pure string building.

These tests pin the emitted SKILL against virtuoso_bridge's own ops builder,
proving the generate -> emit pipeline is correct without any Virtuoso.
"""

from virtuoso_bridge.virtuoso.layout.ops import layout_create_rect

from layout_opt.generator import DiffPairConfig, DesignParams, generate_layout
from layout_opt.skill import emit_skill, emit_skill_progn


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
