"""PVT corner analysis on real SKY130 silicon (ngspice).

A design that meets spec at nominal (typical process, 1.8 V, 27 °C) can fail at
a corner — slow-slow process, low supply, hot/cold. Real sign-off runs the OTA
across the Process / Voltage / Temperature grid and reports the *worst case*.
This uses the SKY130 BSIM models (`tt/ff/ss` corners) + a supply/temperature
sweep, so the robustness numbers are silicon-grade, not analytic.

Requires the SKY130 PDK (see `ngspice_backend.sky130_available`); degrades to a
clear "unavailable" otherwise.

The verdict follows two sign-off rules (ported from ppa-eda-agent's
analog_loop.score/pick_winner):

  * The worst corner governs: a spec met at tt and missed at ss is missed.
  * A spec with no measurement behind it is *unverified*, never passed. A corner
    whose simulation failed, or that returned NaN/inf, is not silently dropped
    from the worst case — it makes the verdict `unverified`.

Margins are directional (a `min` bound's margin is value-limit, a `max` bound's
is limit-value, both relative to |limit|), so ranking designs by their worst
margin cannot pick the slowest design for a speed spec by a sign error.
"""

from __future__ import annotations

import math
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


# Default PVT targets: the stability criterion this module has always reported
# as `stable` (PM > 45 deg at every corner). Callers pass their own spec.
DEFAULT_TARGETS: dict[str, dict[str, float]] = {"pm_deg": {"min": 45.0}}

METRICS = ("gain_db", "gbw_mhz", "pm_deg")


def full_grid():
    return tuple((p, t, v) for p in PROCESS for t in TEMPS for v in VOLTS)


def corner_label(proc: str, temp: float, vdd: float) -> str:
    return f"{proc}/{temp:g}C/{vdd:g}V"


