"""The GP surrogate: predicts, and gets more accurate with more samples."""

import numpy as np
import pytest

from layout_opt.generator import DEFAULT_BOUNDS, DiffPairConfig, bounds_vector
from layout_opt.surrogate import SurrogateModel
from layout_opt.surrogate_opt import _lhs
from layout_opt.truth import truth_fom


CFG = DiffPairConfig()
BNDS = bounds_vector(DEFAULT_BOUNDS)


def _dataset(n: int, seed: int):
    xs = _lhs(n, BNDS, seed=seed)
    ys = [truth_fom(x, CFG) for x in xs]
    return xs, ys


def test_predict_before_fit_raises():
    with pytest.raises(RuntimeError):
        SurrogateModel().predict_one(_lhs(1, BNDS, seed=0)[0])


def test_predict_returns_finite_mean_and_std():
    xs, ys = _dataset(20, seed=2)
    m = SurrogateModel()
    m.fit(xs, ys)
    mean, std = m.predict(xs)
    assert mean.shape == (20,)
    assert np.all(np.isfinite(mean))
    assert np.all(std >= 0)


def test_accuracy_improves_with_more_samples():
    train_x, train_y = _dataset(48, seed=2)
    test_x, test_y = _dataset(40, seed=3)

    small = SurrogateModel(); small.fit(train_x[:8], train_y[:8])
    large = SurrogateModel(); large.fit(train_x[:40], train_y[:40])

    rmse_small = small.score(test_x, test_y).rmse
    rmse_large = large.score(test_x, test_y).rmse
    assert rmse_large < rmse_small
    assert large.score(test_x, test_y).r2 > 0.9
