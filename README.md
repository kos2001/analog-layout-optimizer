# Analog Layout Optimization PoC — *without* Virtuoso

A working, fully-tested proof of concept for an **analog design + layout flow**
that runs and verifies entirely **offline** — no running Cadence Virtuoso, no
license needed. It now spans the whole loop, schematic to silicon:

> **sizing (DE)** → **schematic netlist** → **placement (SA)** → **routing
> (negotiated, multi-layer)** → **sign-off (DRC + LVS + connectivity)** →
> **parasitic extraction → post-layout re-sim** → **optional SKY130 silicon
> verify (real PDK)**

It demonstrates which layers of an analog flow can be built and validated before
any commercial EDA tool is in the loop, using `virtuoso-bridge-lite`'s pure SKILL
builders, plus open-source **ngspice** and the open **SKY130** PDK for real
device physics. **140+ tests**, all green offline (SKY130/Spectre paths degrade
gracefully when the PDK/server is absent).

See **[End-to-end flow & web app](#end-to-end-flow--web-app)** for the one-click
pipeline and the interactive UI.

## Recommended architecture

This repo is **offline-first**: it runs today without an EDA server, Virtuoso,
PDK, or license. It is the **analog optimization application layer**. Arcadia
[`virtuoso-bridge-lite`](https://github.com/Arcadia-1/virtuoso-bridge-lite) stays
underneath as the optional Cadence runtime engine for a future live setup.

```text
Hermes Agent / Web UI / FastAPI
        |
        v
analog-layout-optimizer application layer
  - geometry/routing/problem models
  - PDK config + netlist templates
  - optimizers and surrogate-assisted loops
  - visualization and Hermes workflows
        |
        v
Arcadia virtuoso-bridge-lite engine
  - VirtuosoClient SKILL execution
  - SSH/jump-host/local bridge lifecycle
  - SpectreSimulator + PSF parsing
  - Maestro/window/snapshot diagnostics
        |
        v
Optional future: remote/local Cadence Virtuoso + Spectre + PDK
```

Boundary: keep design objectives, candidate generation, surrogate logic, UI, and
customer-specific PDK configuration in this repo. Offline mode is the default and
fully supported. If a live Cadence environment exists later, delegate SKILL
transport, daemon/tunnel lifecycle, Spectre invocation, PSF parsing, and
Virtuoso/Maestro diagnostics to `virtuoso-bridge-lite`; do not grow a second
bridge here. See `docs/arcadia-integration.md` for the operating checklist.

## End-to-end flow & web app

A FastAPI backend (`webapp/backend`) + React/Vite frontend (`webapp/frontend`)
expose every stage. The **Full flow** tab runs the whole pipeline on one click
(`/api/full-flow` → `layout_opt/flow_e2e.py`) and shows a stage-by-stage verdict;
the other tabs let you explore each stage interactively.

```
┌ sizing (DE, log-space) ── opamp_opt.py        minimize power s.t. gain/GBW/PM/slew
│ schematic (netlist) ───── schematic.py        OTA devices+terminals = single source of truth
│ placement (SA) ────────── placement.py        minimize HPWL (+ overlap)
│ routing (negotiated) ──── mlroute.py           2-layer PathFinder rip-up-and-reroute
│ sign-off ──────────────── drc.py + signoff.py  DRC + LVS (extract vs netlist) + connectivity
│ post-layout ───────────── parasitics.py        extract R/C → re-sim → ΔPM
└ silicon verify (opt.) ─── ngspice_backend.py   real SKY130 BSIM via ngspice
```

| Web tab | What it shows |
|---|---|
| **Full flow** | one-click sizing→silicon pipeline + verdict |
| Layout / Joint | device + interconnect geometry optimization |
| Comparator (maze) | A* maze routing + **drag-to-place** live re-routing |
| Complex cases | bus/macro+power-grid/diff-pair; **fixed vs best-order vs PathFinder** + DRC |
| Schematic → P&R | netlist → placement → routing, **sign-off panel + DRC overlay + post-layout** |
| PPA | **NSGA-II** power/performance/area **Pareto front** + preference weighting |
| Op-amp (OTA) | sizing + AC Bode + Verify (**generic level-1 / SKY130 real PDK** / Spectre) |
| T-coil, Process, Surrogate, Bridge, Agent | bandwidth peaking, foundry-change effects, surrogate loop, bridge smoke, Hermes agent |

### Run the web app

```bash
# backend (set PDK_ROOT to enable the SKY130 path; optional)
PDK_ROOT=~/pdk python -m uvicorn webapp.backend.main:app --port 8011
# frontend (Vite dev server proxies /api → :8011)
cd webapp/frontend && npm install && npm run dev      # http://localhost:5173
```

`/api/full-flow?place=sa&seed=1&sky130=false` returns the staged report headless.

### Routing algorithms — is A\* enough?

`scenarios.py` + `mlroute.py` answer this with running comparisons. A\* is optimal
*per net*, but routing nets sequentially makes the result depend on net order
(NP-hard). On congested cases **fixed-order A\*** strands nets or burns vias;
**PathFinder negotiated congestion** (rip-up-and-reroute, order-independent) on a
**2-layer** surface routes them all. E.g. the macro+power-grid case: fixed-order
leaves a net unrouted; negotiation routes all 8 cleanly.

### Sign-off (DRC + LVS) and post-layout

`drc.py` checks the routed geometry (short/corner/via-spacing/open); `signoff.py`
runs **LVS** — it extracts per-net connectivity from the routed metal and verifies
it matches the schematic netlist (terminals on one component = no open; no shared
cell = no short) — then gives a PASS/FAIL verdict. `parasitics.py` then extracts
R/C and re-simulates: parasitic C on the output and on the high-impedance internal
node degrade phase margin. A tighter (SA) placement degrades far less than a
random one — the concrete link from **placement quality → silicon performance**.

### GDS export (`gds.py`)

The placed+routed flow exports to real **GDSII** (`gdstk`, no PDK needed) on
SKY130 stream layers (met1 68/20, met2 69/20, via 68/44, device 65/20, labels) —
each routing-grid cell becomes metal, vias where a net changes layer, a marker +
label per device. The file opens in **KLayout / Magic** and can be DRC'd against
the SKY130 deck — the bridge from the in-house grid sign-off to real-tool
verification. Schematic→P&R tab → **Export GDS**, or `alo.py gds`.

### Real DRC with KLayout (`klayout_drc.py`)

The exported GDS is checked by **KLayout's actual geometric DRC engine** (pip
`klayout`, no GUI): met1/met2 min-width and min-spacing with SKY130 rules
(0.14 µm). It **cross-validates** the in-house grid DRC — both flag the same
corner/notch regions, now at true geometry. Schematic→P&R tab → **Real DRC
(KLayout)**, `alo.py klayout-drc`, or `/api/flow/drc-klayout`.

Honest scope: this is **metal-layer geometric DRC**. Full device-level DRC
(poly/diff/well/contact) and **Netgen LVS** need a transistor-level layout
(real devices, contacts, wells) — the abstract grid router doesn't emit one, so
those are a separate layout-synthesis effort, not a check on this GDS. The
in-house connectivity LVS (`signoff.py`) is the right fidelity for this stage.

### Real SKY130 silicon (`ngspice_backend.py`)

The OTA Verify can run on real **SkyWater SKY130** BSIM devices
(`sky130_fd_pr__{n,p}fet_01v8`) through the open PDK's ngspice `.lib`, instead of
the analytic square-law model. Same sizing, different (silicon-grade) numbers —
the model-fidelity gap that motivates post-layout sim. Install the PDK with
`volare enable` and point `PDK_ROOT` at it; without it the path degrades to a
clear "PDK missing" and the live tests skip.

## The cell

A textbook differential pair: two transistors as `2·nf` interdigitated vertical
poly fingers over a shared diffusion, wrapped in a guard ring.

```
 guard ring (M1)
 +-----------------------------+
 |  | | | | | | | |  poly      |   2·nf fingers
 |  [== OD diffusion ==]       |
 +-----------------------------+
```

The optimizer searches 5 continuous geometric parameters
(`w_finger, L, finger_pitch, guard_gap, gr_width`) to **minimize bounding-box
area** subject to:
- **DRC floors** — min L / min W / min poly pitch / min guard gap / min ring width
- **a drive-strength spec** — `nf · w_finger ≥ w_min_total`

## What is verified offline (and how)

| Layer | Module | Verified by |
|---|---|---|
| Parameterized geometry generation | `generator.py`, `geometry.py` | shape count, closed-form bbox/area (`test_generator.py`) |
| SKILL emission (the bridge call surface) | `skill.py` | string-identical to `virtuoso_bridge`'s own `layout_create_rect` (`test_skill_emit.py`) |
| Geometric DRC + spec checks | `evaluate.py` | per-rule penalty math (`test_evaluate.py`) |
| Optimization loop | `optimize.py` | converges to the **hand-derived analytic optimum** (`test_optimize.py`) |

The optimum is analytically known (every parameter is pushed to its binding
lower bound), so the test suite proves generator + evaluator + optimizer are
*jointly* correct — without Virtuoso ever running.

## What is deferred to optional future Virtuoso access

No EDA server is required for this repo's current operating mode. If a live
Cadence environment becomes available later, it would be used for:

- Whether the emitted SKILL produces **valid geometry in the real PDK**
- **Real DRC / LVS** against the PDK deck
- **Parasitic extraction (PEX)** and post-layout performance

These are intentionally not modeled. The surrogate `evaluate()` has the same
`(params → scalar)` signature as a future Virtuoso/Spectre backend, so swapping
it in is a one-function change — see the bottom of `run_demo.py`.

## Run it

```bash
# from repo root, with Arcadia virtuoso-bridge-lite cloned adjacent to this repo
uv pip install -e ../virtuoso-bridge-lite numpy scipy scikit-learn pytest

python -m pytest -q          # 150+ tests, all offline (SKY130 live tests skip if no PDK)
python run_demo.py           # device demo: optimize → report → emit SKILL
# full schematic→silicon pipeline, headless:
python -c "from layout_opt.flow_e2e import run_end_to_end as r; \
import json; print(json.dumps(r('sa',1)['stages'], indent=1))"
```

Arcadia engine smoke checks (safe without an EDA server):

```bash
python verify_bridge.py
python hermes/analog-layout-optimizer/scripts/alo.py bridge-smoke
# optional future only, when a real bridge is configured and started:
python hermes/analog-layout-optimizer/scripts/alo.py bridge-smoke --live
```

Demo output: converges in ~15k evals to **area 2.1010 µm², DRC-clean**, then
prints the 13 `dbCreateRect(...)` SKILL commands that would build the cell.

## Can a surrogate replace Virtuoso? (`surrogate_*`, `truth.py`)

`python run_surrogate_demo.py` answers this directly. It models an *expensive*
post-layout figure of merit (a gain proxy `gm·ro ~ √(W_total·L)` degraded by
layout parasitics — `truth.py`, the Spectre+PEX stand-in) and runs
**surrogate-assisted optimization**:

1. Sample a few designs, evaluate the ground truth → train a GP surrogate
   (`surrogate.py`).
2. Minimize area s.t. DRC + drive-spec + **surrogate**-predicted FoM ≥ target,
   using thousands of cheap surrogate calls (`surrogate_opt.py`).
3. **Validate** the proposed optimum against the ground truth (one expensive
   call), record surrogate-vs-truth error, add the point, retrain. Repeat.

Observed (target FoM 3.5):

| | value |
|---|---|
| pure area optimum | 2.101 µm², FoM 2.15 — **fails** the gain target |
| surrogate-assisted optimum | 2.186 µm², FoM 3.66 (truth-verified ✓) |
| prediction error at optimum | 0.70 → 0.001 over 6 rounds |
| ground-truth calls | **30** |
| surrogate calls | 18,450 (**≈615× fewer** expensive evaluations) |

Takeaways:
- The surrogate **does** replace Virtuoso/Spectre *inside the search loop* — that
  is where the 615× saving comes from.
- It does **not** replace ground truth for trust: round 1 the surrogate
  predicted 3.52 but the truth was 3.31 — the validation loop caught the
  over-optimistic point and retraining corrected it.
- **Sign-off (real DRC/LVS/PEX) still needs the tool.** A surrogate is an
  accelerator, not a substitute for the physical verdict.

This is the same swap-the-`evaluate`-backend idea: here the loop's expensive
term is served by a learned model plus periodic ground-truth validation.

## Routing optimization (`routing.py`)

`python run_routing_demo.py` optimizes the **interconnect**, not just the
device. A structured router connects the interdigitated fingers to net rails
(gates → VINP/VINN, drains → VOUTN/VOUTP, sources → VTAIL) with horizontal
metal rails, vertical stubs, and vias — then searches the routing parameters
(rail width / pitch / via size) to minimize **wirelength + metal area** subject
to metal DRC (min width / spacing / via enclosure) and full connectivity.

Observed (fixed device geometry):

| | wirelength | metal area | DRC |
|---|---|---|---|
| loose default | 22.26 µm | 4.452 µm² | clean |
| optimized | 13.07 µm | 1.059 µm² | clean |
| | **−41%** | **−76%** | connectivity preserved |

Scope: this is a *structured* router for the diff pair's regular topology, not a
general maze/channel router. The DRC-clean optimum is analytically known
(via→floor, rail_width→max(min_width, via+2·enclosure), pitch→width+spacing), so
`test_routing.py` verifies the optimizer reaches it. Real routing parasitics
(PEX) would feed the same surrogate-assisted loop above.

## Joint device + routing co-optimization (`joint.py`)

`python run_joint_demo.py` searches the device geometry (5 params) and the
interconnect (3 params) **together**, minimizing the *full* routed-cell area
subject to device DRC + drive-spec + routing DRC + connectivity.

The point: optimizing the device alone ignores that rails stack above/below the
active area, so it underestimates the real cell.

| | area |
|---|---|
| device-only optimum | 2.101 µm² (interconnect ignored) |
| joint optimum, total cell | 2.790 µm² (device + routing) |
| | the real cell is **~33% larger** than the device-only estimate |

All 8 parameters converge to their DRC/spec floors, the result is DRC-clean on
both device and metal, drive-spec is met, and connectivity holds —
verified in `test_joint.py`.

## A harder circuit + autonomous algorithm study (`opamp*.py`)

`python run_opamp_experiments.py` sizes a **two-stage Miller-compensated OTA**
(8 parameters: W/L of M1/M3/M5/M6/M7, Itail, I6, Cc) — minimize power subject to
gain ≥ 80 dB, GBW ≥ 50 MHz, phase margin ≥ 65°, slew ≥ 50 V/us, and every device
in saturation. Only ~2.7% of the search box is feasible, so it is a genuinely
hard constrained problem. The study runs several optimizers across seeds, then
diagnoses and fixes the baseline's weakness:

| strategy | best | mean | std | note |
|---|---|---|---|---|
| random search | 0.846 mW | 1.04 | 0.123 | reference floor |
| DE, linear space (baseline) | 0.250 | 0.318 | 0.063 | high seed-to-seed variance |
| **DE, log space** | **0.101** | **0.113** | **0.009** | **2.8× lower power, 7× tighter** |
| DE log + SLSQP refine | 0.100 | 0.112 | 0.009 | marginal further gain |

**Diagnosed improvement points (found from the data, not assumed):**
1. Baseline DE beats random search but its per-seed power scatters widely.
   *Cause:* parameters span decades (I: 1 µA–1 mA, Cc: 0.1–10 pF), so
   linear-space DE mutations under-resolve the small-magnitude knobs.
2. **Fix — optimize in log space:** 2.8× lower mean power and 7× tighter
   variance. This is the dominant lever.
3. A local SLSQP polish on top adds only a marginal gain once log-space DE is
   used.

The found optimum sits exactly on the binding constraints (Vov, PM, gain at
their floors) — the signature of a correct min-power solution. The model
(`opamp.py`) is a documented square-law analytical surrogate; a real flow would
swap it for Spectre, leaving the optimizer experiments unchanged.

## Connecting a real PDK / Spectre (`spectre_backend.py`, `pdk.py`)

The Spectre backend swaps the analytical OTA model for a **real Spectre AC run**
driven through virtuoso-bridge, keeping the identical `OpAmpParams -> OpAmpSpecs`
contract (so the optimizer/surrogate/study code is unchanged). gain/GBW/PM come
from the AC sweep; power/slew/overdrives stay exact-given-sizing.

Connecting a process = filling one `PDKConfig` (`pdk.py`) — no code changes:

```python
from layout_opt.pdk import PDKConfig
MY_PDK = PDKConfig(
    name="tsmcN28",
    model_include='include "/pdk/models/spectre/toplevel.scs" section=tt',
    nmos="nch_mac", pmos="pch_mac", l_um=0.03, vdd=0.9,
)
```

Go-live steps:
1. `virtuoso-bridge init user@eda-server [-J jump]` then `virtuoso-bridge start`
   (SSH tunnel + Spectre); confirm with `virtuoso-bridge status` and
   `python -c "from layout_opt.spectre_backend import preflight; print(preflight())"`.
2. Evaluate one design against the PDK:
   `spectre_evaluate(params, MY_PDK)` → measured `OpAmpSpecs`.
3. Optimize with Spectre as ground truth: feed `make_spectre_objective(MY_PDK)`
   to the optimizer, and use `surrogate_opt.py` to keep Spectre calls few
   (the PoC shows ~600x fewer expensive evals).

The full pipeline (render → run → parse → specs) is verified offline against a
synthesized SimulationResult (`test_spectre_backend.py::…full_pipeline…`); only
the actual silicon-accurate run needs a licensed server + PDK. When not
connected, the backend raises `SpectreUnavailable` with actionable guidance.

Via Hermes, the agent drives this with `alo.py preflight` and
`alo.py spectre-eval [--model-include … --nmos … --pmos …]`.

## Going live later

When a Virtuoso server is reachable (e.g. a university EDA host via the bridge's
remote mode), replace the surrogate `evaluate()` with one that:
1. emits the layout (`emit_skill`) into `client.layout.edit(lib, cell)`,
2. invokes the PDK's DRC via `client.execute_skill(...)` and counts violations,
3. (optionally) extracts parasitics and runs Spectre for real performance,

and returns the same scalar. The generator, optimizer, and tests here are
unchanged.
