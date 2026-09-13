"""Batch mode: config-driven, reproducible flow runs with a tool-style run directory.

    python -m layout_opt flow -f flow.json --outdir runs/ota_tt
    python -m layout_opt flow --seeds 0,1,2,3 --sky130

A run directory looks like a commercial P&R / sign-off tool's:

    <outdir>/
      flow.json            effective configuration + environment (reproducibility)
      logs/run.log         timestamped log with message IDs (ALO-xxx)
      reports/qor.rpt      verdict, stage summary, per-stage wall/CPU/peak RSS
      reports/sizing.rpt   placement.rpt  route.rpt  drc.rpt  lvs.rpt  postlayout.rpt
      outputs/design.json  full flow database (same payload as the web API)
      outputs/<top>.gds    GDSII layout (when gdstk is installed)

Exit status: 0 sign-off PASS, 1 FAIL, 2 configuration or runtime error — so a
run can gate CI or a regression farm directly.
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .runlog import Profiler, peak_rss_mb, stage

TOOL = "analog-layout-optimizer"
EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2

DEFAULTS = {
    "design": "two_stage_ota",
    "place": "sa",               # sa | random
    "seeds": [0],                # >1 seed: best-of-N by sign-off ranking
    "maxiter": 90,               # sizing DE iterations
    "sky130": False,             # silicon verify with ngspice + SKY130 (if installed)
    "gds": True,                 # write outputs/<top>.gds
    "klayout_drc": False,        # geometric DRC of the GDS with KLayout
}
_DESIGNS = {"two_stage_ota"}

log = logging.getLogger("alo")


class ConfigError(ValueError):
    pass


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
def load_config(path: str | None, overrides: dict) -> dict:
    cfg = dict(DEFAULTS)
    if path:
        try:
            user = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigError(f"cannot read config {path}: {e}") from e
        unknown = set(user) - set(DEFAULTS)
        if unknown:
            raise ConfigError(f"unknown config key(s): {', '.join(sorted(unknown))}")
        cfg.update(user)
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    if cfg["design"] not in _DESIGNS:
        raise ConfigError(f"unknown design {cfg['design']!r} (available: {', '.join(sorted(_DESIGNS))})")
    if cfg["place"] not in ("sa", "random"):
        raise ConfigError(f"place must be 'sa' or 'random', got {cfg['place']!r}")
    if isinstance(cfg["seeds"], int):
        cfg["seeds"] = [cfg["seeds"]]
    if not cfg["seeds"] or not all(isinstance(s, int) for s in cfg["seeds"]):
        raise ConfigError("seeds must be a non-empty list of integers")
    if not isinstance(cfg["maxiter"], int) or cfg["maxiter"] < 1:
        raise ConfigError("maxiter must be a positive integer")
    return cfg


def _git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=Path(__file__).resolve().parent, capture_output=True,
                              text=True, timeout=5).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
def _header(title: str, meta: dict) -> str:
    bar = "#" * 78
    return (f"{bar}\n#  {title}\n#  Tool    : {TOOL} ({meta['revision']})\n"
            f"#  Design  : {meta['design']}\n#  Date    : {meta['started']}\n{bar}\n\n")


def _table(rows: list[list], headers: list[str]) -> str:
    cells = [headers] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    fmt = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip()
    return "\n".join([fmt(headers), fmt(["-" * w for w in widths])] + [fmt(r) for r in cells[1:]]) + "\n"


def report_qor(result: dict, prof: Profiler, meta: dict, total_s: float) -> str:
    out = _header("QoR Summary", meta)
    out += f"Verdict            : {result['verdict']}\n"
    if "sweep" in result:
        sw = result["sweep"]
        out += f"Seeds              : {sw['seeds']}  (best seed {sw['bestSeed']}; verdicts {sw['verdicts']})\n"
    out += f"Total wall time    : {total_s:.2f} s\nPeak memory (RSS)  : {peak_rss_mb():.1f} MB\n\n"
    out += "Flow stages\n" + _table(
        [[s["name"], s["status"].upper(), s["detail"]] for s in result["stages"]],
        ["Stage", "Status", "Detail"])
    out += "\nResource usage by stage\n" + _table(
        [[st.name, st.calls, f"{st.wall_s:.3f}", f"{st.cpu_s:.3f}", f"{st.peak_rss_mb:.1f}"]
         for st in prof.stats.values()],
        ["Stage", "Calls", "Wall(s)", "CPU(s)", "PeakRSS(MB)"])
    return out


def report_sizing(result: dict, meta: dict) -> str:
    sz = result["sizing"]
    out = _header("Sizing Report", meta)
    out += f"Feasible : {'yes' if sz['feasible'] else 'NO - specs not met'}\n\n"
    out += _table([[k, v] for k, v in sz.items() if k != "feasible"], ["Parameter", "Value"])
    if result.get("silicon"):
        out += "\nSilicon verify (SKY130, ngspice)\n"
        out += _table([[k, v] for k, v in result["silicon"].items()], ["Metric", "Value"])
    return out


def report_placement(result: dict, meta: dict) -> str:
    m = result["matching"]
    out = _header("Placement Report", meta)
    out += (f"Placer            : {result['place']}  (analog-aware: {result['analogAware']})\n"
            f"Die (grid cells)  : {result['width']} x {result['height']}, {result['layers']} routing layers\n"
            f"HPWL              : {result['hpwl']}\nCritical-net WL   : {m['critical_wl']}\n"
            f"Symmetry penalty  : {m['symmetry_penalty']}\n\n")
    out += "Matched pairs (centroid distance)\n" + _table(
        [[k, v] for k, v in m["pair_distance"].items()], ["Pair", "Distance"])
    out += "\nInstances\n" + _table(
        [[c["id"], c["kind"], c["x"], c["y"], f"{c['w']}x{c['h']}"] for c in result["components"]],
        ["Instance", "Kind", "X", "Y", "Size"])
    return out


def report_route(result: dict, meta: dict) -> str:
    r = result["routing"]
    out = _header("Routing Report", meta)
    out += (f"Router            : negotiated congestion (PathFinder), {result['layers']} layers\n"
            f"Converged         : {r['converged']} after {r['iterations']} iteration(s)\n"
            f"Total wirelength  : {r['totalWirelength']}\nTotal vias        : {r['totalVias']}\n"
            f"Unrouted nets     : {len(r['failed'])}{' (' + ', '.join(r['failed']) + ')' if r['failed'] else ''}\n\n")
    out += _table([[n, len(nr["pins"]), nr["wirelength"], nr["vias"], "yes" if nr["routed"] else "NO"]
                   for n, nr in r["nets"].items()],
                  ["Net", "Pins", "Wirelength", "Vias", "Routed"])
    return out


def report_drc(result: dict, meta: dict, klayout: dict | None) -> str:
    from .signoff import ERROR_RULES
    d = result["signoff"]["drc"]
    out = _header("DRC Report", meta)
    errors = sum(n for rule, n in d["counts"].items() if rule in ERROR_RULES)
    warnings = d["total"] - errors
    status = "CLEAN" if d["clean"] else ("PASS (warnings only)" if errors == 0 else "FAIL")
    out += (f"Result            : {status} - {errors} error(s), {warnings} warning(s)\n"
            f"Rules checked     : {', '.join(d['checkedRules'])}\n\n")
    out += _table([[rule, "error" if rule in ERROR_RULES else "warning", n]
                   for rule, n in d["counts"].items()], ["Rule", "Severity", "Count"])
    if d["violations"]:
        out += "\nViolations\n"
        for i, v in enumerate(d["violations"], 1):
            out += f"  {i:4d}. [{v['rule']}] {v['message']}\n"
        if d["total"] > len(d["violations"]):
            out += f"  ... {d['total'] - len(d['violations'])} more not listed\n"
    if klayout is not None:
        out += "\nKLayout geometric DRC (GDS)\n"
        if not klayout.get("available", True):
            out += f"  skipped: {klayout.get('reason', 'KLayout not available')}\n"
        else:
            out += f"  tool: {klayout.get('tool')}  total: {klayout['total']}  clean: {klayout['clean']}\n"
    return out


def report_lvs(result: dict, meta: dict) -> str:
    l = result["signoff"]["lvs"]
    out = _header("LVS Report", meta)
    out += (f"Result            : {'CORRECT' if l['clean'] else 'INCORRECT'}\n"
            f"Devices checked   : {l['nDevicesChecked']}\nSchematic nets    : {l['nSchematicNets']}\n"
            f"Layout nodes      : {l['nLayoutNodes']}\n\n")
    for s in l["shorts"]:
        out += f"  SHORT     nets {' / '.join(s['nets'])} merged\n"
    for o in l["opens"]:
        out += f"  OPEN      net {o['net']} split into {o['components']} components\n"
    for f in l["floating"]:
        out += f"  FLOATING  terminal {f} not on its net's metal\n"
    return out


def report_postlayout(result: dict, meta: dict) -> str:
    pl = result["postlayout"]
    out = _header("Post-layout (Parasitics) Report", meta)
    out += _table([[k, pl["pre"][k], pl["post"].get(k, "-")] for k in pl["pre"]],
                  ["Spec", "Pre-layout", "Post-layout"])
    out += f"\nDelta PM          : {pl['deltaPM']} deg\nStable (PM > 45)  : {pl['stable']}\n\n"
    out += "Extracted parasitics per net\n" + _table(
        [[n, *(v.get(k, "-") for k in ("R_ohm", "C_fF", "wirelength", "vias"))]
         for n, v in pl["parasitics"].items()],
        ["Net", "R(ohm)", "C(fF)", "WL", "Vias"])
    return out


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------
def _setup_logging(logfile: Path, quiet: bool) -> None:
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(logfile, mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if not quiet:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)


def run_flow_batch(cfg: dict, outdir: Path, quiet: bool = False) -> int:
    from .flow_e2e import run_best_of, run_end_to_end

    outdir = Path(outdir)
    for sub in ("logs", "reports", "outputs"):
        (outdir / sub).mkdir(parents=True, exist_ok=True)
    _setup_logging(outdir / "logs" / "run.log", quiet)
    meta = {"design": cfg["design"], "revision": _git_rev(),
            "started": datetime.now().isoformat(timespec="seconds")}
    (outdir / "flow.json").write_text(json.dumps({
        "config": cfg, **meta, "python": platform.python_version(),
        "platform": platform.platform(), "argv": sys.argv}, indent=2))

    log.info("(ALO-001) %s rev %s — design %s", TOOL, meta["revision"], cfg["design"])
    log.info("(ALO-002) Run directory: %s", outdir.resolve())
    log.info("(ALO-003) Config: %s", json.dumps(cfg, sort_keys=True))

    def on_stage(st, wall):
        log.info("(ALO-100) Stage %-11s done in %.3f s (peak RSS %.1f MB)", st.name, wall, st.peak_rss_mb)

    t0 = time.perf_counter()
    with Profiler(on_stage) as prof:
        if len(cfg["seeds"]) > 1:
            log.info("(ALO-010) Seed sweep %s, selecting best by sign-off ranking", cfg["seeds"])
            result = run_best_of(place=cfg["place"], seeds=cfg["seeds"],
                                 sky130=cfg["sky130"], maxiter=cfg["maxiter"])
        else:
            result = run_end_to_end(place=cfg["place"], seed=cfg["seeds"][0],
                                    sky130=cfg["sky130"], maxiter=cfg["maxiter"])

        for st in result["stages"]:
            level = {"fail": logging.ERROR, "warn": logging.WARNING}.get(st["status"], logging.INFO)
            log.log(level, "(ALO-200) %-26s %-4s %s", st["name"], st["status"].upper(), st["detail"])

        klayout = None
        gds_path = outdir / "outputs" / f"{cfg['design']}.gds"
        if cfg["gds"] or cfg["klayout_drc"]:
            try:
                from .gds import flow_to_gds
            except ImportError:
                log.warning("(ALO-301) gdstk not installed — GDS output skipped")
            else:
                with stage("gds_export"):
                    stats = flow_to_gds(result, str(gds_path))
                log.info("(ALO-300) Wrote GDSII %s (top %s, %d polygons, %.1f um^2)",
                         gds_path, stats["topCell"], stats["polygons"], stats["area_um2"])
                if cfg["klayout_drc"]:
                    try:
                        from .klayout_drc import klayout_available, run_drc
                    except ImportError:
                        klayout_available = lambda: False
                    if klayout_available():
                        with stage("klayout_drc"):
                            klayout = run_drc(str(gds_path))
                        log.info("(ALO-310) KLayout DRC: %s violation(s)", klayout["total"])
                    else:
                        klayout = {"available": False, "reason": "klayout python module not installed"}
                        log.warning("(ALO-311) KLayout not available — geometric DRC skipped")
    total = time.perf_counter() - t0

    reports = {
        "qor.rpt": report_qor(result, prof, meta, total),
        "sizing.rpt": report_sizing(result, meta),
        "placement.rpt": report_placement(result, meta),
        "route.rpt": report_route(result, meta),
        "drc.rpt": report_drc(result, meta, klayout),
        "lvs.rpt": report_lvs(result, meta),
        "postlayout.rpt": report_postlayout(result, meta),
    }
    for name, text in reports.items():
        (outdir / "reports" / name).write_text(text)
    (outdir / "outputs" / "design.json").write_text(json.dumps(result, indent=1, default=str))
    log.info("(ALO-400) Reports written to %s", outdir / "reports")

    verdict = result["verdict"]
    if klayout is not None and klayout.get("available", True) and not klayout["clean"]:
        verdict = "FAIL"
        log.error("(ALO-402) KLayout DRC is not clean — overriding verdict to FAIL")
    level = logging.INFO if verdict == "PASS" else logging.ERROR
    log.log(level, "(ALO-900) Flow %s in %.2f s, peak RSS %.1f MB", verdict, total, peak_rss_mb())
    return EXIT_PASS if verdict == "PASS" else EXIT_FAIL


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m layout_opt",
                                 description="Analog layout optimizer — batch mode.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    fl = sub.add_parser("flow", help="run sizing -> P&R -> sign-off -> post-layout and write a run directory")
    fl.add_argument("-f", "--config", help="JSON flow configuration (keys: " + ", ".join(DEFAULTS) + ")")
    fl.add_argument("-o", "--outdir", help="run directory (default: runs/<design>_<timestamp>)")
    fl.add_argument("--place", choices=("sa", "random"))
    fl.add_argument("--seeds", help="comma-separated seeds, e.g. 0,1,2,3 (best-of-N)")
    fl.add_argument("--maxiter", type=int, help="sizing optimizer iterations")
    fl.add_argument("--sky130", action="store_true", default=None, help="silicon verify with SKY130")
    fl.add_argument("--no-gds", dest="gds", action="store_false", default=None, help="skip GDSII output")
    fl.add_argument("--klayout-drc", action="store_true", default=None, help="run KLayout DRC on the GDS")
    fl.add_argument("-q", "--quiet", action="store_true", help="log to file only")
    sub.add_parser("defaults", help="print the default flow configuration as JSON")
    args = ap.parse_args(argv)

    if args.cmd == "defaults":
        print(json.dumps(DEFAULTS, indent=2))
        return EXIT_PASS

    try:
        seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else None
        cfg = load_config(args.config, {"place": args.place, "seeds": seeds, "maxiter": args.maxiter,
                                        "sky130": args.sky130, "gds": args.gds,
                                        "klayout_drc": args.klayout_drc})
    except (ConfigError, ValueError) as e:
        print(f"ERROR (ALO-002) {e}", file=sys.stderr)
        return EXIT_ERROR
    outdir = Path(args.outdir or f"runs/{cfg['design']}_{datetime.now():%Y%m%d_%H%M%S}")
    try:
        return run_flow_batch(cfg, outdir, quiet=args.quiet)
    except Exception:
        log.exception("(ALO-999) Internal error — flow aborted")
        if not log.handlers:
            raise
        return EXIT_ERROR
