"""Pure-Python layout geometry primitives.

No Cadence dependency. Everything here is verifiable with plain unit tests.
All coordinates are in microns.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle on a (layer, purpose) drawing layer.

    Coordinates are normalized so that ``x0 <= x1`` and ``y0 <= y1``.
    """

    layer: str
    purpose: str
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        # Normalize corners so width()/height() are always non-negative.
        # Capture originals first - assigning x0 before reading it would corrupt the swap.
        x0, y0, x1, y1 = self.x0, self.y0, self.x1, self.y1
        object.__setattr__(self, "x0", min(x0, x1))
        object.__setattr__(self, "x1", max(x0, x1))
        object.__setattr__(self, "y0", min(y0, y1))
        object.__setattr__(self, "y1", max(y0, y1))

    def width(self) -> float:
        return self.x1 - self.x0

    def height(self) -> float:
        return self.y1 - self.y0

    def area(self) -> float:
        return self.width() * self.height()


@dataclass
class Layout:
    """A flat collection of rectangles plus a human-readable name."""

    name: str
    rects: list[Rect] = field(default_factory=list)

    def add(self, rect: Rect) -> Rect:
        self.rects.append(rect)
        return rect

    def bbox(self) -> tuple[float, float, float, float]:
        """Return (x0, y0, x1, y1) bounding box over all rects.

        Raises ValueError on an empty layout - an empty bounding box is not a
        meaningful optimization target and silently returning zeros would mask
        a generator bug.
        """
        if not self.rects:
            raise ValueError(f"layout {self.name!r} has no shapes")
        x0 = min(r.x0 for r in self.rects)
        y0 = min(r.y0 for r in self.rects)
        x1 = max(r.x1 for r in self.rects)
        y1 = max(r.y1 for r in self.rects)
        return (x0, y0, x1, y1)

    def bbox_area(self) -> float:
        x0, y0, x1, y1 = self.bbox()
        return (x1 - x0) * (y1 - y0)

    def rects_on(self, layer: str, purpose: str = "drawing") -> list[Rect]:
        return [r for r in self.rects if r.layer == layer and r.purpose == purpose]
