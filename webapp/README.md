# Web UI — visual analog layout optimizer

A React + Vite + TypeScript frontend over a FastAPI backend that reuses the
exact `layout_opt` engine. Shows the optimization **visually**, with no Virtuoso
anywhere in the loop.

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

**Backend** (port 8000):
```bash
# from repo root, with the venv that has layout_opt + fastapi installed
uv pip install -e ../virtuoso-bridge-lite fastapi "uvicorn[standard]" httpx numpy scipy
python -m uvicorn webapp.backend.main:app --port 8000
```

**Frontend** (port 5173, proxies /api -> 8000):
```bash
cd webapp/frontend
npm install
npm run dev
# open http://localhost:5173
```

## Architecture

```
 React UI  ──/api──►  FastAPI  ──►  layout_opt (generator + evaluate + optimize)
 (SVG, sliders,        (CORS,        the SAME pure-Python engine the offline
  animation, chart)     JSON)         tests use — no logic duplicated)
```

The backend's `evaluate` is the surrogate (area + geometric DRC + drive spec).
Swapping it for a Virtuoso/Spectre-backed evaluator changes only the backend —
the UI is unaffected.

## Verified

- `npm run build` — clean (tsc typecheck + vite build).
- Backend endpoints exercised via FastAPI TestClient.
- UI driven with Playwright: layout renders, sliders evaluate live, optimize
  animates 3.38 → 2.12 µm² across 51 frames, and a forced `w_finger=0.2`
  turns the OD shape red with the `W_total(spec)` rule listed.
