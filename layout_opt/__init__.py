"""Virtuoso-free analog layout geometry optimization PoC.

This package demonstrates the parts of an analog layout-optimization flow that
can be developed and *verified without a running Cadence Virtuoso* instance:

  * ``geometry``  - pure-Python geometric primitives (no Virtuoso).
  * ``generator`` - parameterized differential-pair layout builder (no Virtuoso).
  * ``skill``     - emit the layout as real SKILL via virtuoso_bridge's pure
                    string-builder functions (the only Virtuoso-bound step is
                    *executing* these strings, which is deferred).
  * ``evaluate``  - a surrogate objective (area + DRC/spec penalties) computed
                    entirely in Python; swappable for a Virtuoso/Spectre backend.
  * ``optimize``  - black-box optimization over the surrogate.

The Virtuoso-only concern (does the emitted SKILL produce DRC-clean geometry in
the real PDK, post-layout parasitics, etc.) is intentionally *not* modeled here.
"""

from .geometry import Rect, Layout
from .generator import DiffPairConfig, DesignParams, generate_layout, PDKRules
from .evaluate import evaluate, EvalResult, make_objective
try:
    # emit_skill needs virtuoso_bridge (Cadence SKILL layout ops); keep it
    # OPTIONAL so the offline algorithms import and run without the Arcadia bridge
    from .skill import emit_skill
except Exception:  # pragma: no cover - optional Cadence-side dependency
    emit_skill = None

__all__ = [
    "Rect",
    "Layout",
    "DiffPairConfig",
    "DesignParams",
    "PDKRules",
    "generate_layout",
    "evaluate",
    "EvalResult",
    "make_objective",
    "emit_skill",
]
