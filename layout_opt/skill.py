"""Emit a Layout as Cadence SKILL commands.

This uses virtuoso_bridge's *pure* string-builder functions
(``virtuoso_bridge.virtuoso.layout.ops``). Building the SKILL strings needs no
Virtuoso connection - that is the whole point: the entire generate -> emit
pipeline is verifiable offline as text. Only *running* these strings (via
``client.layout.edit()``) requires a live Virtuoso, which we defer.

When a Virtuoso server is eventually available, the deferred step is simply::

    from virtuoso_bridge import VirtuosoClient
    client = VirtuosoClient.from_env()
    with client.layout.edit(lib, cell) as lay:
        for cmd in emit_skill(layout):
            lay.add(cmd)
"""

from __future__ import annotations

from virtuoso_bridge.virtuoso.layout.ops import layout_create_rect

from .geometry import Layout


def emit_skill(layout: Layout) -> list[str]:
    """Return the SKILL command strings that would recreate *layout* in Virtuoso."""
    return [
        layout_create_rect(r.layer, r.purpose, r.x0, r.y0, r.x1, r.y1)
        for r in layout.rects
    ]


def emit_skill_progn(layout: Layout) -> str:
    """Wrap all commands in a single SKILL ``progn(...)`` block (one round-trip)."""
    cmds = emit_skill(layout)
    return "progn(\n  " + "\n  ".join(cmds) + "\n)"
