"""Common-centroid matched-array layout — a core analog placement technique.

Matched devices (a differential pair, a current mirror) drift apart if a process
gradient (oxide thickness, implant dose, stress, temperature) falls differently
on each. The fix is geometric: arrange the unit cells of devices A and B so both
share the *same centroid*. Then any *linear* gradient contributes equally to A
and B and cancels to first order.

Three placements, worst→best for a linear gradient:

    simple          A A B B      segregated — centroids far apart
    interdigitated  A B A B      1-D interleave — cancels one axis, not both
    common_centroid A A B B      2-D cross-quad — centroids coincide, both axes
                    A A B B
                    B B A A
                    B B A A

`gradient_mismatch` quantifies the residual: model a linear gradient g·position
and return the normalized |mean_A - mean_B| (≈0 ⇒ matched). Pure geometry, no PDK.
"""

from __future__ import annotations

from dataclasses import dataclass

STRATEGIES = ("simple", "interdigitated", "common_centroid")


def assign(strategy: str, rows: int, cols: int) -> list[list[str]]:
    """Return a rows×cols grid of 'A'/'B' device labels for the strategy."""
    grid = [["A"] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            if strategy == "simple":
                dev = "A" if c < cols // 2 else "B"
            elif strategy == "interdigitated":
                dev = "A" if c % 2 == 0 else "B"
            elif strategy == "common_centroid":
                # 2×2 cross-quad super-blocks: (A B / B A) by quadrant parity.
                qr, qc = r // (rows // 2 or 1), c // (cols // 2 or 1)
                dev = "A" if (qr + qc) % 2 == 0 else "B"
            else:
                raise ValueError(f"unknown strategy {strategy!r}")
            grid[r][c] = dev
    return grid


def _cells(grid: list[list[str]], dev: str) -> list[tuple[float, float]]:
    return [(c + 0.5, r + 0.5)
            for r, row in enumerate(grid) for c, d in enumerate(row) if d == dev]


def centroid(grid: list[list[str]], dev: str) -> tuple[float, float]:
    pts = _cells(grid, dev)
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)


def gradient_mismatch(grid: list[list[str]], gx: float = 1.0, gy: float = 1.0) -> float:
    """Residual device mismatch under a linear gradient g·position (normalized).

    0 ⇒ A and B see the same average gradient (common centroid achieved).
    """
    rows, cols = len(grid), len(grid[0])
    def mean(dev):
        pts = _cells(grid, dev)
        return sum(gx * x + gy * y for x, y in pts) / len(pts)
    span = gx * cols + gy * rows
    return abs(mean("A") - mean("B")) / span if span else 0.0


@dataclass
class CCResult:
    strategy: str
    rows: int
    cols: int
    grid: list[list[str]]
    centroid_a: tuple[float, float]
    centroid_b: tuple[float, float]
    centroid_offset: float            # distance between A and B centroids
    mismatch_x: float
    mismatch_y: float
    mismatch_diag: float


def analyze(strategy: str, rows: int = 4, cols: int = 4) -> CCResult:
    grid = assign(strategy, rows, cols)
    ca, cb = centroid(grid, "A"), centroid(grid, "B")
    off = ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5
    return CCResult(
        strategy=strategy, rows=rows, cols=cols, grid=grid,
        centroid_a=ca, centroid_b=cb, centroid_offset=round(off, 4),
        mismatch_x=round(gradient_mismatch(grid, 1.0, 0.0), 4),
        mismatch_y=round(gradient_mismatch(grid, 0.0, 1.0), 4),
        mismatch_diag=round(gradient_mismatch(grid, 1.0, 1.0), 4),
    )


def layout_payload(strategy: str, rows: int = 4, cols: int = 4,
                   pitch: float = 1.0) -> dict:
    """Rects + centroids for the webapp canvas (one rect per unit cell)."""
    res = analyze(strategy, rows, cols)
    rects = []
    for r in range(rows):
        for c in range(cols):
            dev = res.grid[r][c]
            rects.append({
                "device": dev, "row": r, "col": c,
                "x0": c * pitch, "y0": r * pitch,
                "x1": (c + 1) * pitch, "y1": (r + 1) * pitch,
            })
    return {
        "strategy": strategy, "rows": rows, "cols": cols, "pitch": pitch,
        "rects": rects,
        "centroidA": list(res.centroid_a), "centroidB": list(res.centroid_b),
        "centroidOffset": res.centroid_offset,
        "mismatchX": res.mismatch_x, "mismatchY": res.mismatch_y,
        "mismatchDiag": res.mismatch_diag,
        "bbox": {"x0": 0.0, "y0": 0.0, "x1": cols * pitch, "y1": rows * pitch},
    }


def compare(rows: int = 4, cols: int = 4) -> dict:
    return {"rows": rows, "cols": cols,
            "strategies": [layout_payload(s, rows, cols) for s in STRATEGIES]}
