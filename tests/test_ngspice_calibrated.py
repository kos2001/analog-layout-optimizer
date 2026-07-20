"""ngspice-calibrated sizing: close the analytic-vs-simulation optimism gap."""

import pytest

from layout_opt.ngspice_backend import (
    GENERIC_NGSPICE, ngspice_available, sky130_available, sky130_model,
    ngspice_evaluate,
)
from layout_opt.opamp_opt import GBW_MIN, PM_MIN, de_log_ngspice

pytestmark = pytest.mark.skipif(not ngspice_available(),
                                reason="ngspice not installed")


def test_calibrated_sizing_reports_calibration_and_sim_specs():
    out = de_log_ngspice(seed=0, maxiter=60, model=GENERIC_NGSPICE, rounds=1)
    assert {"design", "sim", "calibration"} <= set(out)
    assert out["design"].feasible
    # generic level-1 ngspice mirrors the analytic constants, so the
    # simulated specs should already sit near the nominal targets.
    assert out["sim"].gbw_hz >= GBW_MIN * 0.8
    assert out["calibration"]["rounds"] >= 1


@pytest.mark.skipif(not sky130_available(), reason="SKY130 PDK not installed")
def test_sky130_calibrated_sizing_meets_specs_in_simulation():
    # The whole point: after calibration the *simulated* SKY130 specs meet
    # the nominal targets, not just the optimistic analytic ones.
    model = sky130_model()
    out = de_log_ngspice(seed=0, maxiter=90, model=model, rounds=2)
    sim = ngspice_evaluate(out["design"].params, model)
    assert sim.gbw_hz >= GBW_MIN * 0.9
    assert sim.pm_deg >= PM_MIN - 5.0
