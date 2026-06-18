"""Ground-truth post-layout performance model.

STAND-IN: with no Virtuoso/Spectre/PEX available, this function plays the role
of the *expensive* ground-truth evaluator. In a real flow it would be:
    emit layout -> run PDK DRC -> extract parasitics (PEX) -> Spectre AC sim
    -> read a figure of merit.
Here it is a closed-form but deliberately non-trivial function of geometry,
representing a gain-bandwidth-like FoM that is degraded by layout parasitics.

The key properties that make it a meaningful surrogate target:
  * it depends on geometry through *parasitics* (diffusion/gate/guard-ring
    capacitance), which the cheap geometric evaluator (area only) cannot see;
  * it is nonlinear and has an interior trade-off (wider fingers raise gm but
    also raise junction cap and area), so the optimum is not at a bound;
  * it is unknown to the optimizer - it must be *learned* from samples.

It is intentionally NOT exposed to the optimizer directly; the surrogate is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .generator import DesignParams, DiffPairConfig, generate_layout


_K_GAIN = 10.0       # overall FoM scale (arbitrary but fixed units)


@dataclass
class Performance:
    fom: float       # gain-like figure of merit (higher is better)
    area: float      # bbox area (same as geometric evaluator)
    gain: float      # intrinsic gain proxy (diagnostic)
    load: float      # parasitic loading factor (diagnostic)


def truth_performance(p: DesignParams, cfg: DiffPairConfig | None = None) -> Performance:
    """Expensive ground-truth evaluation (stand-in for Spectre+PEX).

    The FoM is a small-signal gain proxy gm*ro: gm ~ sqrt(W/L) and ro ~ L give
    gain ~ sqrt(W_total * L). It therefore *rewards* larger total width and
    longer channel - which cost area - so meeting a gain target fights the
    area minimizer. Layout parasitics (poly pitch, guard-ring gap add routing
    and junction loading) divide the gain down.
    """
    cfg = cfg or DiffPairConfig()

    w_total = cfg.nf * p.w_finger
    gain = math.sqrt(w_total * p.l)                      # gm*ro proxy

    # Parasitic loading from layout: wider spacing => more routing/junction cap.
    load = (
        1.0
        + 0.5 * (p.finger_pitch + p.guard_gap)
        + 0.15 * math.tanh((p.finger_pitch - 0.30) * 3.0)  # mild nonlinearity
    )

    bbox_area = generate_layout(p, cfg).bbox_area()
    fom = _K_GAIN * gain / load
    return Performance(fom=fom, area=bbox_area, gain=gain, load=load)


def truth_fom(p: DesignParams, cfg: DiffPairConfig | None = None) -> float:
    """Scalar ground-truth FoM (the quantity the surrogate learns)."""
    return truth_performance(p, cfg).fom
