"""Comparator routing scenario for the maze router — congested on purpose.

A clocked tail device, a differential input pair, and a cross-coupled latch
driving OUTP/OUTN. Devices are blockages on the routing grid. The two outputs
must cross between the left and right halves, which are separated by a wall with
only a SHORT passage (11,8) and a LONG detour passage (11,17). Both outputs
prefer the short passage, so whichever net is routed first takes it and the
other must take the long detour — net **order** changes the total wirelength a
lot. The nets are listed in a deliberately poor order so the naive (as-given)
ordering is clearly suboptimal vs. the optimizer's choice.
"""

from __future__ import annotations

from .maze import Grid

W, H = 24, 20


def build_comparator() -> tuple[Grid, dict[str, list[tuple[int, int]]]]:
    """Return (grid, nets) for the (congested) comparator routing problem."""
    g = Grid(W, H)

    # Central wall splitting left/right halves, open ONLY at the short passage
    # (11, 8) and the long detour passage (11, 17).
    g.block_rect(11, 0, 11, 7)
    g.block_rect(11, 9, 11, 16)
    g.block_rect(11, 18, 11, 19)
    # Transistor active areas (keep-outs) constraining the routes.
    g.block_rect(3, 3, 8, 6)      # input pair M1
    g.block_rect(15, 3, 20, 6)    # input pair M2

    # Listed in a deliberately suboptimal order (naive == this order).
    nets = {
        "TAIL": [(13, 1), (20, 1)],        # local (top-right)
        "OUTP": [(5, 10), (18, 10)],       # crosses L<->R; wants the short passage
        "OUTN": [(2, 8), (20, 8)],         # crosses L<->R; also wants it
        "VINP": [(0, 12), (4, 12)],        # local (left)
        "VINN": [(23, 12), (19, 12)],      # local (right)
        "CLK":  [(2, 1), (9, 1)],          # local (top-left)
    }
    return g, nets
