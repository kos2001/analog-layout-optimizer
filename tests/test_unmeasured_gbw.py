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
    r = flow_e2e.run_end_to_end("sa", 1, sky130=True)
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
    monkeypatch.setattr(flow_e2e, "ngspice_evaluate",
                        lambda p, *_a, **_k: replace(evaluate_opamp(p), **good))
    r = flow_e2e.run_end_to_end("sa", 1, sky130=True)
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
