# Web UI — visual analog layout optimizer

A React + Vite + TypeScript frontend over a FastAPI backend that reuses the
exact `layout_opt` engine. Shows the optimization **visually**. Offline tabs run without Virtuoso and are the default operating mode because no
EDA server is available. If real Cadence access is added later, it should go
through the Arcadia `virtuoso-bridge-lite` engine, not a second local bridge
implementation.

Features:
- **Layout render** — SVG of the differential pair, colored by layer
  (OD diffusion / PO poly / M1 guard ring / M2 routing / vias).
- **Parameter sliders** — drag W / L / pitch / gap / ring-width; the layout,
  area, and DRC status update live (debounced `/api/evaluate`).
- **Optimize device** — runs `scipy.differential_evolution` on the backend,
  streams per-generation frames, and plays them back so you watch the area
  shrink, with a convergence chart and a scrubber.
- **Joint (device+routing)** — `/api/joint` co-optimizes the device *and* the
  interconnect; the canvas renders the full routed cell (purple M2 rails/stubs,
  yellow vias) and reports total cell area vs. device-only area + wirelength.
- **DRC / spec highlight** — violating shapes turn red and the offending rules
  are listed (e.g. `W_total(spec): 0.8 < min 2`).

## Run

Two terminals.

**Backend** (port 8011):
```bash
# from repo root, with the venv that has layout_opt + fastapi installed
uv pip install -e ../virtuoso-bridge-lite fastapi "uvicorn[standard]" httpx numpy scipy scikit-learn
python -m uvicorn webapp.backend.main:app --port 8011
```

**Frontend** (port 5173, proxies /api -> 8011):
```bash
cd webapp/frontend
npm install
npm run dev
# open http://localhost:5173
```

## Architecture

```
 React UI  ──/api──►  FastAPI  ──►  layout_opt application layer
 (SVG, sliders,        (CORS,        generator + evaluate + optimize
  animation, chart)     JSON)        no frontend logic duplication
                              └──► Arcadia virtuoso-bridge-lite engine
                                   only if real Virtuoso/Spectre is enabled later
```

The backend's `evaluate` is the surrogate (area + geometric DRC + drive spec).
Swapping it for a Virtuoso/Spectre-backed evaluator changes only the backend and
should use Arcadia `VirtuosoClient` / `SpectreSimulator`; the UI is unaffected.

## Verified

- `npm run build` — clean (tsc typecheck + vite build).
- Backend endpoints exercised via FastAPI TestClient.
- UI driven with Playwright: layout renders, sliders evaluate live, optimize
  animates 3.38 → 2.12 µm² across 51 frames, and a forced `w_finger=0.2`
  turns the OD shape red with the `W_total(spec)` rule listed.
