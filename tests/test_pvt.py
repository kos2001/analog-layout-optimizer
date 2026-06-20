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