def _measured(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def score_corners(per_corner: dict[str, dict | None], targets: dict) -> dict:
    """Worst-corner verdict for one design.

    `per_corner` maps a corner label to its measurements ({metric: value}), or
    to None when that corner's simulation failed. `targets` maps a metric to
    {"min": x} and/or {"max": y}. Returns passed / violations / unverified and,
    per metric, the deciding corner with its directional margin.
    """
    violations: list[str] = []
    unverified: list[str] = []
    worst: dict = {}
    for key, bound in targets.items():
        values = {c: (m or {}).get(key) for c, m in per_corner.items()}
        present = {c: float(v) for c, v in values.items() if _measured(v)}
        for corner in values:
            if corner not in present:
                unverified.append(f"{key} not measured at {corner}")
        if not present:
            continue
        candidates = []
        if "max" in bound:
            corner, value = max(present.items(), key=lambda kv: (kv[1], kv[0]))
            lim = bound["max"]
            candidates.append({"corner": corner, "value": value, "limit": lim,
                               "kind": "max",
                               "margin": (lim - value) / abs(lim) if lim else -value})
            if value > lim:
                violations.append(f"{key} {value:.6g} > {lim:.6g} at {corner}")
        if "min" in bound:
            corner, value = min(present.items(), key=lambda kv: (kv[1], kv[0]))
            lim = bound["min"]
            candidates.append({"corner": corner, "value": value, "limit": lim,
                               "kind": "min",
                               "margin": (value - lim) / abs(lim) if lim else value})
            if value < lim:
                violations.append(f"{key} {value:.6g} < {lim:.6g} at {corner}")
        if candidates:
            # A two-sided spec records the bound that is actually deciding.
            worst[key] = min(candidates, key=lambda c: c["margin"])
    return {"passed": not violations and not unverified,
            "status": ("fail" if violations else
                       "unverified" if unverified else "pass"),
            "violations": violations, "unverified": unverified, "worst": worst}


def worst_margin(verdict: dict) -> float | None:
    """Smallest directional margin across a verdict's specs (None if none)."""
    margins = [e["margin"] for e in (verdict.get("worst") or {}).values()
               if _measured(e.get("margin"))]
    return min(margins) if margins else None


def pick_robust(results: list[dict]) -> dict | None:
    """The passing design with the most room to spare at its worst corner.

    `results` are run_pvt() payloads (or any dict with a "verdict" from
    score_corners). Only fully verified passes are eligible; among them the
    largest worst directional margin wins. Ties keep the earliest result.
    """
    passing = [r for r in results if (r.get("verdict") or {}).get("passed")]
    if not passing:
        return None
    return max(passing, key=lambda r: worst_margin(r["verdict"]) or 0.0)


def run_pvt(p: OpAmpParams, corners=ESSENTIAL, pdk_root: str | None = None,
            targets: dict | None = None) -> dict:
    """Evaluate gain/GBW/PM at each (process, temp, vdd) corner; report worst case.

    Failed simulations and non-finite metrics are kept as *unmeasured* corners:
    `worst` is taken over measured values only, but the `verdict` (and
    `stable`) cannot pass while any requested corner is missing a measurement.
    """
    targets = DEFAULT_TARGETS if targets is None else targets
    if not (ngspice_available() and sky130_available(pdk_root)):
        return {"available": False,
                "error": "PVT needs ngspice + the SKY130 PDK (set PDK_ROOT / volare enable)."}

    base = sky130_model(pdk_root=pdk_root)
    lib = base.header.split('"')[1]
    out, failed = [], []
    per_corner: dict[str, dict | None] = {}
    for proc, temp, vdd in corners:
        label = corner_label(proc, temp, vdd)
        model = replace(base, name=f"sky130-{proc}",
                        header=f'.lib "{lib}" {proc}', vdd=vdd, temp=temp)
        try:
            s = ngspice_evaluate(p, model)
        except NgspiceUnavailable as e:
            failed.append({"corner": label, "error": str(e)[:200]})
            per_corner[label] = None
            continue
        raw = {"gain_db": s.gain_db, "gbw_mhz": s.gbw_hz / 1e6, "pm_deg": s.pm_deg}
        meas = {k: float(v) for k, v in raw.items() if _measured(v)}
        rec = {"process": proc, "temp_c": temp, "vdd": vdd}
        rec["gain_db"] = round(meas["gain_db"], 2) if "gain_db" in meas else None
        rec["gbw_mhz"] = round(meas["gbw_mhz"], 2) if "gbw_mhz" in meas else None
        rec["pm_deg"] = round(meas["pm_deg"], 1) if "pm_deg" in meas else None
        missing = [k for k in METRICS if rec[k] is None]
        if missing:
            rec["unmeasured"] = missing
        out.append(rec)
        per_corner[label] = {k: rec[k] for k in METRICS if rec[k] is not None}
    corners = out
    verdict = score_corners(per_corner, targets)

    if not corners:
        return {"available": True, "error": "all PVT points failed to simulate",
                "corners": [], "failed": failed, "errors": len(failed),
                "verdict": verdict, "stable": False}

    def _worst(key: str):
        vals = [(c[key], corner_label(c["process"], c["temp_c"], c["vdd"]))
                for c in corners if c[key] is not None]
        return min(vals) if vals else (None, None)

    worst, worst_corner = {}, {}
    for key in METRICS:
        worst[key], worst_corner[key] = _worst(key)
    nominal = next((c for c in corners
                    if c["process"] == "tt" and c["temp_c"] == 27.0 and c["vdd"] == 1.8), corners[0])
    pm_ok = score_corners(per_corner, {"pm_deg": {"min": 45.0}})
    # `stable` keeps its meaning (worst PM > 45 deg) but is only claimed when
    # PM was actually measured at every requested corner.
    stable = (not pm_ok["unverified"] and worst["pm_deg"] is not None
              and worst["pm_deg"] > 45.0)
    return {"available": True, "nCorners": len(corners), "errors": len(failed),
            "corners": corners, "failed": failed, "worst": worst,
            "worstCorner": worst_corner, "nominal": nominal,
            "stable": stable, "verdict": verdict,
            "worstMargin": worst_margin(verdict)}
