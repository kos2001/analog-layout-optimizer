"""Common-centroid input-pair layout: extraction, LVS, DRC, matching metric."""

import os
import tempfile

import pytest

from layout_opt.diffpair_cc import build_cc_diffpair, PATTERN
from layout_opt.klayout_lvs import lvs_diffpair
from layout_opt.klayout_drc import run_drc


def test_abba_fingers_recombine_into_two_matched_nmos():
    r = lvs_diffpair(guard=False)
    assert r["devices"]["counts"]["nmos"] == 2          # 4 fingers -> 2 devices
    assert r["perDeviceW"] == {"M1": 2.0, "M2": 2.0}    # each W = nf x wf


@pytest.mark.parametrize("guard", [False, True])
def test_diffpair_lvs_matches(guard):
    assert lvs_diffpair(guard=guard)["match"] is True


def test_common_centroid_cancels_linear_gradient():
    _, _, _, m = build_cc_diffpair(guard=False)
    assert m["pattern"] == "ABBA"
    assert m["centroid_offset"] == 0.0                  # shared centroid
    assert m["gradient_mismatch"] == 0.0                # gradient fully cancels
    # the naive segregated (AABB) order does NOT cancel it
    assert m["segregated_mismatch"] > 0.0
    assert m["improvement_x"] is None                   # cc mismatch is 0 -> inf


@pytest.mark.parametrize("guard", [False, True])
def test_diffpair_layout_is_drc_clean(guard):
    ly, _top, _, _ = build_cc_diffpair(guard=guard)
    fd, path = tempfile.mkstemp(suffix=".gds")
    os.close(fd)
    try:
        ly.write(path)
        r = run_drc(path)
    finally:
        os.unlink(path)
    assert r["clean"] is True, r


def test_guard_ring_adds_psdm_tap_shapes():
    ly_g, top_g, _, _ = build_cc_diffpair(guard=True)
    ly_n, top_n, _, _ = build_cc_diffpair(guard=False)
    psdm = ly_g.layer(94, 20)
    # guarded layout has more p-tap (psdm) shapes than the bare array
    assert top_g.shapes(psdm).size() > top_n.shapes(ly_n.layer(94, 20)).size()
