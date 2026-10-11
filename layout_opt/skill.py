"""Emit a Layout as Cadence SKILL commands.

The command strings mirror virtuoso_bridge's *pure* string builders
(``virtuoso_bridge.virtuoso.layout.ops``). Building the SKILL strings needs no
Virtuoso connection - that is the whole point: the entire generate -> emit
pipeline is verifiable offline as text. Only *running* these strings (via
``client.layout.edit()``) requires a live Virtuoso, which we defer.

Rects are built locally rather than through ``layout_create_rect``: the bridge
formats coordinates with ``:g`` (6 significant digits), which silently moves
any edge beyond 1 mm (``f"{1000.005:g}" == "1000"``). Here every coordinate is
snapped to the database grid and printed exactly. The bridge stays OPTIONAL:
this module imports and emits without it (see commit e5c2171).

When a Virtuoso server is eventually available, the deferred step is simply::

    from virtuoso_bridge import VirtuosoClient
    client = VirtuosoClient.from_env()
    with client.layout.edit(lib, cell) as lay:
        for cmd in emit_skill(layout):
            lay.add(cmd)

or, as one self-contained round-trip that binds ``cv`` and saves::

    client.execute_skill(emit_skill_progn(layout, lib, cell))
"""

from __future__ import annotations

import math
from decimal import Decimal

from .geometry import Layout, Rect

try:
    from virtuoso_bridge.virtuoso.layout.ops import layout_bind_current_or_open_cell_view
    from virtuoso_bridge.virtuoso.ops import save_current_cellview
except Exception:  # pragma: no cover - optional Cadence-side dependency
    layout_bind_current_or_open_cell_view = None
    save_current_cellview = None

# Virtuoso's default database resolution is 1000 DBU/um, so no coordinate finer
# than 1 nm is representable. Pass the PDK manufacturing grid (e.g. 0.005 um on
# SKY130) to snap coarser.
DB_GRID_UM = 0.001


def _escape(value: str) -> str:
    """Escape a Python string for a SKILL string literal (as the bridge does)."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def snap_coord(value: float, grid: float = DB_GRID_UM) -> str:
    """Snap *value* (um) to *grid* and render it exactly, with no float noise.

    Matches ``:g`` output wherever ``:g`` is exact (``0``, ``2.5``, ``0.165``)
    but never truncates: ``1000.005`` stays ``1000.005``.
    """
    if not math.isfinite(value):
        raise ValueError(f"non-finite layout coordinate: {value!r}")
    if not (math.isfinite(grid) and grid > 0):
        raise ValueError(f"grid must be a positive finite number, got {grid!r}")
    step = Decimal(repr(grid))
    exact = Decimal(round(value / grid)) * step       # exact decimal multiple
    text = format(exact, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def rect_skill(r: Rect, *, grid: float = DB_GRID_UM, cv_expr: str = "cv") -> str:
    """``dbCreateRect`` for *r*, same form as the bridge's ``layout_create_rect``."""
    x0, y0, x1, y1 = (snap_coord(v, grid) for v in (r.x0, r.y0, r.x1, r.y1))
    if x0 == x1 or y0 == y1:
        # dbCreateRect returns nil for a zero-area box: the shape would vanish
        raise ValueError(f"rect collapses to zero area on a {grid} um grid: {r}")
    return (
        f'dbCreateRect({cv_expr} list("{_escape(r.layer)}" "{_escape(r.purpose)}") '
        f"list(list({x0} {y0}) list({x1} {y1})))"
    )


def emit_skill(layout: Layout, *, grid: float = DB_GRID_UM) -> list[str]:
    """Return the SKILL command strings that would recreate *layout* in Virtuoso.

    Each command draws into an already-bound ``cv`` (as inside
    ``client.layout.edit()``); see :func:`emit_skill_progn` for a standalone block.
    """
    return [rect_skill(r, grid=grid) for r in layout.rects]


def _bind_cv(lib: str | None, cell: str | None, view: str, mode: str) -> str:
    """SKILL that binds ``cv``: the named cellview, else the open edit window."""
    if lib is None and cell is None:
        return "cv = geGetEditCellView()"
    if not lib or not cell:
        raise ValueError("lib and cell must be given together")
    if layout_bind_current_or_open_cell_view is not None:
        return layout_bind_current_or_open_cell_view(lib, cell, view=view, mode=mode)
    view_type = "maskLayout" if view.strip().lower().startswith("layout") else view
    return (f'cv = dbOpenCellViewByType("{_escape(lib)}" "{_escape(cell)}" '
            f'"{_escape(view)}" "{_escape(view_type)}" "{_escape(mode)}")')


def emit_skill_progn(
    layout: Layout,
    lib: str | None = None,
    cell: str | None = None,
    *,
    view: str = "layout",
    mode: str = "w",
    save: bool = True,
    grid: float = DB_GRID_UM,
) -> str:
    """Wrap all commands in a single SKILL ``progn(...)`` block (one round-trip).

    The block is runnable on its own: it first binds ``cv`` (to *lib*/*cell*
    when given - opened in *mode*, reusing a matching edit window like the
    bridge's ``LayoutEditor`` - otherwise to the current edit cellview), then
    draws every rect and, if *save*, ``dbSave``s the cellview.
    """
    cmds = [_bind_cv(lib, cell, view, mode), *emit_skill(layout, grid=grid)]
    if save:
        cmds.append(save_current_cellview() if save_current_cellview is not None
                    else "dbSave(cv)")
    return "progn(\n  " + "\n  ".join(cmds) + "\n)"
