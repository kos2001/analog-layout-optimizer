"""FastAPI backend exposing the (Virtuoso-free) layout optimization engine.

It reuses the exact same ``layout_opt`` package the offline PoC and tests use -
no logic is duplicated for the web. Endpoints:

  GET  /api/config    defaults, search bounds, PDK rules, fixed config
  POST /api/evaluate  params -> layout rects + area + DRC violations (live sliders)
  POST /api/optimize  run optimization -> per-generation frames + final best

Execution model (see layout_opt/jobs.py): heavy endpoints (optimizers, full
flow, simulators) are ``async`` and run their engine call in a shared worker
*process* pool, so a long run never blocks the event loop or starves the live
slider endpoints of the GIL. Results are cached by provenance key (request +
engine source hash [+ external tool fingerprint]); concurrent identical
requests share one in-flight computation. Response shapes are unchanged.

  POST   /api/jobs              {"kind", "params"} -> 202 {"job_id", "status", ...}
  GET    /api/jobs/{id}         status, timings, stage progress, result when done
  GET    /api/jobs/{id}/events  Server-Sent Events: status + stage progress
  DELETE /api/jobs/{id}         cancel a queued job (409 once running/finished)
  GET    /api/health            liveness + executor/cache/job stats
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, get_type_hints

# Make the layout_opt package importable (repo root is two levels up).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from layout_opt.evaluate import EvalResult, evaluate
from layout_opt.generator import (
    DEFAULT_BOUNDS,
    DesignParams,
    DiffPairConfig,
    PDKRules,
    generate_layout,
)
import numpy as np

from layout_opt.optimize import optimize_trajectory
from layout_opt.joint import optimize_joint_trajectory
from layout_opt.comparator import build_comparator
from layout_opt.maze import route_all, optimize_net_order
from layout_opt.interactive import (
    GRID_W, GRID_H, default_floorplan, route_components, components_from_payload,
)
from layout_opt import scenarios as _scn
from layout_opt import common_centroid as _cc
from layout_opt import ppa as _ppa
from layout_opt import placement as _flow
from layout_opt.tcoil import (
    TCoilParams,
    bandwidth,
    bw_extension,
    optimize_tcoil,
    peaking_db,
    transimpedance,
)
from layout_opt.opamp import OpAmpParams, evaluate_opamp
from layout_opt.opamp_opt import (
    GAIN_MIN, GBW_MIN, PM_MIN, SLEW_MIN, STRATEGIES, de_log_refine,
)
from layout_opt.spectre_backend import (
    SpectreUnavailable, preflight as spectre_preflight, spectre_evaluate,
)
from layout_opt.pdk import GENERIC_PDK
from layout_opt.routing import (
    RoutingParams,
    RoutingRules,
    connectivity_ok,
    route,
    routed_layout,
    routing_violations,
)
from layout_opt.flow_e2e import select_best
from layout_opt.jobs import (
    TERMINAL, ComputeService, JobRegistry, Plan, QueueFull, await_shared,
)
from layout_opt.provenance import cache_key, code_version, digest, file_digest, tool_fingerprint

# Engine sources + this file (payload shaping lives here) -> cache-key version.
CODE_VERSION = digest([code_version(), file_digest(__file__)])[:16]

SERVICE = ComputeService(warm_module=__name__)
JOBS = JobRegistry(SERVICE)


def configure_service(**kw) -> None:
    """(Re)build the compute service + job registry, e.g. ``mode="thread"`` in tests."""
    global SERVICE, JOBS
    SERVICE.shutdown()
    registry_kw = {k: kw.pop(k) for k in ("max_running", "max_jobs", "max_queued") if k in kw}
    SERVICE = ComputeService(warm_module=__name__, **kw)
    JOBS = JobRegistry(SERVICE, **registry_kw)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    if os.environ.get("ALO_PREWARM", "1") != "0":
        SERVICE.warm()                       # spawn + import in the background
    yield
    SERVICE.shutdown()


app = FastAPI(title="Analog Layout Optimizer", version="1.0", lifespan=_lifespan)

# Vite dev server runs on a different port; allow it during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CFG = DiffPairConfig()
RULES = PDKRules()
RRULES = RoutingRules()


# --------------------------------------------------------------------------
# Job kinds: named, picklable engine calls (shared by endpoints and /api/jobs)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class _Kind:
    fn: Callable              # top-level -> pickles by reference into workers
    model: type[BaseModel]    # validates/coerces params, applies defaults
    env: bool                 # result depends on external tools/PDK


KINDS: dict[str, _Kind] = {}


def _kind(name: str, model: type[BaseModel] | None = None, env: bool = False):
    def deco(fn):
        if model is None:
            hints = get_type_hints(fn)
            fields = {p.name: (hints.get(p.name, Any),
                               ... if p.default is inspect.Parameter.empty else p.default)
                      for p in inspect.signature(fn).parameters.values()}
            m = create_model(f"{fn.__name__}Params",
                             __config__=ConfigDict(extra="forbid"), **fields)
        else:   # endpoint body model, but strict about unknown keys for jobs
            m = type(f"{model.__name__}Job", (model,),
                     {"model_config": ConfigDict(extra="forbid"), "__module__": __name__})
        KINDS[name] = _Kind(fn, m, env)
        return fn
    return deco


def _cacheable(result) -> bool:
    """Never cache a transient answer (tool/PDK not reachable right now)."""
    if not isinstance(result, dict):
        return True
    return "error" not in result and "unavailable" not in str(result.get("status", ""))


def _plan(kind: str, params: dict) -> Plan:
    """Validated params -> provenance key + cache-aware submission."""
    spec = KINDS[kind]
    if kind == "full-flow":
        params = {**params, "sweep": max(0, min(params["sweep"], 16))}
    key = cache_key(kind, params, version=CODE_VERSION,
                    env=tool_fingerprint() if spec.env else None)
    if kind == "full-flow" and params["sweep"] > 0:
        # Fan the sweep out as independent (individually cached) seeds across
        # the shared pool, then rank in-process: no nested pools.
        seeds = list(range(params["seed"], params["seed"] + params["sweep"]))
        subs = [_plan(kind, {**params, "seed": s, "sweep": 0}) for s in seeds]
        return Plan(kind, params, key,
                    lambda: SERVICE.submit_composite(
                        key, [p.start for p in subs],
                        lambda results: select_best(seeds, results), _cacheable),
                    [(p.key, {"seed": s}) for p, s in zip(subs, seeds)])
    return Plan(kind, params, key,
                lambda: SERVICE.submit(key, spec.fn, params, _cacheable), [(key, {})])


def _validate(kind: str, raw: dict) -> dict:
    return KINDS[kind].model(**raw).model_dump()


async def _offload(kind: str, **params) -> dict:
    """Run a heavy kind off the event loop (worker pool), cached + shared."""
    fut, _how = _plan(kind, _validate(kind, params)).start()
    return await await_shared(fut)


# --------------------------------------------------------------------------
# Wire models
# --------------------------------------------------------------------------
class ParamsIn(BaseModel):
    w_finger: float
    l: float
    finger_pitch: float
    guard_gap: float
    gr_width: float

    def to_design(self) -> DesignParams:
        return DesignParams(
            w_finger=self.w_finger,
            l=self.l,
            finger_pitch=self.finger_pitch,
            guard_gap=self.guard_gap,
            gr_width=self.gr_width,
        )


class OptimizeIn(BaseModel):
    seed: int = 0
    maxiter: int = Field(default=60, ge=5, le=300)


def _params_dict(p: DesignParams) -> dict:
    return {k: getattr(p, k) for k in DesignParams.ORDER}


def _layout_payload(p: DesignParams) -> dict:
    """Serialize the generated layout: rects + which params violate which rule.

    Each rect carries a ``violatesRule`` list so the frontend can highlight the
    exact shapes implicated by a DRC/spec violation.
    """
    lay = generate_layout(p, CFG)
    res: EvalResult = evaluate(p, CFG, RULES)

    # Map a violated rule-name to the layers it visually concerns.
    rule_layers = {
        "L": {CFG.layer_poly},
        "poly_pitch": {CFG.layer_poly},
        "W_finger": {CFG.layer_diff, CFG.layer_poly},
        "W_total(spec)": {CFG.layer_diff},
        "guard_gap": {CFG.layer_gr},
        "gr_width": {CFG.layer_gr},
    }
    violated_layers: set[str] = set()
    for v in res.violations:
        name = v.split(":")[0]
        violated_layers |= rule_layers.get(name, set())

    x0, y0, x1, y1 = lay.bbox()
    rects = [
        {
            "layer": r.layer,
            "purpose": r.purpose,
            "x0": r.x0,
            "y0": r.y0,
            "x1": r.x1,
            "y1": r.y1,
            "violated": r.layer in violated_layers,
        }
        for r in lay.rects
    ]
    return {
        "name": lay.name,
        "rects": rects,
        "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        "area": res.area,
        "objective": res.objective,
        "penalty": res.penalty,
        "isClean": res.is_clean,
        "violations": res.violations,
    }


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/api/config")
def get_config() -> dict:
    return {
        "order": list(DesignParams.ORDER),
        "bounds": DEFAULT_BOUNDS,
        "rules": {
            "min_l": RULES.min_l,
            "min_w": RULES.min_w,
            "min_poly_pitch": RULES.min_poly_pitch,
            "min_gr_gap": RULES.min_gr_gap,
            "min_gr_width": RULES.min_gr_width,
        },
        "config": {
            "nf": CFG.nf,
            "w_min_total": CFG.w_min_total,
            "layer_poly": CFG.layer_poly,
            "layer_diff": CFG.layer_diff,
            "layer_gr": CFG.layer_gr,
        },
        # A sensible, DRC-clean starting point for the sliders.
        "defaults": {
            "w_finger": CFG.w_min_total / CFG.nf,
            "l": 0.06,
            "finger_pitch": 0.30,
            "guard_gap": 0.40,
            "gr_width": 0.10,
        },
    }


@app.post("/api/evaluate")
def post_evaluate(params: ParamsIn) -> dict:
    return _layout_payload(params.to_design())


def _routed_payload(p: DesignParams, rp: RoutingParams) -> dict:
    """Serialize the FULL routed cell (device + rails/stubs/vias) for the UI."""
    lay = routed_layout(p, rp, CFG, RRULES)
    routed = route(p, rp, CFG, RRULES)
    dev_res = evaluate(p, CFG, RULES)
    route_viols = routing_violations(rp, RRULES)

    # Which layers a violation visually concerns.
    dev_rule_layers = {
        "L": {CFG.layer_poly}, "poly_pitch": {CFG.layer_poly},
        "W_finger": {CFG.layer_diff}, "W_total(spec)": {CFG.layer_diff},
        "guard_gap": {CFG.layer_gr}, "gr_width": {CFG.layer_gr},
    }
    violated_layers: set[str] = set()
    for v in dev_res.violations:
        violated_layers |= dev_rule_layers.get(v.split(":")[0], set())
    if route_viols:
        violated_layers |= {"M2", "VIA12"}

    x0, y0, x1, y1 = lay.bbox()
    rects = [
        {"layer": r.layer, "purpose": r.purpose, "x0": r.x0, "y0": r.y0,
         "x1": r.x1, "y1": r.y1, "violated": r.layer in violated_layers}
        for r in lay.rects
    ]
    all_viols = list(dev_res.violations) + route_viols
    return {
        "name": lay.name,
        "rects": rects,
        "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        "area": lay.bbox_area(),               # TOTAL routed-cell area
        "deviceArea": dev_res.area,
        "wirelength": routed.wirelength,
        "viaCount": routed.via_count,
        "connected": connectivity_ok(routed, CFG),
        "isClean": (not all_viols) and connectivity_ok(routed, CFG),
        "violations": all_viols,
        "objective": dev_res.area,
    }


@_kind("joint", model=OptimizeIn)
def _compute_joint(seed: int = 0, maxiter: int = 60) -> dict:
    res, frames = optimize_joint_trajectory(
        cfg=CFG, rules=RULES, rrules=RRULES, seed=seed, maxiter=maxiter
    )
    frame_payloads = []
    for i, (p, rp) in enumerate(frames):
        pl = _routed_payload(p, rp)
        frame_payloads.append(
            {
                "iter": i,
                "params": {**_params_dict(p),
                           "rail_width": rp.rail_width,
                           "rail_pitch": rp.rail_pitch,
                           "via_size": rp.via_size},
                "area": pl["area"],
                "objective": pl["objective"],
                "isClean": pl["isClean"],
                "violations": pl["violations"],
                "layout": pl,
            }
        )
    best_pl = _routed_payload(res.device, res.routing)
    return {
        "nEvals": res.n_evals,
        "best": {
            "params": {**_params_dict(res.device),
                       "rail_width": res.routing.rail_width,
                       "rail_pitch": res.routing.rail_pitch,
                       "via_size": res.routing.via_size},
            "area": res.total_area,
            "deviceArea": res.device_area,
            "wirelength": res.wirelength,
            "isClean": res.is_clean,
            "violations": res.device_violations + res.routing_violations,
            "layout": best_pl,
        },
        "frames": frame_payloads,
    }


@app.post("/api/joint")
async def post_joint(body: OptimizeIn) -> dict:
    return await _offload("joint", **body.model_dump())


@_kind("optimize", model=OptimizeIn)
def _compute_optimize(seed: int = 0, maxiter: int = 60) -> dict:
    opt, frames = optimize_trajectory(
        cfg=CFG, rules=RULES, seed=seed, maxiter=maxiter
    )
    frame_payloads = []
    for i, fp in enumerate(frames):
        pl = _layout_payload(fp)
        frame_payloads.append(
            {
                "iter": i,
                "params": _params_dict(fp),
                "area": pl["area"],
                "objective": pl["objective"],
                "isClean": pl["isClean"],
                "violations": pl["violations"],
                "layout": pl,
            }
        )
    return {
        "nEvals": opt.n_evals,
        "best": {
            "params": _params_dict(opt.params),
            "area": opt.result.area,
            "isClean": opt.result.is_clean,
            "violations": opt.result.violations,
            "layout": _layout_payload(opt.params),
        },
        "frames": frame_payloads,
    }


@app.post("/api/optimize")
async def post_optimize(body: OptimizeIn) -> dict:
    return await _offload("optimize", **body.model_dump())


# --------------------------------------------------------------------------
# Comparator maze routing
# --------------------------------------------------------------------------
def _maze_solution_payload(grid, nets, sol) -> dict:
    return {
        "order": sol.order,
        "totalWirelength": sol.total_wirelength,
        "totalBends": sol.total_bends,
        "failed": sol.failed,
        "nets": {
            net: {
                "pins": nets[net],
                "cells": sorted(nr.cells),
                "wirelength": nr.wirelength,
                "bends": nr.bends,
                "routed": nr.routed,
            }
            for net, nr in sol.routes.items()
        },
    }


@_kind("maze")
def _compute_maze() -> dict:
    grid, nets = build_comparator()
    naive = route_all(grid, nets, list(nets.keys()))
    best = optimize_net_order(grid, nets)
    # Worst feasible ordering, for contrast.
    from itertools import permutations
    worst = max(
        (route_all(grid, nets, list(o)) for o in permutations(nets.keys())),
        key=lambda s: (len(s.failed), s.total_wirelength),
    )
    return {
        "width": grid.width,
        "height": grid.height,
        "blocked": sorted(grid.blocked),
        "netNames": list(nets.keys()),
        "naive": _maze_solution_payload(grid, nets, naive),
        "optimized": _maze_solution_payload(grid, nets, best),
        "worstWirelength": worst.total_wirelength,
    }


@app.get("/api/maze")
async def get_maze() -> dict:
    return await _offload("maze")


# --------------------------------------------------------------------------
# Interactive floorplan: drag components -> dynamic maze routing
# --------------------------------------------------------------------------
@_kind("floorplan/scenario")
def _compute_floorplan_scenario() -> dict:
    return route_components(GRID_W, GRID_H, default_floorplan(), optimize=True)


@app.get("/api/floorplan/scenario")
def get_floorplan_scenario() -> dict:
    """Default comparator placement + its initial routing."""
    return _compute_floorplan_scenario()


class FloorplanIn(BaseModel):
    width: int = GRID_W
    height: int = GRID_H
    components: list[dict]
    optimize: bool = False


@app.post("/api/floorplan/route")
def post_floorplan_route(body: FloorplanIn) -> dict:
    """Re-route an arbitrary placement (called on every drag)."""
    comps = components_from_payload(body.components)
    return route_components(body.width, body.height, comps, optimize=body.optimize)


# --------------------------------------------------------------------------
# Complex real-work cases: routing scenarios + common-centroid layout
# --------------------------------------------------------------------------
@app.get("/api/scenarios")
def list_scenarios() -> dict:
    return {"cases": _scn.CASES}


@_kind("scenario")
def _compute_scenario(key: str) -> dict:
    if key not in {c["key"] for c in _scn.CASES}:
        return {"error": f"unknown scenario {key}"}
    return _scn.run_case(key)


@app.get("/api/scenarios/{key}")
def get_scenario(key: str) -> dict:
    return _compute_scenario(key)


@_kind("common-centroid")
def _compute_common_centroid(rows: int = 4, cols: int = 4) -> dict:
    rows = max(2, min(rows, 8)); cols = max(2, min(cols, 8))
    return _cc.compare(rows, cols)


@app.get("/api/common-centroid")
def get_common_centroid(rows: int = 4, cols: int = 4) -> dict:
    return _compute_common_centroid(rows, cols)


@_kind("ppa")
def _compute_ppa(w_power: float = 1.0, w_area: float = 1.0, w_perf: float = 1.0,
                 pop: int = 80, gens: int = 40, seed: int = 0) -> dict:
    pop = max(20, min(pop, 160)); gens = max(5, min(gens, 80))
    return _ppa.run_ppa(pop_size=pop, generations=gens, seed=seed,
                        weights=(w_power, w_area, w_perf))


@app.get("/api/ppa")
async def get_ppa(w_power: float = 1.0, w_area: float = 1.0, w_perf: float = 1.0,
                  pop: int = 80, gens: int = 40, seed: int = 0) -> dict:
    """OTA PPA Pareto front (NSGA-II) + the design matching a P/P/A preference."""
    return await _offload("ppa", w_power=w_power, w_area=w_area, w_perf=w_perf,
                          pop=pop, gens=gens, seed=seed)


@_kind("flow")
def _compute_flow(place: str = "sa", seed: int = 0, analog: bool = False) -> dict:
    place = place if place in ("sa", "random") else "sa"
    return _flow.run_flow(place=place, seed=seed, analog_aware=analog)


@app.get("/api/flow")
def get_flow(place: str = "sa", seed: int = 0, analog: bool = False) -> dict:
    """Schematic -> placement -> routing, connected by one netlist."""
    return _compute_flow(place, seed, analog)


@_kind("full-flow", env=True)
def _compute_full_flow(place: str = "sa", seed: int = 0, sky130: bool = False,
                       sweep: int = 0) -> dict:
    from layout_opt.flow_e2e import run_best_of, run_end_to_end
    place = place if place in ("sa", "random") else "sa"
    if sweep > 0:   # direct calls only; the service fans sweeps out via _plan
        seeds = range(seed, seed + min(sweep, 16))
        return run_best_of(place=place, seeds=seeds, sky130=sky130, workers=1)
    return run_end_to_end(place=place, seed=seed, sky130=sky130)


@app.get("/api/full-flow")
async def get_full_flow(place: str = "sa", seed: int = 0, sky130: bool = False,
                        sweep: int = 0) -> dict:
    """One-click end-to-end: sizing -> P&R -> sign-off -> post-layout -> [silicon].

    sweep>0 runs `sweep` seeds (seed..seed+sweep-1) and returns the best run
    by sign-off ranking instead of gambling on a single seed. Seeds run in
    parallel worker processes and are cached individually.
    """
    return await _offload("full-flow", place=place, seed=seed, sky130=sky130, sweep=sweep)


@_kind("layout/shapes")
def _compute_layout_shapes(which: str = "ota") -> dict:
    from layout_opt.layout_view import layout_shapes
    return layout_shapes(which if which in ("ota", "mirror", "diffpair") else "ota")


@app.get("/api/layout/shapes")
def get_layout_shapes(which: str = "ota") -> dict:
    """Per-SKY130-layer polygons of a transistor layout, for the in-browser viewer."""
    return _compute_layout_shapes(which)


@app.get("/api/flow/gds")
def get_flow_gds(place: str = "sa", seed: int = 0) -> dict:
    """Export the placed+routed OTA to GDSII (base64) + layer stats."""
    return _compute_flow_gds(place, seed)


@_kind("flow/gds")
def _compute_flow_gds(place: str = "sa", seed: int = 0) -> dict:
    import base64
    from layout_opt.gds import flow_to_gds_bytes
    place = place if place in ("sa", "random") else "sa"
    f = _flow.run_flow(place=place, seed=seed)
    data, stats = flow_to_gds_bytes(f)
    return {"filename": f"ota_{place}_{seed}.gds",
            "gdsBase64": base64.b64encode(data).decode("ascii"),
            "bytes": len(data), "stats": stats}


@app.get("/api/lvs")
def get_lvs(cell: str = "ota") -> dict:
    """Transistor-level layout synthesis + real KLayout LVS (OTA / mirror / diff pair)."""
    return _compute_lvs(cell)


@_kind("lvs", env=True)
def _compute_lvs(cell: str = "ota") -> dict:
    from layout_opt.klayout_lvs import lvs_current_mirror, lvs_ota, lvs_diffpair
    if cell == "mirror":
        return lvs_current_mirror()
    if cell == "diffpair":
        return lvs_diffpair()
    return lvs_ota()


@_kind("antenna")
def _compute_antenna() -> dict:
    from layout_opt.antenna import antenna_ota
    return antenna_ota()


@app.get("/api/antenna")
def get_antenna() -> dict:
    """Per-net antenna ratio (metal/gate area) on the transistor-level OTA layout."""
    return _compute_antenna()


@_kind("em")
def _compute_em() -> dict:
    from layout_opt.em import em_check
    return em_check()


@app.get("/api/em")
def get_em() -> dict:
    """EM DC current-density check on the OTA (currents from sizing, widths from layout)."""
    return _compute_em()


@app.get("/api/lde")
def get_lde() -> dict:
    """Input-pair STI/LOD mismatch vs dummy count (common-centroid array)."""
    return _compute_lde()


@_kind("lde")
def _compute_lde() -> dict:
    from layout_opt.lde import diffpair_lde
    from layout_opt.device_layout import device_extent
    pitch = device_extent(1.0, 0.15)[0] + 0.9
    return diffpair_lde(["A", "B", "B", "A"], pitch, dummy_options=(0, 1, 2, 3))


@app.get("/api/flow/drc-klayout")
def get_flow_drc_klayout(place: str = "sa", seed: int = 0) -> dict:
    """Real DRC on the exported GDS with the KLayout engine (met1/met2 width+space)."""
    return _compute_flow_drc_klayout(place, seed)


@_kind("flow/drc-klayout", env=True)
def _compute_flow_drc_klayout(place: str = "sa", seed: int = 0) -> dict:
    from layout_opt.klayout_drc import run_drc_on_flow
    place = place if place in ("sa", "random") else "sa"
    return run_drc_on_flow(_flow.run_flow(place=place, seed=seed))


@app.get("/api/pvt")
async def get_pvt(seed: int = 0, full: bool = False) -> dict:
    """PVT corner sweep on real SKY130 silicon (slow: ~15-18 s per corner)."""
    return await _offload("pvt", seed=seed, full=full)


@_kind("pvt", env=True)
def _compute_pvt(seed: int = 0, full: bool = False) -> dict:
    from layout_opt.pvt import run_pvt, full_grid
    from layout_opt.opamp_opt import de_log_refine
    p = de_log_refine(seed=seed).params
    return run_pvt(p, corners=full_grid()) if full else run_pvt(p)


# --------------------------------------------------------------------------
# T-coil frequency response
# --------------------------------------------------------------------------
_TCOIL_W = np.logspace(-1.0, 1.3, 200)  # rad/s


def _tcoil_curve(p: TCoilParams) -> dict:
    mag = np.abs(transimpedance(p, _TCOIL_W))
    return {
        "magDb": [float(20.0 * np.log10(m + 1e-12)) for m in mag],
        "bw": bandwidth(p),
        "bwExtension": bw_extension(p),
        "peakingDb": peaking_db(p),
        "params": {"L": p.L, "k": p.k, "Cb": p.Cb},
    }


class TCoilIn(BaseModel):
    L: float
    k: float
    Cb: float


@app.get("/api/tcoil")
async def get_tcoil() -> dict:
    return await _offload("tcoil")


@_kind("tcoil")
def _compute_tcoil() -> dict:
    none = TCoilParams(0.0, 0.0, 0.0)
    shunt = TCoilParams(0.5, 0.0, 0.0)
    flat = optimize_tcoil(peak_limit_db=0.1, seed=0).params
    return {
        "freq": [float(w) for w in _TCOIL_W],
        "curves": {
            "none": _tcoil_curve(none),
            "shunt": _tcoil_curve(shunt),
            "tcoil": _tcoil_curve(flat),
        },
        "thresholdDb": float(20.0 * np.log10(1.0 / np.sqrt(2.0))),  # -3 dB
    }


@app.post("/api/tcoil/eval")
def post_tcoil_eval(body: TCoilIn) -> dict:
    return _tcoil_curve(TCoilParams(body.L, body.k, body.Cb))


# --------------------------------------------------------------------------
# Op-amp (two-stage OTA) sizing + optimizer study + Spectre backend
# --------------------------------------------------------------------------
def _opamp_design_payload(seed: int = 0) -> dict:
    d = de_log_refine(seed=seed)
    s = d.specs
    specs = [
        {"name": "Gain", "value": round(s.gain_db, 2), "unit": "dB",
         "target": GAIN_MIN, "pass": s.gain_db >= GAIN_MIN - 1e-6},
        {"name": "GBW", "value": round(s.gbw_hz / 1e6, 2), "unit": "MHz",
         "target": GBW_MIN / 1e6, "pass": s.gbw_hz >= GBW_MIN - 1.0},
        {"name": "Phase margin", "value": round(s.pm_deg, 2), "unit": "deg",
         "target": PM_MIN, "pass": s.pm_deg >= PM_MIN - 1e-6},
        {"name": "Slew", "value": round(s.slew / 1e6, 2), "unit": "V/us",
         "target": SLEW_MIN / 1e6, "pass": s.slew >= SLEW_MIN - 1.0},
    ]
    return {
        "feasible": d.feasible,
        "power_mw": round(d.power_mw, 4),
        "specs": specs,
        "sizing": {
            "wl1": round(d.params.wl1, 2), "wl3": round(d.params.wl3, 2),
            "wl5": round(d.params.wl5, 2), "wl6": round(d.params.wl6, 2),
            "wl7": round(d.params.wl7, 2),
            "itail_uA": round(d.params.itail * 1e6, 3),
            "i6_uA": round(d.params.i6 * 1e6, 3),
            "cc_pF": round(d.params.cc * 1e12, 4),
        },
        "overdrives": {f"vov{i}": round(getattr(s, f"vov{i}"), 4)
                       for i in (1, 3, 5, 6, 7)},
    }


@_kind("opamp")
def _compute_opamp() -> dict:
    return _opamp_design_payload(0)


@app.get("/api/opamp")
def get_opamp() -> dict:
    return _compute_opamp()


@app.get("/api/opamp/study")
async def get_opamp_study(seeds: int = 4) -> dict:
    return await _offload("opamp/study", seeds=seeds)


@_kind("opamp/study")
def _compute_opamp_study(seeds: int = 4) -> dict:
    import numpy as np
    out = []
    for name, fn in STRATEGIES.items():
        powers = []
        for s in range(seeds):
            d = fn(seed=s)
            if d.feasible:
                powers.append(d.power_mw)
        arr = np.array(powers) if powers else np.array([float("nan")])
        out.append({
            "strategy": name, "feasible": len(powers), "n": seeds,
            "best_mw": round(float(np.nanmin(arr)), 4),
            "mean_mw": round(float(np.nanmean(arr)), 4),
            "std_mw": round(float(np.nanstd(arr)) if len(arr) > 1 else 0.0, 4),
        })
    return {"results": out,
            "note": "log-space DE: lower power + tighter variance than linear."}


@app.get("/api/opamp/preflight")
def get_opamp_preflight() -> dict:
    return spectre_preflight()


@app.get("/api/opamp/spectre-eval")
async def get_opamp_spectre_eval(seed: int = 0) -> dict:
    return await _offload("opamp/spectre-eval", seed=seed)


@_kind("opamp/spectre-eval", env=True)
def _compute_opamp_spectre_eval(seed: int = 0) -> dict:
    cand = de_log_refine(seed=seed).params
    a = evaluate_opamp(cand)
    out = {
        "pdk": GENERIC_PDK.name,
        "analytic": {"gain_db": round(a.gain_db, 2), "gbw_mhz": round(a.gbw_hz / 1e6, 2),
                     "pm_deg": round(a.pm_deg, 2), "power_mw": round(a.power * 1e3, 4)},
    }
    try:
        s = spectre_evaluate(cand, GENERIC_PDK)
        out["spectre"] = {"gain_db": round(s.gain_db, 2), "gbw_mhz": round(s.gbw_hz / 1e6, 2),
                          "pm_deg": round(s.pm_deg, 2), "power_mw": round(s.power * 1e3, 4)}
        out["status"] = "ran_real_spectre"
    except SpectreUnavailable as e:
        out["status"] = "spectre_unavailable"
        out["error"] = str(e)
        out["preflight"] = spectre_preflight()
    return out


# --------------------------------------------------------------------------
# Process change: natural language -> re-optimized placement+routing (before/after)
# --------------------------------------------------------------------------
class AdaptIn(BaseModel):
    nl: str = ""
    overrides: dict = {}


def _routed_layout_payload(device, routing, cfg, rrules) -> dict:
    lay = routed_layout(device, routing, cfg, rrules)
    x0, y0, x1, y1 = lay.bbox()
    return {
        "name": lay.name,
        "rects": [{"layer": r.layer, "purpose": r.purpose, "x0": r.x0, "y0": r.y0,
                   "x1": r.x1, "y1": r.y1, "violated": False} for r in lay.rects],
        "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        "area": lay.bbox_area(),
        "objective": lay.bbox_area(),
        "isClean": True,
        "violations": [],
    }


@app.post("/api/adapt")
async def post_adapt(body: AdaptIn) -> dict:
    return await _offload("adapt", **body.model_dump())


@_kind("adapt", model=AdaptIn)
def _compute_adapt(nl: str = "", overrides: dict | None = None) -> dict:
    from layout_opt.process_change import (
        ProcessOverrides, apply_overrides, parse_process_nl,
    )
    from layout_opt.joint import optimize_joint

    ov = ProcessOverrides(overrides) if overrides else parse_process_nl(nl)
    base = (DiffPairConfig(), PDKRules(), RoutingRules())
    new = apply_overrides(ov)

    def run(cfg, rules, rrules) -> dict:
        j = optimize_joint(cfg=cfg, rules=rules, rrules=rrules, seed=0, maxiter=150)
        pl = _routed_layout_payload(j.device, j.routing, cfg, rrules)
        return {
            "layout": pl,
            "totalArea": round(j.total_area, 4),
            "deviceArea": round(j.device_area, 4),
            "wirelength": round(j.wirelength, 3),
            "drcClean": j.is_clean,
            "device": {k: round(v, 4) for k, v in zip(j.device.ORDER, j.device.to_vector())},
            "routing": {k: round(v, 4) for k, v in zip(j.routing.ORDER, j.routing.to_vector())},
        }

    before = run(*base)
    after = run(*new)
    b = before["totalArea"]
    return {
        "overrides": ov.values,
        "before": before,
        "after": after,
        "areaDeltaPct": round(100.0 * (after["totalArea"] - b) / b, 1) if b else 0.0,
        "topology": {"fingers": 2 * new[0].nf,
                     "nets": ["VINP", "VINN", "VOUTN", "VOUTP", "VTAIL"]},
    }


# --------------------------------------------------------------------------
# Surrogate-assisted optimization (active learning) visualization
# --------------------------------------------------------------------------
@app.get("/api/surrogate")
async def get_surrogate(target: float = 3.5) -> dict:
    return await _offload("surrogate", target=target)


@_kind("surrogate")
def _compute_surrogate(target: float = 3.5) -> dict:
    from layout_opt.surrogate_opt import surrogate_assisted_optimize
    r = surrogate_assisted_optimize(fom_target=target, n_init=10, n_holdout=8,
                                    rounds=6, seed=0, de_maxiter=30)
    return {
        "target": target,
        "rounds": [{
            "index": rd.index,
            "fomPred": round(rd.fom_pred, 4),
            "fomTruth": round(rd.fom_truth, 4),
            "predError": round(rd.pred_error, 4),
            "holdoutRmse": round(rd.holdout_rmse, 4),
            "holdoutR2": round(rd.holdout_r2, 4),
            "meets": rd.meets_target,
            "expensiveCalls": rd.expensive_calls,
        } for rd in r.rounds],
        "best": {"area": round(r.best_area, 4), "fomTruth": round(r.best_fom_truth, 4)},
        "expensiveCalls": r.expensive_calls,
        "surrogateCalls": r.surrogate_calls,
        "savings": round(r.surrogate_calls / max(r.expensive_calls, 1), 0),
    }


# --------------------------------------------------------------------------
# SKILL viewer — the actual virtuoso-bridge output for the optimized cell
# --------------------------------------------------------------------------
@app.get("/api/skill")
async def get_skill() -> dict:
    return await _offload("skill")


@_kind("skill")
def _compute_skill() -> dict:
    from layout_opt.skill import emit_skill
    from layout_opt.joint import optimize_joint
    j = optimize_joint(cfg=CFG, rules=RULES, rrules=RRULES, seed=0, maxiter=120)
    lay = routed_layout(j.device, j.routing, CFG, RRULES)
    cmds = emit_skill(lay)
    return {
        "cell": lay.name,
        "shapeCount": len(lay.rects),
        "commands": cmds,
        "il": "\n".join(cmds),
        "note": "Generated by virtuoso_bridge layout.ops builders. Execute via "
                "client.layout.edit() once a Virtuoso server is connected.",
    }


# --------------------------------------------------------------------------
# virtuoso_bridge feature checks (verified WITHOUT Virtuoso)
# --------------------------------------------------------------------------
@app.get("/api/bridge")
def get_bridge() -> dict:
    import json as _json
    import socket as _socket
    import threading as _threading
    from virtuoso_bridge import ExecutionStatus, VirtuosoClient
    from virtuoso_bridge.spectre.parsers import parse_spectre_psf_ascii
    from virtuoso_bridge.virtuoso.layout.ops import layout_create_rect, layout_create_path
    from virtuoso_bridge.virtuoso.schematic.ops import schematic_create_inst

    checks = []
    # 1. layout builders
    rect = layout_create_rect("M1", "drawing", 0, 0, 1, 0.5)
    checks.append({"name": "Layout SKILL builders", "ok": rect.startswith("dbCreateRect("),
                   "sample": rect})
    # 2. schematic builders
    inst = schematic_create_inst('dbOpenCellViewByType("a" "b" "symbol")', "M0", 0, 0, "R0")
    checks.append({"name": "Schematic SKILL builders", "ok": "dbCreateInst(" in inst,
                   "sample": inst[:70]})
    # 3. PSF parser
    import tempfile as _tf
    psf = ('HEADER\nPROPERTIES\nSWEEP\n"freq" 1\nTRACE\n"vout" "V"\nVALUE\n'
           '"freq" 1e3\n"vout" 100.0\n"freq" 1e6\n"vout" 70.7\nEND\n')
    pp = Path(_tf.mkdtemp()) / "out.tran.tran"; pp.write_text(psf)
    res = parse_spectre_psf_ascii(pp)
    checks.append({"name": "Spectre PSF parser", "ok": res.ok and "vout" in (res.data or {}),
                   "sample": f"signals {list((res.data or {}).keys())}"})

    # 4. TCP round-trip via a fake daemon
    STX, NAK = "\x02", "\x15"
    srv = _socket.socket(); srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0)); port = srv.getsockname()[1]; srv.listen(2)

    def _serve():
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        with conn:
            buf = b""
            while True:
                ch = conn.recv(4096)
                if not ch:
                    break
                buf += ch
            try:
                skill = _json.loads(buf.decode())["skill"]
                reply = STX + str(eval(skill, {"__builtins__": {}}, {}))
            except Exception as e:  # noqa: BLE001
                reply = NAK + str(e)
            conn.sendall(reply.encode())

    _threading.Thread(target=_serve, daemon=True).start()
    rt = VirtuosoClient.local(port=port).execute_skill("6*7")
    srv.close()
    checks.append({"name": "VirtuosoClient TCP round-trip (fake daemon)",
                   "ok": rt.status is ExecutionStatus.SUCCESS and rt.output == "42",
                   "sample": f"execute_skill('6*7') -> {rt.output!r}"})

    return {"checks": checks, "allOk": all(c["ok"] for c in checks),
            "preflight": spectre_preflight()}


# --------------------------------------------------------------------------
# OTA Bode (AC magnitude / phase of the sized design)
# --------------------------------------------------------------------------
@app.get("/api/opamp/bode")
def get_opamp_bode(seed: int = 0) -> dict:
    return _compute_opamp_bode(seed)


@_kind("opamp/bode")
def _compute_opamp_bode(seed: int = 0) -> dict:
    from layout_opt.opamp import ac_response
    cand = de_log_refine(seed=seed).params
    freqs = list(np.logspace(2, 10, 200))    # 100 Hz .. 10 GHz
    mag_db, phase_deg = ac_response(cand, freqs)
    return {"freq": [float(f) for f in freqs],
            "magDb": [round(m, 3) for m in mag_db],
            "phaseDeg": [round(p, 2) for p in phase_deg]}


# --------------------------------------------------------------------------
# Agent console — proxy to the Hermes api_server (port 8650)
# --------------------------------------------------------------------------
class AgentIn(BaseModel):
    prompt: str
    port: int = 8650


@app.post("/api/agent")
def post_agent(body: AgentIn) -> dict:
    import json as _json
    import os as _os
    import urllib.request as _ur
    env = Path(_os.path.expanduser("~/.hermes/profiles/virtuoso-bridge/.env"))
    key = ""
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("API_SERVER_KEY="):
                key = line.split("=", 1)[1].strip()
                break
    if not key:
        return {"ok": False, "error": "Hermes virtuoso-bridge profile API_SERVER_KEY not found"}
    payload = _json.dumps({"model": "gpt-5.5",
                           "messages": [{"role": "user", "content": body.prompt}],
                           "stream": False}).encode()
    req = _ur.Request(f"http://127.0.0.1:{body.port}/v1/chat/completions", data=payload,
                      method="POST", headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json"})
    try:
        with _ur.urlopen(req, timeout=180) as r:
            resp = _json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"agent gateway unreachable: {e}"}
    if "error" in resp:
        return {"ok": False, "error": _json.dumps(resp["error"])[:400]}
    msg = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"ok": True, "reply": msg}


# --------------------------------------------------------------------------
# T-coil physical geometry: spiral layout -> extracted L/k -> response
# --------------------------------------------------------------------------
class GeomIn(BaseModel):
    turns: float = 3.0
    width: float = 3.0
    spacing: float = 2.0
    inner: float = 30.0
    r_ohm: float = 200.0
    cl_ff: float = 40.0
    cb: float = 0.14


@app.post("/api/tcoil/geometry")
def post_tcoil_geometry(body: GeomIn) -> dict:
    from layout_opt.tcoil_geom import TCoilGeometry, evaluate_geometry, spiral_points
    from layout_opt.tcoil import transimpedance
    g = TCoilGeometry(turns=body.turns, width=body.width,
                      spacing=body.spacing, inner=body.inner)
    r = evaluate_geometry(g, r_ohm=body.r_ohm, cl_ff=body.cl_ff, cb_norm=body.cb)
    ex = r["extract"]
    w = np.logspace(-1.0, 1.3, 160)
    mag = np.abs(transimpedance(r["params"], w))
    return {
        "path": [[round(x, 2), round(y, 2)] for x, y in spiral_points(g)],
        "width": body.width,
        "dOut": ex.d_out_um,
        "L_nH": round(ex.L_nH, 3),
        "k": ex.k,
        "wireUm": ex.wire_um,
        "areaUm2": ex.area_um2,
        "normL": r["normL"] if "normL" in r else r["norm_L"],
        "bwExtension": r["bw_extension"],
        "peakingDb": r["peaking_db"],
        "freq": [float(x) for x in w],
        "magDb": [round(float(20.0 * np.log10(m + 1e-12)), 3) for m in mag],
    }


# --------------------------------------------------------------------------
# Full foundry process-change effects (DRC geometry + device model + taxonomy)
# --------------------------------------------------------------------------
class EffectsIn(BaseModel):
    nl: str = ""
    overrides: dict = {}
    tech: dict = {}          # kp_n_mult, kp_p_mult, lambda_mult, vdd


@app.post("/api/process/effects")
async def post_process_effects(body: EffectsIn) -> dict:
    return await _offload("process/effects", **body.model_dump())


@_kind("process/effects", model=EffectsIn)
def _compute_process_effects(nl: str = "", overrides: dict | None = None,
                             tech: dict | None = None) -> dict:
    from layout_opt.process_change import (
        ProcessOverrides, parse_process_nl, process_effects,
    )
    ov = ProcessOverrides(overrides) if overrides else parse_process_nl(nl)
    return process_effects(ov, tech or None, maxiter=120)


# --------------------------------------------------------------------------
# Open-source closed loop: verify a candidate with ngspice (vs analytic)
# --------------------------------------------------------------------------
@app.get("/api/opamp/ngspice-eval")
async def get_opamp_ngspice_eval(seed: int = 0, model: str = "generic") -> dict:
    return await _offload("opamp/ngspice-eval", seed=seed, model=model)


@_kind("opamp/ngspice-eval", env=True)
def _compute_opamp_ngspice_eval(seed: int = 0, model: str = "generic") -> dict:
    from layout_opt.ngspice_backend import (
        GENERIC_NGSPICE, NgspiceUnavailable, ngspice_available, ngspice_evaluate,
        sky130_model, sky130_available,
    )
    use_sky = model == "sky130"
    dev_model = sky130_model() if use_sky else GENERIC_NGSPICE
    cand = de_log_refine(seed=seed).params
    a = evaluate_opamp(cand)
    out = {
        "backend": "ngspice",
        "model": dev_model.name,
        "modelKind": "sky130" if use_sky else "generic",
        "available": ngspice_available(),
        "sky130Available": sky130_available(),
        "analytic": {"gain_db": round(a.gain_db, 2), "gbw_mhz": round(a.gbw_hz / 1e6, 2),
                     "pm_deg": round(a.pm_deg, 2), "power_mw": round(a.power * 1e3, 4)},
    }
    if use_sky and not sky130_available():
        out["status"] = "sky130_unavailable"
        out["error"] = "SKY130 PDK not found. Install with `volare enable` and set PDK_ROOT."
        return out
    try:
        s = ngspice_evaluate(cand, dev_model)
        out["sim"] = {"gain_db": round(s.gain_db, 2), "gbw_mhz": round(s.gbw_hz / 1e6, 2),
                      "pm_deg": round(s.pm_deg, 2), "power_mw": round(s.power * 1e3, 4)}
        out["status"] = "ran_ngspice"
    except NgspiceUnavailable as e:
        out["status"] = "ngspice_unavailable"
        out["error"] = str(e)
    return out


# --------------------------------------------------------------------------
# Async jobs: submit -> 202, poll / SSE, cancel while queued
# --------------------------------------------------------------------------
class JobIn(BaseModel):
    kind: str
    params: dict = {}


def _job_or_404(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"unknown job {job_id} (finished jobs are evicted oldest-first)")
    return job


@app.post("/api/jobs", status_code=202)
async def post_job(body: JobIn) -> dict:
    """Queue any registered kind. An identical request (same provenance key)
    while one is queued/running returns that job (``deduplicated: true``); a
    request whose result is cached returns a job that is already ``done``.
    """
    if body.kind not in KINDS:
        raise HTTPException(422, {"error": f"unknown kind {body.kind!r}", "kinds": sorted(KINDS)})
    try:
        params = _validate(body.kind, body.params)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)) from e
    try:
        job, dedup = JOBS.submit(_plan(body.kind, params))
    except QueueFull as e:
        raise HTTPException(429, f"job queue full: {e}") from e
    return {"job_id": job.id, "status": job.status, "kind": job.plan.kind,
            "deduplicated": dedup, "cache": job.cache,
            "links": {"self": f"/api/jobs/{job.id}", "events": f"/api/jobs/{job.id}/events"}}


@app.get("/api/jobs")
def list_jobs() -> dict:
    return {"jobs": JOBS.list(), "counts": JOBS.counts()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return _job_or_404(job_id).snapshot()


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    job, cancelled = JOBS.cancel(job_id)
    if job is None:
        raise HTTPException(404, f"unknown job {job_id}")
    if not cancelled:
        raise HTTPException(409, f"job is {job.status}; only queued jobs can be cancelled")
    return job.snapshot(include_result=False)


def _sse(ev: dict) -> str:
    return f"id: {ev['id']}\nevent: {ev['type']}\ndata: {json.dumps(ev['data'], default=str)}\n\n"


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    """SSE: replays past events, then streams status/progress until terminal."""
    sub = JOBS.subscribe(job_id, asyncio.get_running_loop())
    if sub is None:
        raise HTTPException(404, f"unknown job {job_id}")
    past, q = sub

    def terminal(ev: dict) -> bool:
        return ev["type"] == "status" and ev["data"]["status"] in TERMINAL

    async def stream():
        try:
            for ev in past:
                yield _sse(ev)
                if terminal(ev):
                    return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(ev)
                if terminal(ev):
                    return
        finally:
            JOBS.unsubscribe(job_id, q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/health")
def get_health() -> dict:
    return {"status": "ok", "version": CODE_VERSION, "executor": SERVICE.stats(),
            "jobs": JOBS.counts(), "kinds": sorted(KINDS)}
