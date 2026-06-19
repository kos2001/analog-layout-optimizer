# Analog Layout Optimization PoC — *without* Virtuoso

A working, fully-tested proof of concept for **layout geometric-parameter
optimization** that runs and verifies entirely **offline** — no running Cadence
Virtuoso, no PDK, no license needed. It demonstrates exactly which layers of an
analog layout-optimization flow can be built and validated before any EDA tool
is in the loop, using `virtuoso-bridge-lite`'s pure SKILL builders.

## Recommended architecture

This repo is the **analog optimization application layer**. Arcadia
[`virtuoso-bridge-lite`](https://github.com/Arcadia-1/virtuoso-bridge-lite) is
the **Cadence runtime engine** underneath it.

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
Remote/local Cadence Virtuoso + Spectre + PDK
```

Boundary: keep design objectives, candidate generation, surrogate logic, UI, and
customer-specific PDK configuration in this repo. Delegate SKILL transport,
daemon/tunnel lifecycle, Spectre invocation, PSF parsing, and Virtuoso/Maestro
diagnostics to `virtuoso-bridge-lite`. In other words, do not grow a second
bridge here; treat Arcadia as the pinned engine and build workflow/product value
above it. See `docs/arcadia-integration.md` for the operating checklist.

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

## What is deferred to Virtuoso (cannot be faked offline)

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

python -m pytest -q          # 19 tests, all offline
python run_demo.py           # end-to-end: optimize → report → emit SKILL
```

Arcadia engine smoke checks:

```bash
python verify_bridge.py
python hermes/analog-layout-optimizer/scripts/alo.py bridge-smoke
# once a real bridge is configured and started:
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
