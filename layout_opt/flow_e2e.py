"""End-to-end one-click flow: sizing → P&R → sign-off → post-layout → silicon.

Chains every stage of the project into a single run and returns a staged report
(status + one-line summary per stage) plus the full payload. This is the
"press one button, get a verified, parasitic-aware, optionally silicon-checked
design" path — the whole PoC in one call.

    sizing (DE)  →  schematic  →  placement (SA)  →  routing (negotiated)
        →  sign-off (DRC + LVS)  →  post-layout (parasitics)  →  [SKY130 verify]
"""

from __future__ import annotations

from .opamp import evaluate_opamp
from .opamp_opt import de_log_refine
from .placement import run_flow
from .schematic import two_stage_ota
from .ngspice_backend import (
    GENERIC_NGSPICE, NgspiceUnavailable, ngspice_available, ngspice_evaluate,
    sky130_model, sky130_available,
)


def _stage(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def rank_candidates(results: list[dict]) -> int:
    """Index of the best full-flow run by sign-off ranking.

    Order: PASS verdict > fewest unrouted nets > LVS clean > fewest DRC
    errors/warnings > highest post-layout phase margin. This replaces
    "pick a random seed and hope" with a deterministic best-of-N choice.
    """
    def key(r: dict):
        so, rt, pl = r["signoff"], r["routing"], r["postlayout"]
        return (
            0 if r["verdict"] == "PASS" else 1,
            len(rt["failed"]),
            0 if so["lvs"]["clean"] else 1,
            so["drcErrors"],
            so.get("drcWarnings", 0),
            -pl["post"]["pm_deg"],
        )
    return min(range(len(results)), key=lambda i: key(results[i]))


def run_best_of(place: str = "sa", seeds=(0, 1, 2, 3), sky130: bool = False,
                maxiter: int = 90, runner=None) -> dict:
    """Run the full flow across several seeds and return the best by sign-off.

    `runner(place, seed, sky130, maxiter)` is injectable for tests.
    """
    run = runner or (lambda place, seed, sky130, maxiter:
                     run_end_to_end(place=place, seed=seed, sky130=sky130,
                                    maxiter=maxiter))
    seeds = list(seeds)
    results = [run(place=place, seed=s, sky130=sky130, maxiter=maxiter)
               for s in seeds]
    best = rank_candidates(results)
    out = results[best]
    out["sweep"] = {
        "seeds": seeds,
        "bestSeed": seeds[best],
        "verdicts": [r["verdict"] for r in results],
    }
    return out


def run_end_to_end(place: str = "sa", seed: int = 0, sky130: bool = False,
                   maxiter: int = 90) -> dict:
    stages = []

    # 1. Sizing — minimize power s.t. gain/GBW/PM/slew specs (DE in log space).
    d = de_log_refine(seed=seed, maxiter=maxiter)
    s = evaluate_opamp(d.params)
    stages.append(_stage(
        "Sizing (DE)", "pass" if d.feasible else "fail",
        f"gain {s.gain_db:.1f} dB · GBW {s.gbw_hz/1e6:.1f} MHz · PM {s.pm_deg:.0f}° · "
        f"{s.power*1e3:.3f} mW" + ("" if d.feasible else " · specs not met")))

    # 2-6. schematic → placement → routing → sign-off → post-layout (sized).
    flow = run_flow(place=place, seed=seed, sizing=d.params)
    sch = two_stage_ota()

    stages.append(_stage("Schematic", "info",
                         f"two-stage Miller OTA · {len(sch.devices)} devices · "
                         f"{len(flow['netlist'])} nets"))
    stages.append(_stage("Placement (SA)", "info",
                         f"HPWL {flow['hpwl']} ({place})"))
    r = flow["routing"]
    stages.append(_stage(
        "Routing (negotiated)", "pass" if not r["failed"] else "fail",
        f"WL {r['totalWirelength']} · {r['totalVias']} vias · "
        + ("all nets routed" if not r["failed"] else f"{len(r['failed'])} unrouted")))
    so = flow["signoff"]
    stages.append(_stage(
        "Sign-off (DRC+LVS)", "pass" if so["verdict"] == "PASS" else "fail",
        f"LVS {'✓' if so['lvs']['clean'] else '✗'} · "
        f"DRC {so['drcErrors']} err / {so['drcWarnings']} warn"))
    pl = flow["postlayout"]
    # Physical sign-off (DRC/LVS) is the tape-out gate; post-layout PM is a
    # separate performance-closure check — advisory (warn), not a DRC failure.
    stages.append(_stage(
        "Post-layout (parasitics)", "pass" if pl["stable"] else "warn",
        f"PM {pl['pre']['pm_deg']}° → {pl['post']['pm_deg']}° (Δ{pl['deltaPM']}) · "
        + ("stable" if pl["stable"] else "PM margin lost — re-spin sizing / add comp")))

    # 7. Optional silicon verify on the sized design.
    silicon = None
    if sky130:
        if sky130_available():
            try:
                ss = ngspice_evaluate(d.params, sky130_model())
                silicon = {"model": "sky130-tt", "gain_db": round(ss.gain_db, 2),
                           "gbw_mhz": round(ss.gbw_hz / 1e6, 2), "pm_deg": round(ss.pm_deg, 1)}
                stages.append(_stage("Silicon verify (SKY130)", "pass",
                                     f"{silicon['gain_db']} dB · {silicon['gbw_mhz']} MHz · "
                                     f"{silicon['pm_deg']}° (real BSIM)"))
            except NgspiceUnavailable as e:
                stages.append(_stage("Silicon verify (SKY130)", "warn", str(e)))
        else:
            stages.append(_stage("Silicon verify (SKY130)", "warn",
                                 "SKY130 PDK not installed (set PDK_ROOT)"))

    # Overall verdict: every gating stage must pass.
    gating = [st for st in stages if st["status"] in ("pass", "fail")]
    verdict = "PASS" if all(st["status"] == "pass" for st in gating) else "FAIL"

    return {
        **flow,
        "stages": stages,
        "verdict": verdict,
        "sizing": {
            "feasible": d.feasible,
            "gain_db": round(s.gain_db, 2), "gbw_mhz": round(s.gbw_hz / 1e6, 2),
            "pm_deg": round(s.pm_deg, 1), "power_mw": round(s.power * 1e3, 4),
            "wl1": round(d.params.wl1, 1), "wl6": round(d.params.wl6, 1),
            "itail_uA": round(d.params.itail * 1e6, 1), "cc_pF": round(d.params.cc * 1e12, 2),
        },
        "silicon": silicon,
    }
