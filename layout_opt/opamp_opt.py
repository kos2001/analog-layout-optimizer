"""OTA sizing: constrained min-power optimization + algorithm experiments.

Problem: minimize power subject to gain / GBW / phase-margin / slew specs and
device saturation (overdrive windows). ~2.7% of the box is feasible, so the
optimizer must both *find* the feasible region and minimize within it.

This module provides several optimizer strategies so the experiment harness can
measure which algorithmic choices actually help (the point of the study):

    de_linear        differential evolution on raw parameters (baseline)
    de_log           DE on log-transformed parameters (I and Cc span decades)
    de_log_refine    de_log then a local SLSQP polish (multi-start refinement)
    random_search    uniform random sampling (reference floor)

All share one objective: feasibility-first (drive every spec violation to zero),
then minimize power among feasible points.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import differential_evolution, minimize

from .opamp import BOUNDS, OpAmpParams, bounds_vector, evaluate_opamp

# --- spec targets (the "tight" regime) -------------------------------------
GAIN_MIN = 80.0        # dB
GBW_MIN = 50e6         # Hz
PM_MIN = 65.0          # deg
SLEW_MIN = 50e6        # V/s
VOV_MIN = 0.08         # V (saturation margin)
VOV_MAX = 0.40         # V (headroom)

POWER_SCALE = 1e-3     # report/compare power in mW

# Parasitic guard-band: post-layout routing adds capacitance on the internal
# node n2 and on VOUT, and the n2 pole p_n2 = 1/(r1*C_n2) collapses PM when
# power-minimal sizing makes r1 huge. Guard-banded sizing therefore constrains
# the *estimated post-layout* PM (with typical extracted caps, measured ~8 fF
# on n2 / ~13 fF on VOUT for this flow) instead of just raising the nominal
# PM target, which the analytic model cannot see.
C_N2_EST_F = 10e-15
C_OUT_EST_F = 20e-15


@dataclass
class Design:
    params: OpAmpParams
    power_mw: float
    violation: float      # total normalized spec shortfall (0 == feasible)
    feasible: bool
    nfev: int

    @property
    def specs(self):
        return evaluate_opamp(self.params)


def _violation_from_specs(s, p: OpAmpParams, *, gbw_min: float = GBW_MIN,
                          pm_min: float = PM_MIN) -> float:
    """Total normalized spec shortfall for an already-evaluated spec set.

    Shared by the analytical and the Spectre-backed objectives so both enforce
    exactly the same constraints. `gbw_min`/`pm_min` allow guard-banded targets.
    """
    v = 0.0
    v += max(0.0, (GAIN_MIN - s.gain_db) / GAIN_MIN)
    v += max(0.0, (gbw_min - s.gbw_hz) / gbw_min)
    v += max(0.0, (pm_min - s.pm_deg) / pm_min)
    v += max(0.0, (SLEW_MIN - s.slew) / SLEW_MIN)
    for vov in (s.vov1, s.vov3, s.vov5, s.vov6, s.vov7):
        v += max(0.0, (VOV_MIN - vov) / VOV_MIN)
        v += max(0.0, (vov - VOV_MAX) / VOV_MAX)
    return v


def _violation(p: OpAmpParams, *, gbw_min: float = GBW_MIN,
               pm_min: float = PM_MIN) -> float:
    """Total normalized spec shortfall (analytical model); 0 means feasible."""
    return _violation_from_specs(evaluate_opamp(p), p,
                                 gbw_min=gbw_min, pm_min=pm_min)


def _objective(p: OpAmpParams, feas_weight: float = 1e3, *,
               gbw_min: float = GBW_MIN, pm_min: float = PM_MIN) -> float:
    """Feasibility-first: big penalty * violation, then power (mW) when feasible."""
    v = _violation(p, gbw_min=gbw_min, pm_min=pm_min)
    pw = evaluate_opamp(p).power / POWER_SCALE
    if v > 0:
        return feas_weight * v + 10.0   # keep infeasible strictly worse than any feasible
    return pw


def _design_from_x(x, nfev, *, gbw_min: float = GBW_MIN,
                   pm_min: float = PM_MIN) -> Design:
    p = OpAmpParams.from_vector(x)
    v = _violation(p, gbw_min=gbw_min, pm_min=pm_min)
    return Design(
        params=p,
        power_mw=evaluate_opamp(p).power / POWER_SCALE,
        violation=v,
        feasible=(v <= 1e-9),
        nfev=int(nfev),
    )


# --- parameter <-> log-space mapping ---------------------------------------
_B = np.array(bounds_vector())
_LOG_LO = np.log10(_B[:, 0])
_LOG_HI = np.log10(_B[:, 1])


def _from_log(xl):
    return 10.0 ** np.asarray(xl)


# --- strategies -------------------------------------------------------------
def de_linear(seed=0, maxiter=120) -> Design:
    res = differential_evolution(
        lambda x: _objective(OpAmpParams.from_vector(x)),
        bounds=bounds_vector(), seed=seed, maxiter=maxiter,
        tol=1e-9, polish=True, updating="deferred",
    )
    return _design_from_x(res.x, res.nfev)


def de_log(seed=0, maxiter=120) -> Design:
    res = differential_evolution(
        lambda xl: _objective(OpAmpParams.from_vector(_from_log(xl))),
        bounds=list(zip(_LOG_LO, _LOG_HI)), seed=seed, maxiter=maxiter,
        tol=1e-9, polish=True, updating="deferred",
    )
    return _design_from_x(_from_log(res.x), res.nfev)


def _guardband_violation(p: OpAmpParams) -> float:
    """Estimated post-layout PM shortfall (routing caps on n2 / VOUT applied)."""
    from .parasitics import post_layout_specs
    post = post_layout_specs(p, C_OUT_EST_F, C_N2_EST_F)
    return max(0.0, (PM_MIN - post["pm_deg"]) / PM_MIN)


def de_log_refine(seed=0, maxiter=120, guardband: bool = False) -> Design:
    """de_log, then a local SLSQP polish in log-space from the DE optimum.

    `guardband=True` additionally requires the *estimated post-layout* PM
    (typical extracted routing caps applied) to meet PM_MIN, so the sizing
    survives parasitic extraction instead of collapsing on the n2 pole.
    """
    def obj(xl):
        p = OpAmpParams.from_vector(_from_log(xl))
        v = _violation(p)
        if guardband:
            v += _guardband_violation(p)
        pw = evaluate_opamp(p).power / POWER_SCALE
        return 1e3 * v + 10.0 if v > 0 else pw

    res = differential_evolution(
        obj, bounds=list(zip(_LOG_LO, _LOG_HI)), seed=seed, maxiter=maxiter,
        tol=1e-9, polish=False, updating="deferred",
    )
    nfev = int(res.nfev)
    x0 = res.x
    loc = minimize(
        obj, x0, method="SLSQP", bounds=list(zip(_LOG_LO, _LOG_HI)),
        options={"maxiter": 200, "ftol": 1e-10},
    )
    nfev += int(loc.nfev)
    best = loc.x if obj(loc.x) <= obj(x0) else x0
    d = _design_from_x(_from_log(best), nfev)
    if guardband and _guardband_violation(d.params) > 1e-9:
        return Design(params=d.params, power_mw=d.power_mw,
                      violation=d.violation + _guardband_violation(d.params),
                      feasible=False, nfev=d.nfev)
    return d


def random_search(seed=0, n=15000) -> Design:
    rng = np.random.default_rng(seed)
    lo, hi = _B[:, 0], _B[:, 1]
    best = None
    best_obj = float("inf")
    for _ in range(n):
        x = lo + rng.random(len(lo)) * (hi - lo)
        o = _objective(OpAmpParams.from_vector(x))
        if o < best_obj:
            best_obj, best = o, x
    return _design_from_x(best, n)


STRATEGIES = {
    "de_linear": de_linear,
    "de_log": de_log,
    "de_log_refine": de_log_refine,
    "random_search": random_search,
}
