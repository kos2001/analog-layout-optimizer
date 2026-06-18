from layout_opt.generator import (
    DiffPairConfig,
    DesignParams,
    active_bbox,
    generate_layout,
)

import pytest


def make_params(**kw) -> DesignParams:
    base = dict(w_finger=0.5, l=0.03, finger_pitch=0.18, guard_gap=0.20, gr_width=0.05)
    base.update(kw)
    return DesignParams(**base)


def test_params_vector_roundtrip():
    p = make_params()
    assert DesignParams.from_vector(p.to_vector()) == p
    assert p.to_vector() == [0.5, 0.03, 0.18, 0.20, 0.05]


def test_from_vector_wrong_length_raises():
    with pytest.raises(ValueError):
        DesignParams.from_vector([1, 2, 3])


def test_rect_count_matches_topology():
    cfg = DiffPairConfig(nf=4)  # total fingers = 8
    lay = generate_layout(make_params(), cfg)
    # 1 diffusion + 2*nf poly fingers + 4 guard-ring bars
    assert len(lay.rects) == 1 + 2 * cfg.nf + 4
    assert len(lay.rects_on("PO")) == 2 * cfg.nf
    assert len(lay.rects_on("OD")) == 1
    assert len(lay.rects_on("M1")) == 4


def test_bbox_equals_outer_guard_ring():
    cfg = DiffPairConfig(nf=4)
    p = make_params()
    lay = generate_layout(p, cfg)

    ax0, ay0, ax1, ay1 = active_bbox(p, cfg)
    expected = (
        ax0 - p.guard_gap - p.gr_width,
        ay0 - p.guard_gap - p.gr_width,
        ax1 + p.guard_gap + p.gr_width,
        ay1 + p.guard_gap + p.gr_width,
    )
    got = lay.bbox()
    assert got == pytest.approx(expected)


def test_area_matches_closed_form():
    cfg = DiffPairConfig(nf=4)
    p = make_params()
    lay = generate_layout(p, cfg)

    n = 2 * cfg.nf
    active_w = (n - 1) * p.finger_pitch + p.l + 2 * cfg.diff_ext
    active_h = p.w_finger + 2 * cfg.poly_ext
    margin = 2 * (p.guard_gap + p.gr_width)
    expected = (active_w + margin) * (active_h + margin)
    assert lay.bbox_area() == pytest.approx(expected)


def test_wider_pitch_increases_area():
    cfg = DiffPairConfig(nf=4)
    a = generate_layout(make_params(finger_pitch=0.18), cfg).bbox_area()
    b = generate_layout(make_params(finger_pitch=0.30), cfg).bbox_area()
    assert b > a
