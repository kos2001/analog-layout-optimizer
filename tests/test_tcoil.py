"""T-coil analytic bandwidth-extension model + optimization."""

import numpy as np
import pytest

from layout_opt.tcoil import (
    TCoilParams,
    bandwidth,
    bw_extension,
    optimize_tcoil,
    peaking_db,
    transimpedance,
)


def test_dc_gain_is_unity():
    for p in (TCoilParams(0, 0, 0), TCoilParams(0.5, 0.5, 0.2)):
        assert abs(transimpedance(p, 0.0)) == pytest.approx(1.0, abs=1e-9)


def test_no_coil_is_reference_bandwidth():
    p = TCoilParams(L=0.0, k=0.0, Cb=0.0)
    assert bandwidth(p) == pytest.approx(1.0, rel=0.02)
    assert peaking_db(p) <= 1e-6


def test_response_rolls_off_at_high_frequency():
    p = TCoilParams(0.3, 0.5, 0.1)
    assert abs(transimpedance(p, 1e3)) < 1e-2  # ~1/w^2 rolloff


def test_shunt_peaking_extends_about_1_8x():
    # Pure shunt peaking (k=0, Cb=0) is the classic ~1.8x maximally-flat result.
    p = TCoilParams(L=0.5, k=0.0, Cb=0.0)
    assert 1.6 < bw_extension(p) < 2.0


def test_maximally_flat_tcoil_reaches_about_3x():
    r = optimize_tcoil(peak_limit_db=0.1, seed=0)
    assert r.peaking_db <= 0.15
    assert r.bw_extension > 2.5            # textbook T-coil ~2.8-3x
    # ...and it beats shunt peaking at comparable flatness.
    assert r.bw_extension > bw_extension(TCoilParams(0.5, 0.0, 0.0))


def test_relaxing_peaking_allows_more_bandwidth():
    flat = optimize_tcoil(peak_limit_db=0.1, seed=0).bw_extension
    peaky = optimize_tcoil(peak_limit_db=3.0, seed=0).bw_extension
    assert peaky > flat
