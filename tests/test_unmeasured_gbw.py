"""A simulated AC sweep with no 0 dB crossing has no GBW or phase margin.

Those metrics must travel as *unmeasured* end to end — NaN in OpAmpSpecs, None
in every JSON payload, a spec miss in the optimizer, and never a pass in the
flow — instead of being filled in with a sweep endpoint.
"""

import json
import math
from dataclasses import replace

import pytest

import layout_opt.flow_e2e as flow_e2e
import layout_opt.ngspice_backend as nb
from layout_opt.opamp import evaluate_opamp
from layout_opt.opamp_opt import de_log_ngspice, de_log_refine


def _unmeasured_specs(p, *_a, **_k):
    return replace(evaluate_opamp(p), gbw_hz=math.nan, pm_deg=math.nan)


def test_summary_maps_unmeasured_to_none_and_serializes_strictly():
    s = replace(evaluate_opamp(de_log_refine(seed=0).params), gbw_hz=math.nan, pm_deg=math.nan)
    assert s.unmeasured() == ["gbw_hz", "pm_deg"]
    out = s.summary()
    assert out["gbw_mhz"] is None and out["pm_deg"] is None
    assert out["gain_db"] is not None and out["power_mw"] is not None
    json.dumps(out, allow_nan=False)                    # what the API serializer requires


def test_calibration_stops_instead_of_using_an_unmeasured_residual(monkeypatch):
    monkeypatch.setattr(nb, "ngspice_evaluate", _unmeasured_specs)
    out = de_log_ngspice(seed=0, maxiter=30, rounds=3)
    assert out["calibration"]["measured"] is False
    assert out["calibration"]["rounds"] == 1
    assert math.isfinite(out["calibration"]["gbw_min_hz"])   # targets not poisoned by NaN


def test_ngspice_eval_endpoint_reports_null_and_a_note(monkeypatch):
    main = pytest.importorskip("webapp.backend.main")
    monkeypatch.setattr(nb, "ngspice_evaluate", _unmeasured_specs)
    out = main._compute_opamp_ngspice_eval(seed=0, model="generic")
    assert out["status"] == "ran_ngspice"
    assert out["sim"]["gbw_mhz"] is None and out["sim"]["pm_deg"] is None
    assert out["unmeasured"] == ["gbw_hz", "pm_deg"] and out["note"]
    json.dumps(out, allow_nan=False)


def test_full_flow_silicon_stage_warns_and_does_not_pass(monkeypatch):
    monkeypatch.setattr(flow_e2e, "sky130_available", lambda *a, **k: True)
    monkeypatch.setattr(flow_e2e, "sky130_model", lambda *a, **k: nb.GENERIC_NGSPICE)
    monkeypatch.setattr(flow_e2e, "ngspice_evaluate", _unmeasured_specs)
    monkeypatch.setattr(nb, "ngspice_evaluate", _unmeasured_specs)    # calibrated sizing
    r = flow_e2e.run_end_to_end("sa", 1, sky130=True, maxiter=40)
    st = next(s for s in r["stages"] if s["name"].startswith("Silicon"))
    assert st["status"] == "warn" and "not measured" in st["detail"]
    assert r["silicon"]["gbw_mhz"] is None and r["silicon"]["pm_deg"] is None
    json.dumps(r, allow_nan=False)


# --- silicon verify: pass only when real-BSIM specs meet the sizing targets ---
def _silicon_flow(monkeypatch, **overrides):
    from layout_opt.opamp_opt import GAIN_MIN, GBW_MIN, PM_MIN
    good = {"gain_db": GAIN_MIN + 5, "gbw_hz": GBW_MIN * 1.2, "pm_deg": PM_MIN + 5}
    good.update(overrides)
    monkeypatch.setattr(flow_e2e, "sky130_available", lambda *a, **k: True)
    monkeypatch.setattr(flow_e2e, "sky130_model", lambda *a, **k: nb.GENERIC_NGSPICE)
    fake = lambda p, *_a, **_k: replace(evaluate_opamp(p), **good)          # noqa: E731
    monkeypatch.setattr(flow_e2e, "ngspice_evaluate", fake)
    monkeypatch.setattr(nb, "ngspice_evaluate", fake)                     # calibrated sizing
    r = flow_e2e.run_end_to_end("sa", 1, sky130=True, maxiter=40)
    return r, next(s for s in r["stages"] if s["name"].startswith("Silicon"))


