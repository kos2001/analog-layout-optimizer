"""End-to-end one-click flow: sizing → P&R → sign-off → post-layout → silicon.

Chains every stage of the project into a single run and returns a staged report
(status + one-line summary per stage) plus the full payload. This is the
"press one button, get a verified, parasitic-aware, optionally silicon-checked
design" path — the whole PoC in one call.

    sizing (DE)  →  schematic  →  placement (SA)  →  routing (negotiated)
        →  sign-off (DRC + LVS)  →  post-layout (parasitics)  →  [SKY130 verify]
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import pickle
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from .opamp import evaluate_opamp
from .opamp_opt import de_log_refine
from .placement import run_flow
from .schematic import two_stage_ota
from .runlog import Profiler, merge_stats, stage
from .ngspice_backend import (
    GENERIC_NGSPICE, NgspiceUnavailable, ngspice_available, ngspice_evaluate,
    sky130_model, sky130_available,
)

_log = logging.getLogger("alo")


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


def select_best(seeds, results: list[dict]) -> dict:
    """Best run by sign-off ranking, annotated with the sweep summary.

    Returns a shallow copy so (possibly cached / shared) per-seed results are
    never mutated.
    """
    seeds = list(seeds)
    best = rank_candidates(results)
    return {**results[best], "sweep": {
        "seeds": seeds,
        "bestSeed": seeds[best],
        "verdicts": [r["verdict"] for r in results],
    }}


def _run_seed(runner, place: str, seed: int, sky130: bool, maxiter: int):
    """One sweep point in a worker process: (result, StageStats for the parent).

    Top-level so ProcessPoolExecutor can pickle it by reference.
    """
    with Profiler() as prof:
        res = (runner or run_end_to_end)(place=place, seed=seed, sky130=sky130,
                                         maxiter=maxiter)
    return res, list(prof.stats.values())


def _picklable(obj) -> bool:
    try:
        pickle.dumps(obj)
        return True
    except Exception:                          # noqa: BLE001 - lambdas/closures/locals
        return False


def _sweep_parallel(runner, place, seeds, sky130, maxiter, workers):
    """Seeds across processes, results in seed order; None if no pool is possible."""
    unavailable = (OSError, AssertionError, NotImplementedError, RuntimeError,
                   BrokenProcessPool)          # no processes here (sandbox, daemon, ...)
    try:
        # spawn (not fork): safe when the caller is a threaded server, same on all OSes.
        ex = ProcessPoolExecutor(max_workers=workers,
                                 mp_context=multiprocessing.get_context("spawn"))
    except unavailable as e:
        _log.warning("(ALO-011) parallel sweep unavailable (%s) — running seeds serially", e)
        return None
    try:
        try:
            futs = [ex.submit(_run_seed, runner, place, s, sky130, maxiter) for s in seeds]
        except unavailable as e:
            _log.warning("(ALO-011) parallel sweep unavailable (%s) — running seeds serially", e)
            return None
        try:
            outs = [f.result() for f in futs]  # a seed's own exception propagates as-is
        except BrokenProcessPool as e:
            _log.warning("(ALO-012) worker pool died (%s) — re-running seeds serially", e)
            return None
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
    for _, stats in outs:
        merge_stats(stats)
    return [res for res, _ in outs]


def run_best_of(place: str = "sa", seeds=(0, 1, 2, 3), sky130: bool = False,
                maxiter: int = 90, runner=None, workers: int | None = None) -> dict:
    """Run the full flow across several seeds and return the best by sign-off.

    Seeds are independent, so they run in parallel processes (pure-Python
    CPU-bound work: threads would serialize on the GIL). ``workers`` defaults
    to min(len(seeds), cpu_count); ``workers=1`` runs serially in-process,
    which is also the fallback when no process pool can be started. Results,
    their order and the winner (incl. ties: first seed in list order) are
    identical to the serial run.

    `runner(place, seed, sky130, maxiter)` is injectable for tests; one that
    cannot be pickled (lambda/closure) runs serially.
    """
    seeds = list(seeds)
    if workers is None:
        workers = min(len(seeds), os.cpu_count() or 1)
    results = None
    if workers > 1 and len(seeds) > 1 and _picklable(runner):
        results = _sweep_parallel(runner, place, seeds, sky130, maxiter,
                                  min(workers, len(seeds)))
    if results is None:
        run = runner or run_end_to_end
        results = [run(place=place, seed=s, sky130=sky130, maxiter=maxiter)
                   for s in seeds]
    return select_best(seeds, results)


def run_end_to_end(place: str = "sa", seed: int = 0, sky130: bool = False,
                   maxiter: int = 90) -> dict:
    stages = []

    # 1. Sizing — minimize power s.t. gain/GBW/PM/slew specs (DE in log space),
    # with a parasitic guard-band so post-layout PM/GBW still meet nominal.
    with stage("sizing"):
        d = de_log_refine(seed=seed, maxiter=maxiter, guardband=True)
        s = evaluate_opamp(d.params)
    stages.append(_stage(
        "Sizing (DE)", "pass" if d.feasible else "fail",
        f"gain {s.gain_db:.1f} dB · GBW {s.gbw_hz/1e6:.1f} MHz · PM {s.pm_deg:.0f}° · "
        f"{s.power*1e3:.3f} mW" + ("" if d.feasible else " · specs not met")))

    # 2-6. schematic → placement → routing → sign-off → post-layout (sized).
    # analog_aware: matched-pair symmetry + short high-impedance (n1/n2) nets,
    # and PM-critical nets (n2/VOUT) are routed first.
    flow = run_flow(place=place, seed=seed, sizing=d.params, analog_aware=True)
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
                with stage("silicon"):
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
