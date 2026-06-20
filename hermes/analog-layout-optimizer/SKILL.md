---
name: analog-layout-optimizer
description: Use when the user wants to size or optimize an ANALOG / custom / mixed-signal circuit or its layout — op-amp / OTA transistor sizing, differential-pair area minimization under DRC, comparator routing, T-coil bandwidth extension, device+routing co-optimization, or driving Cadence Virtuoso/Spectre via virtuoso-bridge. Complements the digital-PnR ppa-closure-agent skill with the analog/AMS + Cadence side. Triggers on requests like "size this OTA for X MHz min power", "minimize the cell area under DRC", "route the comparator", "extend bandwidth with a T-coil", "which optimizer is best for this sizing", or "run an analog optimization experiment".
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [semiconductor, eda, analog, ams, sizing, opamp, ota, routing, maze, tcoil, optimization, virtuoso, spectre, drc]
    related_skills: [ppa-closure-agent, writing-plans, systematic-debugging]
---

# Analog Layout Optimizer

## Overview

Operate an offline, **Virtuoso-free** analog design-optimization engine. There
is currently no EDA server; that is the default supported mode. Keep Arcadia
`virtuoso-bridge-lite` as the optional runtime engine for future real
Virtuoso/Spectre access. Like the [[ppa-closure-agent]] for digital PnR, this skill
does **not** replace EDA tools — it generates knob candidates, scores them
against specs, and explains trade-offs — but for the **analog / custom** side:
transistor sizing, area-vs-DRC, routing, and passive (T-coil) optimization.

The engine lives at `ALO_REPO` (default
`/Users/kos2001/gitspace/virtuso_bridge/layout_opt_poc`, also at
`github.com/kos2001/analog-layout-optimizer`). Run it with the bridge venv
python so numpy/scipy/scikit-learn are available.

## When to use

- Size a two-stage Miller OTA (or similar) to meet gain/GBW/PM/slew at min power.
- Minimize a cell's area subject to DRC + drive-strength spec.
- Route a comparator (A* maze router) and report wirelength / net order.
- Extend bandwidth with a bridged T-coil (analytic, ~3x maximally-flat).
- Co-optimize device geometry **and** interconnect (true full-cell area).
- Compare optimization algorithms / diagnose why one struggles.

Do **not** use for: digital place-and-route QoR closure (use ppa-closure-agent),
RTL, or signoff-grade tool replacement.

## How to run (JSON tool calls)

Set up once per shell:

```bash
PY=/Users/kos2001/gitspace/virtuoso-bridge-lite/.venv/bin/python
ALO=~/.hermes/skills/semiconductor-eda/analog-layout-optimizer/scripts/alo.py
```

Each command prints one JSON object — parse it and report the numbers.

```bash
$PY $ALO opamp                 # size the OTA, min power; returns specs + sizing
$PY $ALO opamp-study --seeds 6 # optimizer comparison (the log-space finding)
$PY $ALO joint                 # device+routing co-optimization (full-cell area)
$PY $ALO maze                  # comparator maze routing (wirelength, net order)
$PY $ALO tcoil --peak 0.1      # T-coil bandwidth extension factor
$PY $ALO full-flow [--sky130]  # ONE-CLICK end-to-end: sizing->P&R->sign-off->post-layout
                               # ->[silicon]; returns per-stage status + overall verdict
$PY $ALO signoff [--place sa]  # place+route the OTA, run DRC+LVS+connectivity sign-off
$PY $ALO ppa                   # NSGA-II power/performance/area Pareto front + chosen design
$PY $ALO scenario macro_power_grid   # routing-algo comparison: fixed vs best-order vs
                               # PathFinder (also: bus_channel, diff_pair); shows DRC
$PY $ALO ngspice-eval [--model sky130]  # verify OTA on REAL ngspice; --model sky130 =
                               # real SkyWater SKY130 BSIM silicon (needs PDK_ROOT)
$PY $ALO pvt [--full]          # SKY130 PVT corner analysis: worst-case gain/GBW/PM
                               # across process/voltage/temp (slow, ~15 s/corner)
$PY $ALO bridge-smoke          # offline-safe: check Arcadia engine import/CLI; no EDA server required
$PY $ALO preflight             # optional future: check real-Spectre readiness (will be unready without EDA server)
$PY $ALO bridge-smoke --live   # optional future: execute SKILL 1+2 only after bridge is configured
$PY $ALO spectre-eval [--model-include '…' --nmos nch_mac --pmos pch_mac]
                               # verify a candidate via REAL Spectre against a PDK
                               # (analytic vs spectre; SpectreUnavailable+guidance if not connected)
$PY $ALO adapt --nl "<process change in natural language>"
                               # PROCESS MIGRATION: schematic fixed, re-optimize
                               # placement+routing to new DRC/spec; before/after areas
# or, when you (the agent) parse the request yourself, pass structured overrides:
$PY $ALO adapt --overrides '{"min_poly_pitch":0.3,"min_m_spacing":0.12,"w_min_total":3.0}'
```

