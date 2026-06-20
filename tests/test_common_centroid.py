"""Common-centroid matched-array placement + gradient cancellation."""

import pytest

from layout_opt.common_centroid import (
    STRATEGIES, analyze, assign, centroid, gradient_mismatch, layout_payload,
)


def test_equal_device_counts():
    for s in STRATEGIES:
        grid = assign(s, 4, 4)
        flat = [d for row in grid for d in row]
        assert flat.count("A") == flat.count("B") == 8


def test_common_centroid_cancels_linear_gradient():
    cc = assign("common_centroid", 4, 4)
    assert gradient_mismatch(cc, 1.0, 0.0) == pytest.approx(0.0)
    assert gradient_mismatch(cc, 0.0, 1.0) == pytest.approx(0.0)
    assert gradient_mismatch(cc, 1.0, 1.0) == pytest.approx(0.0)
    a, b = centroid(cc, "A"), centroid(cc, "B")
    assert a == pytest.approx(b)                       # coincident centroids


def test_mismatch_ordering_simple_worst_cc_best():
    m = {s: analyze(s, 4, 4).mismatch_diag for s in STRATEGIES}
    assert m["simple"] > m["interdigitated"] > m["common_centroid"]
    assert m["common_centroid"] == pytest.approx(0.0)


def test_interdigitated_cancels_y_only():
    g = assign("interdigitated", 4, 4)
    assert gradient_mismatch(g, 0.0, 1.0) == pytest.approx(0.0)   # y cancels
    assert gradient_mismatch(g, 1.0, 0.0) > 0.0                   # x does not


def test_layout_payload_shape():
    p = layout_payload("common_centroid", 4, 4)
    assert len(p["rects"]) == 16
    assert p["centroidOffset"] == pytest.approx(0.0)
    assert {"x0", "y0", "x1", "y1", "device"} <= set(p["rects"][0])