def test_silicon_stage_passes_when_specs_met(monkeypatch):
    r, st = _silicon_flow(monkeypatch)
    assert st["status"] == "pass"
    assert r["silicon"]["meetsSpec"] is True and r["silicon"]["misses"] == []


def test_silicon_stage_flags_unstable_pm_instead_of_passing(monkeypatch):
    r, st = _silicon_flow(monkeypatch, pm_deg=40.0)
    assert st["status"] == "warn"
    assert "unstable" in st["detail"] and "PM" in st["detail"]
    assert r["silicon"]["meetsSpec"] is False


def test_silicon_stage_lists_every_spec_miss(monkeypatch):
    from layout_opt.opamp_opt import GAIN_MIN, GBW_MIN
    r, st = _silicon_flow(monkeypatch, gain_db=GAIN_MIN - 0.4, gbw_hz=GBW_MIN * 0.5)
    assert st["status"] == "warn"
    assert {m["metric"] for m in r["silicon"]["misses"]} == {"gain_db", "gbw_mhz"}
    assert "unstable" not in st["detail"]


# --- calibration never trades a feasible design for an infeasible target -----
def test_calibration_keeps_last_feasible_design_when_a_gap_cannot_close(monkeypatch):
    # Silicon gain 7 dB below the analytic model, whatever the sizing: raising
    # the analytic gain target can't close it and would end infeasible.
    from layout_opt.opamp_opt import GAIN_MIN
    monkeypatch.setattr(nb, "ngspice_evaluate",
                        lambda p, *_a, **_k: replace(evaluate_opamp(p),
                                                     gain_db=evaluate_opamp(p).gain_db - 7.0))
    out = de_log_ngspice(seed=0, maxiter=30, rounds=3)
    cal = out["calibration"]
    assert out["design"].feasible
    assert cal["meetsSpec"] is False and cal["limitedBy"] == ["gain_db"]
    assert out["sim"].gain_db < GAIN_MIN


def test_calibration_closes_a_small_gap(monkeypatch):
    # A 0.4 dB analytic-vs-silicon gain gap is closable by tightening the target.
    monkeypatch.setattr(nb, "ngspice_evaluate",
                        lambda p, *_a, **_k: replace(evaluate_opamp(p),
                                                     gain_db=evaluate_opamp(p).gain_db - 0.4))
    out = de_log_ngspice(seed=0, maxiter=40, rounds=3)
    assert out["calibration"]["meetsSpec"] is True and out["design"].feasible
    assert out["calibration"]["limitedBy"] == []


def test_sky130_flow_sizes_against_silicon_and_reports_calibration(monkeypatch):
    r, st = _silicon_flow(monkeypatch)
    sizing = next(x for x in r["stages"] if x["name"].startswith("Sizing"))
    assert "SKY130-calibrated" in sizing["detail"]
    assert r["calibration"]["meetsSpec"] is True and r["calibration"]["rounds"] >= 1
    plain = flow_e2e.run_end_to_end("sa", 1, sky130=False, maxiter=40)
    assert plain["calibration"] is None


def test_calibration_backtracks_an_overshooting_pm_target(monkeypatch):
    # Silicon PM 20 deg below the model: the full residual step asks the
    # analytic sizing for ~85 deg (unreachable), so calibration must backtrack
    # to a reachable target instead of stopping at round one.
    from layout_opt.opamp_opt import PM_MIN
    fake = lambda p, *_a, **_k: replace(evaluate_opamp(p),                # noqa: E731
                                        pm_deg=evaluate_opamp(p).pm_deg - 20.0)
    monkeypatch.setattr(nb, "ngspice_evaluate", fake)
    first = de_log_ngspice(seed=0, maxiter=40, rounds=1)["sim"].pm_deg
    out = de_log_ngspice(seed=0, maxiter=40, rounds=3)
    assert out["design"].feasible
    assert out["calibration"]["rounds"] >= 2
    assert out["sim"].pm_deg > first + 2.0
    assert out["calibration"]["pm_min_deg"] > PM_MIN
