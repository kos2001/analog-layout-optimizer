#!/usr/bin/env python3
"""Analog Layout Optimizer — JSON CLI for the Hermes Agent to call as a tool.

Wraps the layout_opt engine (offline, Virtuoso-free) so Hermes can run an
operation and parse structured JSON. Each subcommand prints one JSON object.

Repo + venv (override with env vars):
  ALO_REPO  default: /Users/kos2001/gitspace/virtuso_bridge/layout_opt_poc
  (run with the venv python:
   /Users/kos2001/gitspace/virtuso_bridge/virtuoso-bridge-lite/.venv/bin/python)

Usage:
  python alo.py opamp        [--seed N]      # size two-stage OTA, min power
  python alo.py opamp-study  [--seeds N]     # optimizer-algorithm comparison
  python alo.py joint        [--seed N]      # device+routing co-optimization
  python alo.py maze                         # comparator maze routing
  python alo.py tcoil        [--peak DB]     # T-coil bandwidth extension
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_REPO = os.environ.get(
    "ALO_REPO", "/Users/kos2001/gitspace/virtuso_bridge/layout_opt_poc"
)
sys.path.insert(0, _REPO)


def _opamp(args):
    from layout_opt.opamp_opt import de_log_refine
    d = de_log_refine(seed=args.seed)
    s = d.specs
    return {
        "op": "opamp_sizing",
        "feasible": d.feasible,
        "power_mw": round(d.power_mw, 4),
        "specs": {
            "gain_db": round(s.gain_db, 2),
            "gbw_mhz": round(s.gbw_hz / 1e6, 2),
            "pm_deg": round(s.pm_deg, 2),
            "slew_v_per_us": round(s.slew / 1e6, 2),
        },
        "sizing": {
            "wl1": round(d.params.wl1, 2), "wl3": round(d.params.wl3, 2),
            "wl5": round(d.params.wl5, 2), "wl6": round(d.params.wl6, 2),
            "wl7": round(d.params.wl7, 2),
            "itail_uA": round(d.params.itail * 1e6, 3),
            "i6_uA": round(d.params.i6 * 1e6, 3),
            "cc_pF": round(d.params.cc * 1e12, 4),
        },
    }


def _opamp_study(args):
    import numpy as np
    from layout_opt.opamp_opt import STRATEGIES
    out = {}
    for name, fn in STRATEGIES.items():
        powers = []
        for s in range(args.seeds):
            d = fn(seed=s)
            if d.feasible:
                powers.append(d.power_mw)
        arr = np.array(powers) if powers else np.array([float("nan")])
        out[name] = {
            "feasible": len(powers),
            "n": args.seeds,
            "best_mw": round(float(np.nanmin(arr)), 4),
            "mean_mw": round(float(np.nanmean(arr)), 4),
            "std_mw": round(float(np.nanstd(arr)) if len(arr) > 1 else 0.0, 4),
        }
    return {"op": "opamp_optimizer_study", "results": out}


def _joint(args):
    from layout_opt.joint import optimize_joint
    j = optimize_joint(seed=args.seed)
    return {
        "op": "joint_device_routing",
        "total_cell_area_um2": round(j.total_area, 4),
        "device_area_um2": round(j.device_area, 4),
        "wirelength_um": round(j.wirelength, 3),
        "drc_clean": j.is_clean,
        "device": {k: round(v, 4) for k, v in zip(j.device.ORDER, j.device.to_vector())},
        "routing": {k: round(v, 4) for k, v in zip(j.routing.ORDER, j.routing.to_vector())},
    }


def _maze(_args):
    from layout_opt.comparator import build_comparator
    from layout_opt.maze import optimize_net_order, route_all
    grid, nets = build_comparator()
    best = optimize_net_order(grid, nets)
    naive = route_all(grid, nets, list(nets.keys()))
    return {
        "op": "comparator_maze_routing",
        "optimized_order": best.order,
        "optimized_wirelength": best.total_wirelength,
        "naive_wirelength": naive.total_wirelength,
        "failed": best.failed,
        "per_net": {n: nr.wirelength for n, nr in best.routes.items()},
    }


def _adapt(args):
    # Process change in natural language (or JSON overrides) -> re-optimize
    # placement+routing to the new DRC/spec; schematic/topology stays fixed.
    import json as _json
    from layout_opt.process_change import ProcessOverrides, adapt, parse_process_nl
    if args.overrides:
        ov = ProcessOverrides(_json.loads(args.overrides))
    elif args.nl:
        ov = parse_process_nl(args.nl)
    else:
        raise SystemExit("adapt needs --nl '<text>' or --overrides '<json>'")
    r = adapt(ov, seed=args.seed, maxiter=args.maxiter)
    return {
        "op": "process_adapt",
        "overrides_applied": r.overrides,
        "before": r.before,
        "after": r.after,
        "area_delta_pct": round(r.area_delta_pct, 1),
        "topology_fixed": r.topology_fixed,
    }


def _preflight(_args):
    from layout_opt.spectre_backend import preflight
    return {"op": "spectre_preflight", **preflight()}


def _bridge_smoke(args):
    """Check the Arcadia virtuoso-bridge-lite engine boundary.

    Default mode is safe/offline: it verifies that the runtime engine can be
    imported and that the CLI is visible.  With --live, it also attempts a real
    SKILL round-trip through the configured/running bridge.
    """
    import importlib.metadata
    import shutil
    import subprocess
    from pathlib import Path

    out = {
        "op": "bridge_smoke",
        "architecture": "analog-layout-optimizer application layer -> Arcadia virtuoso-bridge-lite engine",
        "repo": _REPO,
        "checks": {},
    }

    try:
        import virtuoso_bridge  # type: ignore[import-not-found]
        module_file = getattr(virtuoso_bridge, "__file__", None)
        out["checks"]["python_import"] = {
            "ok": True,
            "module_file": str(Path(str(module_file)).resolve()) if module_file else "unknown",
            "version": importlib.metadata.version("virtuoso-bridge"),
        }
    except Exception as e:  # noqa: BLE001
        out["checks"]["python_import"] = {"ok": False, "error": str(e)}

    venv_cli = Path(sys.executable).with_name("virtuoso-bridge")
    cli = str(venv_cli) if venv_cli.exists() else shutil.which("virtuoso-bridge")
    out["checks"]["cli_on_path"] = {"ok": bool(cli), "path": cli}
    if cli:
        hp = subprocess.run([cli, "--help"], capture_output=True, text=True, timeout=args.timeout)
        help_text = (hp.stdout + hp.stderr)[:1000]
        out["checks"]["cli_identity"] = {
            "ok": "virtuoso-bridge" in help_text and "Hermes Agent" not in help_text,
            "returncode": hp.returncode,
            "help_head": help_text,
        }
    if cli and args.status:
        p = subprocess.run([cli, "status"], capture_output=True, text=True, timeout=args.timeout)
        out["checks"]["cli_status"] = {
            "ok": p.returncode == 0,
            "returncode": p.returncode,
            "stdout_tail": p.stdout[-2000:],
            "stderr_tail": p.stderr[-2000:],
        }

    env_path = Path(os.path.expanduser("~/.virtuoso-bridge/.env"))
    env_exists = env_path.exists()
    out["checks"]["default_env"] = {
        "ok": True,
        "configured": env_exists,
        "path": str(env_path),
        "status": "configured_for_live_bridge" if env_exists else "not_configured_optional_offline_mode",
    }

    if args.live:
        if not env_exists:
            out["checks"]["live_skill"] = {
                "ok": False,
                "status": "not_configured_optional",
                "error": "No ~/.virtuoso-bridge/.env. This is expected when no EDA/Virtuoso server is available.",
            }
        else:
            try:
                from virtuoso_bridge import ExecutionStatus, VirtuosoClient  # type: ignore[import-not-found]
                r = VirtuosoClient.from_env(timeout=args.timeout).execute_skill("1+2", timeout=args.timeout)
                out["checks"]["live_skill"] = {
                    "ok": r.status is ExecutionStatus.SUCCESS and str(r.output).strip() == "3",
                    "status": r.status.name,
                    "output": r.output,
                    "errors": r.errors,
                }
            except Exception as e:  # noqa: BLE001
                out["checks"]["live_skill"] = {"ok": False, "status": "attempted_but_failed", "error": str(e)}

    out["ready_offline"] = bool(out["checks"].get("python_import", {}).get("ok"))
    out["ready_live"] = bool(out["checks"].get("live_skill", {}).get("ok")) if args.live else None
    out["operating_mode"] = "offline_first_no_eda_server_required"
    if args.live and out["ready_live"]:
        out["operating_mode"] = "live_cadence_bridge"
    return out


def _spectre_eval(args):
    # Verify ONE candidate design with real Spectre against a PDK.
    from layout_opt.opamp_opt import de_log_refine
    from layout_opt.opamp import evaluate_opamp
    from layout_opt.pdk import GENERIC_PDK, PDKConfig
    from layout_opt.spectre_backend import SpectreUnavailable, spectre_evaluate

    cand = de_log_refine(seed=args.seed).params
    analytic = evaluate_opamp(cand)
    if args.model_include:
        pdk = PDKConfig(name="custom", model_include=args.model_include,
                        nmos=args.nmos, pmos=args.pmos, l_um=args.l_um)
    else:
        pdk = GENERIC_PDK
    out = {
        "op": "spectre_eval", "pdk": pdk.name,
        "candidate_sizing": {k: round(v, 4) for k, v in zip(cand.ORDER, cand.to_vector())},
        "analytic": {"gain_db": round(analytic.gain_db, 2),
                     "gbw_mhz": round(analytic.gbw_hz / 1e6, 2),
                     "pm_deg": round(analytic.pm_deg, 2),
                     "power_mw": round(analytic.power * 1e3, 4)},
    }
    try:
        s = spectre_evaluate(cand, pdk)
        out["spectre"] = {"gain_db": round(s.gain_db, 2),
                          "gbw_mhz": round(s.gbw_hz / 1e6, 2),
                          "pm_deg": round(s.pm_deg, 2),
                          "power_mw": round(s.power * 1e3, 4)}
        out["status"] = "ran_real_spectre"
    except SpectreUnavailable as e:
        from layout_opt.spectre_backend import preflight
        out["status"] = "spectre_unavailable"
        out["error"] = str(e)
        out["preflight"] = preflight()
    return out


def _tcoil(args):
    from layout_opt.tcoil import TCoilParams, bw_extension, optimize_tcoil
    r = optimize_tcoil(peak_limit_db=args.peak, seed=0)
    none = bw_extension(TCoilParams(0.0, 0.0, 0.0))
    return {
        "op": "tcoil_bandwidth_extension",
        "bw_extension_x": round(r.bw_extension, 3),
        "reference_x": round(none, 3),
        "peaking_db": round(r.peaking_db, 3),
        "params": {"L": round(r.params.L, 4), "k": round(r.params.k, 4), "Cb": round(r.params.Cb, 4)},
    }


def _ngspice_eval(args):
    """Verify a candidate OTA with REAL ngspice (open-source closed loop)."""
    from layout_opt.opamp_opt import de_log_refine
    from layout_opt.opamp import evaluate_opamp
    from layout_opt.ngspice_backend import (
        GENERIC_NGSPICE, NgspiceUnavailable, ngspice_available, ngspice_evaluate,
    )
    cand = de_log_refine(seed=args.seed).params
    a = evaluate_opamp(cand)
    out = {"op": "ngspice_eval", "model": GENERIC_NGSPICE.name,
           "available": ngspice_available(),
           "analytic": {"gain_db": round(a.gain_db, 2), "gbw_mhz": round(a.gbw_hz / 1e6, 2),
                        "pm_deg": round(a.pm_deg, 2), "power_mw": round(a.power * 1e3, 4)}}
    try:
        s = ngspice_evaluate(cand, GENERIC_NGSPICE)
        out["sim"] = {"gain_db": round(s.gain_db, 2), "gbw_mhz": round(s.gbw_hz / 1e6, 2),
                      "pm_deg": round(s.pm_deg, 2), "power_mw": round(s.power * 1e3, 4)}
        out["status"] = "ran_ngspice"
    except NgspiceUnavailable as e:  # noqa: BLE001
        out["status"] = "ngspice_unavailable"; out["error"] = str(e)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Analog Layout Optimizer JSON CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("opamp"); p.add_argument("--seed", type=int, default=0); p.set_defaults(fn=_opamp)
    p = sub.add_parser("opamp-study"); p.add_argument("--seeds", type=int, default=6); p.set_defaults(fn=_opamp_study)
    p = sub.add_parser("joint"); p.add_argument("--seed", type=int, default=0); p.set_defaults(fn=_joint)
    p = sub.add_parser("maze"); p.set_defaults(fn=_maze)
    p = sub.add_parser("tcoil"); p.add_argument("--peak", type=float, default=0.1); p.set_defaults(fn=_tcoil)
    p = sub.add_parser("adapt")
    p.add_argument("--nl", default="", help="process change in natural language")
    p.add_argument("--overrides", default="", help='JSON dict of rule/spec overrides')
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--maxiter", type=int, default=150)
    p.set_defaults(fn=_adapt)
    p = sub.add_parser("preflight"); p.set_defaults(fn=_preflight)
    p = sub.add_parser("bridge-smoke")
    p.add_argument("--live", action="store_true", help="execute SKILL 1+2 through a configured/running bridge")
    p.add_argument("--status", action="store_true", help="also run `virtuoso-bridge status` if CLI is on PATH")
    p.add_argument("--timeout", type=int, default=10)
    p.set_defaults(fn=_bridge_smoke)
    p = sub.add_parser("spectre-eval")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--model-include", default="")
    p.add_argument("--nmos", default="nch_mac"); p.add_argument("--pmos", default="pch_mac")
    p.add_argument("--l-um", type=float, default=0.18, dest="l_um")
    p.set_defaults(fn=_spectre_eval)
    p = sub.add_parser("ngspice-eval"); p.add_argument("--seed", type=int, default=0); p.set_defaults(fn=_ngspice_eval)
    args = ap.parse_args()
    print(json.dumps(args.fn(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
