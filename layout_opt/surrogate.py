"""Gaussian-process surrogate of the expensive ground-truth FoM.

Wraps sklearn's GaussianProcessRegressor with input standardization and a
sensible kernel. The surrogate is what the optimizer queries thousands of
times; the ground truth is only queried a handful of times to train it.

A GP (not a plain regressor) is used so the model also returns a predictive
std - useful for active learning and for flagging low-confidence regions.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

from .generator import DesignParams


@dataclass
class FitMetrics:
    n_train: int
    rmse: float        # on a held-out set, if provided (else nan)
    r2: float          # on a held-out set, if provided (else nan)


class SurrogateModel:
    """params -> predicted FoM (mean, std), trained on ground-truth samples."""

    def __init__(self) -> None:
        kernel = (
            ConstantKernel(1.0, (1e-2, 1e2))
            * RBF(length_scale=np.ones(len(DesignParams.ORDER)),
                  length_scale_bounds=(1e-1, 1e1))
            # Noise floor kept >= 1e-4 so the covariance never goes singular
            # (a zero-noise GP on near-duplicate points overflows in solve).
            + WhiteKernel(noise_level=1e-3, noise_level_bounds=(1e-4, 1e0))
        )
        self._gp = GaussianProcessRegressor(
            kernel=kernel,
            normalize_y=True,
            n_restarts_optimizer=4,
            alpha=1e-3,  # Tikhonov jitter; large enough to keep tiny (n~8)
                         # training sets well-conditioned (avoids matmul overflow)
            random_state=0,
        )
        self._mu = None
        self._sd = None
        self._fitted = False

    # -- internal scaling -------------------------------------------------
    def _x(self, params_list: list[DesignParams]) -> np.ndarray:
        return np.array([p.to_vector() for p in params_list], dtype=float)

    def _standardize(self, X: np.ndarray) -> np.ndarray:
        return (X - self._mu) / self._sd

    # -- public API -------------------------------------------------------
    def fit(self, params_list: list[DesignParams], y: list[float]) -> None:
        X = self._x(params_list)
        self._mu = X.mean(axis=0)
        self._sd = X.std(axis=0)
        self._sd[self._sd == 0] = 1.0
        # Hyperparameter optimization may report length scales near a bound on
        # small samples; that is expected here and not an error, so silence the
        # benign ConvergenceWarning rather than spam the caller.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=ConvergenceWarning)
            self._gp.fit(self._standardize(X), np.asarray(y, dtype=float))
        self._fitted = True

    def predict(self, params_list: list[DesignParams]) -> tuple[np.ndarray, np.ndarray]:
        if not self._fitted:
            raise RuntimeError("surrogate not fitted")
        Xs = self._standardize(self._x(params_list))
        # numpy's SIMD matmul can raise spurious FP flags (overflow/divide) on
        # small arrays even though the result is finite; outputs are validated
        # elsewhere, so suppress the false-positive flags here.
        with np.errstate(all="ignore"):
            mean, std = self._gp.predict(Xs, return_std=True)
        return mean, std

    def predict_one(self, p: DesignParams) -> tuple[float, float]:
        mean, std = self.predict([p])
        return float(mean[0]), float(std[0])

    def score(
        self, params_list: list[DesignParams], y_true: list[float]
    ) -> FitMetrics:
        """Holdout accuracy: RMSE and R^2 of surrogate vs. ground truth."""
        y_true_arr = np.asarray(y_true, dtype=float)
        mean, _ = self.predict(params_list)
        rmse = float(np.sqrt(np.mean((mean - y_true_arr) ** 2)))
        ss_res = float(np.sum((y_true_arr - mean) ** 2))
        ss_tot = float(np.sum((y_true_arr - y_true_arr.mean()) ** 2)) or 1.0
        r2 = 1.0 - ss_res / ss_tot
        return FitMetrics(n_train=len(self._gp.X_train_), rmse=rmse, r2=r2)
