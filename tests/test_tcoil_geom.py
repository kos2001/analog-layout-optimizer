"""T-coil geometry: spiral shape + L/k extraction sanity."""

import pytest

from layout_opt.tcoil_geom import (
    TCoilGeometry, evaluate_geometry, extract, spiral_points, to_normalized,
)


def g(n=3, w=3, s=2, inner=30):
    return TCoilGeometry(turns=n, width=w, spacing=s, inner=inner)


def test_d_out_formula():
    assert g(3, 3, 2, 30).d_out() == pytest.approx(30 + 2 * 3 * 5)  # 60


def test_more_turns_more_inductance():
    assert extract(g(4)).L_nH > extract(g(2)).L_nH


def test_inductance_in_physical_nH_range():
    L = extract(g(3)).L_nH
    assert 0.1 < L < 10.0          # on-chip µm spiral -> sub-10 nH


def test_coupling_bounded_and_rises_with_turns():
    assert 0.1 <= extract(g(2)).k < extract(g(5)).k <= 0.92


def test_spiral_points_count_and_centered():
    pts = spiral_points(g(3))
    assert len(pts) == 4 * 3 + 1
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    assert abs((min(xs) + max(xs)) / 2) < 1e-6   # centered on origin
    assert abs((min(ys) + max(ys)) / 2) < 1e-6


def test_to_normalized_scaling():
    # norm L = L_phys / (R^2 C_L)
    p = to_normalized(1.0, 0.8, r_ohm=100.0, cl_ff=100.0, cb_norm=0.14)
    assert p.L == pytest.approx(1e-9 / (100.0 ** 2 * 100e-15), rel=1e-6)
    assert p.k == 0.8


def test_evaluate_geometry_extends_bandwidth_at_good_node():
    r = evaluate_geometry(g(3), r_ohm=300.0, cl_ff=30.0)
    assert r["bw_extension"] > 1.5
    assert r["extract"].L_nH > 0
