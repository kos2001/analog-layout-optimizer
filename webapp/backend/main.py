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


@app.get("/api/opamp")
def get_opamp() -> dict:
    return _opamp_design_payload(0)


@app.get("/api/opamp/study")
def get_opamp_study(seeds: int = 4) -> dict:
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
def get_opamp_spectre_eval(seed: int = 0) -> dict:
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
def post_adapt(body: AdaptIn) -> dict:
    from layout_opt.process_change import (
        ProcessOverrides, apply_overrides, parse_process_nl,
    )
    from layout_opt.joint import optimize_joint

    ov = ProcessOverrides(body.overrides) if body.overrides else parse_process_nl(body.nl)
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
def get_surrogate(target: float = 3.5) -> dict:
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
def get_skill() -> dict:
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
