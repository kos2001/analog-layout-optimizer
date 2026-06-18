"""StrongARM comparator routing scenario for the maze router.

A clocked tail device, a differential input pair, and a cross-coupled latch
driving OUTP/OUTN. Devices are blockages on the routing grid; each net lists its
pin cells. A 1-cell pinch in the central channel makes the two outputs contend,
so net order changes the total wirelength (a discrete routing optimization).
"""

from __future__ import annotations

from .maze import Grid

W, H = 31, 22


def build_comparator() -> tuple[Grid, dict[str, list[tuple[int, int]]]]:
    """Return (grid, nets) for the comparator routing problem."""
    g = Grid(W, H)

    # Transistor active areas as routing blockages (keep-outs on this layer).
    g.block_rect(12, 1, 18, 3)    # tail / clock device (top center)
    g.block_rect(6, 6, 12, 9)     # input pair M1 (left)
    g.block_rect(18, 6, 24, 9)    # input pair M2 (right)
    g.block_rect(6, 13, 12, 16)   # latch L (lower left)
    g.block_rect(18, 13, 24, 16)  # latch R (lower right)
    # Side margins below the input pair are blocked: nets heading to the bottom
    # pads must funnel through the central channel (cols 13-17).
    g.block_rect(0, 11, 4, 21)
    g.block_rect(26, 11, 30, 21)
    # 1-cell pinch: the only passage from drain row 10 into the lower channel is
    # (15, 11); both outputs contend for it, so net order changes the total.
    g.block_rect(13, 11, 14, 11)
    g.block_rect(16, 11, 17, 11)

    nets = {
        "CLK":  [(15, 0), (15, 4)],                 # clock pad -> tail gate
        "TAIL": [(11, 4), (19, 4), (15, 4)],        # tail node -> both input sources
        "VINP": [(0, 7), (5, 7)],                   # left input pad -> M1 gate
        "VINN": [(30, 7), (25, 7)],                 # right input pad -> M2 gate
        # Outputs cross in the shared channel: left node -> right pad and vice
        # versa, so on one layer the net routed second must detour.
        "OUTN": [(13, 12), (13, 10), (16, 21)],     # latch-L node -> M1 drain -> bottom-RIGHT pad
        "OUTP": [(17, 12), (17, 10), (14, 21)],     # latch-R node -> M2 drain -> bottom-LEFT pad
    }
    return g, nets
