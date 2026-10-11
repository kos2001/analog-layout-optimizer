"""PVT corner analysis — aggregation logic (mocked) + availability.

The live SKY130 run is ~15-18 s/corner, too slow for CI, so the worst-case
aggregation is tested with a stubbed simulator; a real run is exercised only
through the CLI/endpoint when the PDK is present.
"""

import layout_opt.pvt as pvt
from layout_opt.pvt import full_grid, run_pvt, ESSENTIAL
from layout_opt.opamp import OpAmpParams, OpAmpSpecs


def _p():
    return OpAmpParams(wl1=20, wl3=20, wl5=20, wl6=80, wl7=40,
                       itail=20e-6, i6=80e-6, cc=1e-12)


def test_full_grid_is_27_corners():
    assert len(full_grid()) == 27          # 3 process × 3 temp × 3 voltage


def test_unavailable_without_pdk(monkeypatch):
    monkeypatch.setattr(pvt, "sky130_available", lambda *a, **k: False)
    r = run_pvt(_p())
    assert r["available"] is False and "error" in r


def test_worst_case_aggregation(monkeypatch):
    monkeypatch.setattr(pvt, "ngspice_available", lambda *a, **k: True)
    monkeypatch.setattr(pvt, "sky130_available", lambda *a, **k: True)

    # Stub the simulator: PM/gain/GBW vary by corner so worst-case is well-defined.
    specs = {
        ("tt", 27.0, 1.8): (80.0, 60e6, 70.0),
        ("ss", 125.0, 1.62): (75.0, 40e6, 48.0),   # worst gain/GBW/PM
        ("ff", -40.0, 1.98): (82.0, 80e6, 72.0),
    }
    def fake_eval(p, model):
        proc = model.name.split("-")[1]
        key = next(k for k in specs if k[0] == proc)
        g, gbw, pm = specs[key]
        return OpAmpSpecs(gain_db=g, gbw_hz=gbw, pm_deg=pm, slew=1e7,
                          power=1e-4, vov1=0.1, vov3=0.1, vov5=0.1, vov6=0.1, vov7=0.1)
    monkeypatch.setattr(pvt, "ngspice_evaluate", fake_eval)

    r = run_pvt(_p(), corners=ESSENTIAL)
    assert r["available"] and r["nCorners"] == 3
    assert r["worst"]["gain_db"] == 75.0
    assert r["worst"]["gbw_mhz"] == 40.0
    assert r["worst"]["pm_deg"] == 48.0
    assert r["stable"] is True               # worst PM 48 > 45
    assert r["nominal"]["process"] == "tt"


def test_unstable_flag(monkeypatch):
    monkeypatch.setattr(pvt, "ngspice_available", lambda *a, **k: True)
    monkeypatch.setattr(pvt, "sky130_available", lambda *a, **k: True)
    monkeypatch.setattr(pvt, "ngspice_evaluate", lambda p, m: OpAmpSpecs(
        gain_db=70, gbw_hz=50e6, pm_deg=30.0, slew=1e7, power=1e-4,
        vov1=0.1, vov3=0.1, vov5=0.1, vov6=0.1, vov7=0.1))
    r = run_pvt(_p(), corners=ESSENTIAL[:1])
    assert r["stable"] is False               # PM 30 < 45


# --- worst-corner verdict: missing / NaN is unverified, never pass ------------
import math

import pytest

from layout_opt.ngspice_backend import NgspiceUnavailable
from layout_opt.pvt import pick_robust, score_corners, worst_margin


def _stub(monkeypatch, table):
    """table: process -> (gain_db, gbw_hz, pm_deg) or an exception to raise."""
    monkeypatch.setattr(pvt, "ngspice_available", lambda *a, **k: True)
    monkeypatch.setattr(pvt, "sky130_available", lambda *a, **k: True)

    def fake_eval(p, model):
        v = table[model.name.split("-")[1]]
        if isinstance(v, Exception):
            raise v
        g, gbw, pm = v
        return OpAmpSpecs(gain_db=g, gbw_hz=gbw, pm_deg=pm, slew=1e7, power=1e-4,
                          vov1=0.1, vov3=0.1, vov5=0.1, vov6=0.1, vov7=0.1)
    monkeypatch.setattr(pvt, "ngspice_evaluate", fake_eval)


