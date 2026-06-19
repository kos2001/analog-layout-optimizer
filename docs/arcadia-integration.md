# Arcadia virtuoso-bridge-lite Integration

This project runs **offline-first** as the analog optimization/application layer. Arcadia `virtuoso-bridge-lite` is kept as the optional Cadence runtime engine for a future live Virtuoso/Spectre environment. There is currently no EDA server, and that is a supported/default state.

## Verified sources

- Arcadia clone: `/Users/kos2001/gitspace/virtuoso-bridge-lite`
  - HEAD at evaluation time: `c1084ff docs: clarify optimizer workflow backends`
  - GitHub: https://github.com/Arcadia-1/virtuoso-bridge-lite
- This repo: `/Users/kos2001/gitspace/virtuso_bridge/layout_opt_poc`
  - GitHub: https://github.com/kos2001/analog-layout-optimizer

## Boundary

Keep here:

- analog problem models
- geometry/routing generators
- optimizer and surrogate-assisted loops
- PDK-specific configs and netlist templates
- FastAPI/React UI
- Hermes workflow wrappers

Delegate to Arcadia:

- `VirtuosoClient` SKILL transport
- SSH/jump-host/local bridge lifecycle
- `.il` loading and inline `eval`
- `SpectreSimulator` invocation
- PSF parsing
- Maestro snapshot/readback
- X11/window diagnostics

## Operating model

Current/default mode:

```text
Hermes Agent / Web UI / FastAPI
        -> analog-layout-optimizer application layer
        -> offline analytical/surrogate evaluators
        -> no EDA server required
```

Optional future live mode:

```text
Hermes Agent / Web UI / FastAPI
        -> analog-layout-optimizer application layer
        -> Arcadia virtuoso-bridge-lite engine
        -> remote/local Cadence Virtuoso + Spectre + PDK
```

## Development setup

```bash
cd /Users/kos2001/gitspace/virtuoso-bridge-lite
uv venv .venv
source .venv/bin/activate
uv pip install -e . pytest numpy scipy scikit-learn fastapi "uvicorn[standard]" httpx

cd /Users/kos2001/gitspace/virtuso_bridge/layout_opt_poc
python hermes/analog-layout-optimizer/scripts/alo.py bridge-smoke
python verify_bridge.py
python -m pytest -q
```

## Optional future real Cadence smoke path

Skip this today: there is no EDA server. Run it only after the user configures a real EDA target:

```bash
virtuoso-bridge init user@eda-host [-J user@jump-host]
virtuoso-bridge start
virtuoso-bridge status
python hermes/analog-layout-optimizer/scripts/alo.py bridge-smoke --live
python hermes/analog-layout-optimizer/scripts/alo.py preflight
```

Expected live bridge result: `execute_skill("1+2")` returns `3` through `VirtuosoClient`. Until a server exists, `bridge-smoke --live` reporting `not_configured_optional` is normal, not a blocker.

## Risk notes

- Pin Arcadia version/commit before productionizing; the local clone currently reports package version `0.7.0`.
- `~/.local/bin/virtuoso-bridge` may point to a Hermes profile wrapper on this machine, not the Arcadia CLI. Use the venv CLI at `/Users/kos2001/gitspace/virtuoso-bridge-lite/.venv/bin/virtuoso-bridge` or run through the venv Python.
- `~/.virtuoso-bridge/.env` is absent until `virtuoso-bridge init` is run. This is normal in the current no-EDA-server setup; offline tests do not require it.
- PDK model/include/device names remain project/customer-specific and belong in `PDKConfig`.
