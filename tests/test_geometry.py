from layout_opt.geometry import Layout, Rect

import pytest


def test_rect_normalizes_corners():
    r = Rect("M1", "drawing", 2.0, 3.0, 0.0, 1.0)
    assert (r.x0, r.y0, r.x1, r.y1) == (0.0, 1.0, 2.0, 3.0)
    assert r.width() == 2.0
    assert r.height() == 2.0
    assert r.area() == 4.0


def test_layout_bbox_and_area():
    lay = Layout("t")
    lay.add(Rect("OD", "drawing", 0, 0, 1, 2))
    lay.add(Rect("M1", "drawing", -1, -1, 0.5, 0.5))
    assert lay.bbox() == (-1, -1, 1, 2)
    assert lay.bbox_area() == (1 - (-1)) * (2 - (-1))  # 2 * 3 = 6


def test_empty_layout_bbox_raises():
    with pytest.raises(ValueError):
        Layout("empty").bbox()


def test_rects_on_filters_by_layer():
    lay = Layout("t")
    lay.add(Rect("PO", "drawing", 0, 0, 1, 1))
    lay.add(Rect("M1", "drawing", 0, 0, 1, 1))
    assert len(lay.rects_on("PO")) == 1
    assert len(lay.rects_on("M1")) == 1
    assert lay.rects_on("OD") == []
