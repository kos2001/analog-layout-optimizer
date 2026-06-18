"""FastAPI backend exposing the (Virtuoso-free) layout optimization engine.

It reuses the exact same ``layout_opt`` package the offline PoC and tests use -
no logic is duplicated for the web. Endpoints:

  GET  /api/config    defaults, search bounds, PDK rules, fixed config
  POST /api/evaluate  params -> layout rects + area + DRC violations (live sliders)
  POST /api/optimize  run optimization -> per-generation frames + final best
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the layout_opt package importable (repo root is two levels up).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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
from layout_opt.tcoil import (
    TCoilParams,
    bandwidth,
    bw_extension,
    optimize_tcoil,
    peaking_db,
    transimpedance,
)
from layout_opt.routing import (
    RoutingParams,
    RoutingRules,
    connectivity_ok,
    route,
    routed_layout,
    routing_violations,
)

app = FastAPI(title="Analog Layout Optimizer", version="1.0")

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


@app.post("/api/joint")
def post_joint(body: OptimizeIn) -> dict:
    res, frames = optimize_joint_trajectory(
        cfg=CFG, rules=RULES, rrules=RRULES, seed=body.seed, maxiter=body.maxiter
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


@app.post("/api/optimize")
def post_optimize(body: OptimizeIn) -> dict:
    opt, frames = optimize_trajectory(
        cfg=CFG, rules=RULES, seed=body.seed, maxiter=body.maxiter
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


@app.get("/api/maze")
def get_maze() -> dict:
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
def get_tcoil() -> dict:
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
