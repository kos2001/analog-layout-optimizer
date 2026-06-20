"""PVT corner analysis on real SKY130 silicon (ngspice).

A design that meets spec at nominal (typical process, 1.8 V, 27 °C) can fail at
a corner — slow-slow process, low supply, hot/cold. Real sign-off runs the OTA
across the Process / Voltage / Temperature grid and reports the *worst case*.
This uses the SKY130 BSIM models (`tt/ff/ss` corners) + a supply/temperature
sweep, so the robustness numbers are silicon-grade, not analytic.

Requires the SKY130 PDK (see `ngspice_backend.sky130_available`); degrades to a
clear "unavailable" otherwise.
"""

from __future__ import annotations

from dataclasses import replace

from .opamp import OpAmpParams
from .ngspice_backend import (
    NgspiceUnavailable, ngspice_available, ngspice_evaluate,
    sky130_model, sky130_available,
)

PROCESS = ("ss", "tt", "ff")
TEMPS = (-40.0, 27.0, 125.0)
VOLTS = (1.62, 1.8, 1.98)        # 1.8 V ±10%

# Each SKY130 ngspice point is ~15-18 s (the full PDK .lib parses every model),
# so the default is the 3 *essential* corners; pass full_grid() for all 27.
ESSENTIAL = (("tt", 27.0, 1.8),       # nominal
             ("ss", 125.0, 1.62),     # slow / hot / low-V  -> worst speed & PM
             ("ff", -40.0, 1.98))     # fast / cold / high-V -> worst stability & power


def full_grid():
    return tuple((p, t, v) for p in PROCESS for t in TEMPS for v in VOLTS)


def run_pvt(p: OpAmpParams, corners=ESSENTIAL, pdk_root: str | None = None) -> dict:
    """Evaluate gain/GBW/PM at each (process, temp, vdd) corner; report worst case."""
    if not (ngspice_available() and sky130_available(pdk_root)):
        return {"available": False,
                "error": "PVT needs ngspice + the SKY130 PDK (set PDK_ROOT / volare enable)."}

    base = sky130_model(pdk_root=pdk_root)
    lib = base.header.split('"')[1]
    out, errors = [], 0
    for proc, temp, vdd in corners:
        model = replace(base, name=f"sky130-{proc}",
                        header=f'.lib "{lib}" {proc}', vdd=vdd, temp=temp)
        try:
            s = ngspice_evaluate(p, model)
            out.append({"process": proc, "temp_c": temp, "vdd": vdd,
                        "gain_db": round(float(s.gain_db), 2),
                        "gbw_mhz": round(float(s.gbw_hz) / 1e6, 2),
                        "pm_deg": round(float(s.pm_deg), 1)})
        except NgspiceUnavailable:
            errors += 1
    corners = out

    if not corners:
        return {"available": True, "error": "all PVT points failed to simulate", "corners": []}

    worst = {
        "gain_db": min(c["gain_db"] for c in corners),
        "gbw_mhz": min(c["gbw_mhz"] for c in corners),
        "pm_deg": min(c["pm_deg"] for c in corners),
    }
    nominal = next((c for c in corners
                    if c["process"] == "tt" and c["temp_c"] == 27.0 and c["vdd"] == 1.8), corners[0])
    return {"available": True, "nCorners": len(corners), "errors": errors,
            "corners": corners, "worst": worst, "nominal": nominal,
            "stable": worst["pm_deg"] > 45.0}