**Process migration:** when the user describes a process/PDK change ("min poly
pitch is now 0.3 um", "migrate to a coarser metal", "drive needs more current"),
use `adapt`. The schematic/topology stays fixed; only placement (device
geometry) and routing are re-optimized to meet the new DRC rules + drive spec,
and you report the before/after area and DRC status. Override keys:
`min_l, min_w, min_poly_pitch, min_gr_gap, min_gr_width, min_m_width,
min_m_spacing, min_via, min_via_enclosure, w_min_total` (microns; w_min_total
unitless).

Example (`opamp`): a feasible design at ~0.13 mW meeting gain≥80 dB, GBW≥50 MHz,
PM≥65°, slew≥50 V/us. Use `opamp-study` to show that **log-space DE** gives ~2.8x
lower power and ~7x tighter variance than linear-space DE — the headline result.

## Visual UI (optional)

A React+FastAPI app visualizes layout/joint, the comparator maze grid, and the
T-coil Bode plot:

```bash
cd $ALO_REPO 2>/dev/null || cd /Users/kos2001/gitspace/virtuso_bridge/layout_opt_poc
$PY -m uvicorn webapp.backend.main:app --port 8011 &      # API: /api/{config,maze,tcoil,joint,optimize}
( cd webapp/frontend && npm run dev )                     # UI at http://localhost:5173
```

## Recommended architecture

Use this repo as the **application layer** and Arcadia
`virtuoso-bridge-lite` as the **runtime engine**:

```text
Hermes Agent / Web UI / FastAPI
        -> analog-layout-optimizer application layer
        -> Arcadia virtuoso-bridge-lite engine
        -> offline evaluators today; optional future Cadence Virtuoso + Spectre + PDK
```

Keep optimization, problem models, PDK config, surrogate loops, UI, and Hermes
workflow here. In the current no-EDA-server setup, use offline commands and treat
`bridge-smoke` as dependency readiness only. If a Cadence environment is added
later, delegate SKILL transport, SSH/jump-host tunnels, daemon lifecycle, Spectre
invocation, PSF parsing, Maestro snapshots, and window diagnostics to Arcadia's
`virtuoso-bridge` package/CLI.

## Optional future: driving real Cadence Virtuoso/Spectre

The engine's `evaluate()` / ground-truth functions are currently analytical
surrogates. Because there is no EDA server today, do not try live Cadence commands
by default. If a real PDK/server becomes available later, swap them for a `virtuoso-bridge`
backend (the bridge ships its own Claude/Hermes skills `virtuoso`, `spectre`,
`optimizer`):

1. Only after an EDA server exists: ensure `virtuoso-bridge start` is up (SSH tunnel + Virtuoso daemon) — see the
   bridge's AGENTS.md. `VirtuosoClient.from_env().execute_skill(...)` runs SKILL;
   `SpectreSimulator.from_env()` runs simulations.
2. Replace the surrogate FoM with: emit the candidate (the engine already builds
   real `dbCreateRect(...)` via the bridge's layout ops), run DRC/Spectre through
   the bridge, parse PSF, return the measured spec — same `(params -> scalar)`
   signature, so the optimizer/maze/joint code is unchanged.
3. Use the surrogate-assisted loop (`layout_opt/surrogate_opt.py`) to keep the
   number of expensive Spectre calls small (the PoC shows ~600x fewer).

## Reporting

Always report: which operation ran, the achieved specs vs targets, the chosen
sizing/geometry, feasibility/DRC status, and — for studies — the comparative
numbers. Be explicit that offline results use an analytical model; only the
bridge-backed path reflects the real PDK.
