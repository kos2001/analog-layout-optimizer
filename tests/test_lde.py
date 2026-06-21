"""Layout-dependent effects: STI/LOD + WPE Vth-shift model and dummy benefit."""

from layout_opt.lde import (
    lod_stress, lod_vth, wpe_vth, array_lod_offset, diffpair_lde,
)


def test_lod_stress_decreases_with_distance():
    # a finger far from the OD edge sees less STI stress than one at the edge
    assert lod_stress(0.3, 0.3) > lod_stress(3.0, 3.0)
    assert lod_vth(0.3, 0.3) > lod_vth(3.0, 3.0)


def test_wpe_decays_with_well_distance():
    assert wpe_vth(0.0) > wpe_vth(1.0) > wpe_vth(5.0)
    assert wpe_vth(50.0) < 1e-3


def test_common_centroid_alone_leaves_edge_mismatch():
    # ABBA cancels the linear gradient but the outer fingers (both A) still carry
    # more STI stress -> a residual LOD mismatch with zero dummies.
    m = array_lod_offset(["A", "B", "B", "A"], dummies=0, pitch=1.65)
    assert m["mismatch_mV"] > 1.0


def test_dummies_reduce_lod_mismatch_monotonically():
    pitch = 1.65
    m0 = array_lod_offset(["A", "B", "B", "A"], 0, pitch)["mismatch_mV"]
    m1 = array_lod_offset(["A", "B", "B", "A"], 1, pitch)["mismatch_mV"]
    m2 = array_lod_offset(["A", "B", "B", "A"], 2, pitch)["mismatch_mV"]
    assert m0 > m1 > m2
    assert m2 < 1.0                                  # two dummies nearly eliminate it


def test_diffpair_lde_scan_reports_reduction():
    r = diffpair_lde(["A", "B", "B", "A"], 1.65, dummy_options=(0, 1, 2))
    assert r["scan"][0]["reduction_x"] == 1.0
    assert r["scan"][-1]["reduction_x"] > r["scan"][1]["reduction_x"] > 1.0