def test_failed_corner_is_unverified_not_dropped(monkeypatch):
    # ss (the corner most likely to fail PM) does not simulate: tt/ff look
    # great, but the design must not be reported stable / passed.
    _stub(monkeypatch, {"tt": (80.0, 60e6, 70.0),
                        "ss": NgspiceUnavailable("no data"),
                        "ff": (82.0, 80e6, 72.0)})
    r = run_pvt(_p(), corners=ESSENTIAL)
    assert r["errors"] == 1 and r["failed"][0]["corner"].startswith("ss/")
    assert r["stable"] is False
    assert r["verdict"]["passed"] is False
    assert r["verdict"]["status"] == "unverified"
    assert any("ss/" in u for u in r["verdict"]["unverified"])


def test_nan_metric_is_unverified_not_worst_case_garbage(monkeypatch):
    _stub(monkeypatch, {"tt": (80.0, 60e6, 70.0),
                        "ss": (75.0, 40e6, float("nan")),
                        "ff": (82.0, 80e6, 72.0)})
    r = run_pvt(_p(), corners=ESSENTIAL)
    assert r["worst"]["pm_deg"] == 70.0                 # NaN excluded from min()
    ss = next(c for c in r["corners"] if c["process"] == "ss")
    assert ss["pm_deg"] is None and ss["unmeasured"] == ["pm_deg"]
    assert r["stable"] is False and r["verdict"]["status"] == "unverified"


def test_verdict_names_the_deciding_corner(monkeypatch):
    _stub(monkeypatch, {"tt": (80.0, 60e6, 70.0), "ss": (75.0, 40e6, 48.0),
                        "ff": (82.0, 80e6, 72.0)})
    r = run_pvt(_p(), corners=ESSENTIAL,
                targets={"pm_deg": {"min": 60.0}, "gbw_mhz": {"min": 30.0}})
    v = r["verdict"]
    assert v["status"] == "fail" and v["violations"] == ["pm_deg 48 < 60 at ss/125C/1.62V"]
    assert v["worst"]["pm_deg"]["corner"] == "ss/125C/1.62V"
    assert v["worst"]["pm_deg"]["margin"] == pytest.approx((48 - 60) / 60)
    assert r["worstCorner"]["gbw_mhz"] == "ss/125C/1.62V"


def test_margin_sign_follows_bound_kind():
    per = {"a": {"power": 2.0, "gbw": 100.0}, "b": {"power": 3.0, "gbw": 80.0}}
    v = score_corners(per, {"power": {"max": 4.0}, "gbw": {"min": 50.0}})
    assert v["passed"]
    assert v["worst"]["power"]["corner"] == "b"           # max bound: highest value decides
    assert v["worst"]["power"]["margin"] == pytest.approx(0.25)
    assert v["worst"]["gbw"]["corner"] == "b"             # min bound: lowest value decides
    assert v["worst"]["gbw"]["margin"] == pytest.approx(0.6)
    assert worst_margin(v) == pytest.approx(0.25)


def test_two_sided_bound_records_the_tighter_side():
    v = score_corners({"x": {"vcm": 0.95}}, {"vcm": {"min": 0.5, "max": 1.0}})
    assert v["worst"]["vcm"]["kind"] == "max"
    assert v["worst"]["vcm"]["margin"] == pytest.approx(0.05)


def test_pick_robust_uses_worst_margin_and_ignores_unverified():
    t = {"pm_deg": {"min": 45.0}}
    fast_but_thin = {"name": "thin", "verdict": score_corners(
        {"tt": {"pm_deg": 80.0}, "ss": {"pm_deg": 46.0}}, t)}
    steady = {"name": "steady", "verdict": score_corners(
        {"tt": {"pm_deg": 60.0}, "ss": {"pm_deg": 55.0}}, t)}
    unknown = {"name": "unknown", "verdict": score_corners(
        {"tt": {"pm_deg": 90.0}, "ss": None}, t)}
    assert pick_robust([fast_but_thin, unknown, steady])["name"] == "steady"
    assert pick_robust([unknown]) is None
    assert math.isclose(worst_margin(steady["verdict"]), 10 / 45)
