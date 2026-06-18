"""Two-stage OTA model sanity + the optimization-improvement finding."""

import math

import pytest

from layout_opt.opamp import OpAmpParams, evaluate_opamp
from layout_opt.opamp_opt import (
    GAIN_MIN, GBW_MIN, PM_MIN, SLEW_MIN,
    de_linear, de_log, de_log_refine, random_search,
)


def base(**kw) -> OpAmpParams:
    d = dict(wl1=20, wl3=20, wl5=20, wl6=80, wl7=40,
             itail=20e-6, i6=80e-6, cc=1e-12)
    d.update(kw)
    return OpAmpParams(**d)


# --- model sanity (formulas point the right way) ---------------------------
def test_more_current_raises_gbw():
    lo = evaluate_opamp(base(itail=10e-6)).gbw_hz
    hi = evaluate_opamp(base(itail=40e-6)).gbw_hz
    assert hi > lo                       # GBW ~ gm1 ~ sqrt(Itail)


def test_bigger_cc_lowers_gbw_but_raises_pm():
    small = evaluate_opamp(base(cc=0.5e-12))
    big = evaluate_opamp(base(cc=4e-12))
    assert big.gbw_hz < small.gbw_hz     # GBW = gm1/Cc
    assert big.pm_deg > small.pm_deg     # more compensation -> more phase margin


def test_lower_current_raises_gain():
    # Gain ~ 1/I (output resistance up); lower current -> higher DC gain.
    assert evaluate_opamp(base(itail=8e-6)).gain_db > evaluate_opamp(base(itail=60e-6)).gain_db


def test_power_is_supply_times_current():
    s = evaluate_opamp(base(itail=20e-6, i6=80e-6))
    assert s.power == pytest.approx(1.8 * (20e-6 + 80e-6))


# --- optimization: a feasible spec-meeting design exists and is found -------
def test_optimizer_finds_spec_meeting_design():
    d = de_log_refine(seed=0)
    assert d.feasible
    s = d.specs
    assert s.gain_db >= GAIN_MIN - 1e-6
    assert s.gbw_hz >= GBW_MIN - 1.0
    assert s.pm_deg >= PM_MIN - 1e-6
    assert s.slew >= SLEW_MIN - 1.0


# --- the headline finding: log-space beats linear-space DE ------------------
def test_logspace_beats_linear_and_random():
    seeds = range(4)
    lin = [de_linear(seed=s) for s in seeds]
    log = [de_log(seed=s) for s in seeds]
    rnd = [random_search(seed=s, n=4000) for s in seeds]

    def mean_power(ds):
        ps = [d.power_mw for d in ds if d.feasible]
        return sum(ps) / len(ps)

    # Log-space finds substantially lower-power feasible designs than linear DE,
    # which in turn beats random search.
    assert mean_power(log) < mean_power(lin)
    assert mean_power(lin) < mean_power(rnd)
    # And log-space is the big win (clearly lower power).
    assert mean_power(log) < 0.7 * mean_power(lin)
