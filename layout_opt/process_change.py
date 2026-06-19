"""Process-change adaptation: natural language -> re-optimized placement+routing.

When the PDK/process changes, the **schematic is fixed** (same differential-pair
topology, same nets, same finger count) but the **placement (device geometry)
and routing must change** to satisfy the new DRC rules and any new drive spec.

This module:
  * `ProcessOverrides` — the new rule/spec values (everything optional).
  * `parse_process_nl(text)` — deterministic extractor for common phrasings
    (e.g. "min poly pitch 0.3 um, metal spacing 0.12, drive 3 mA total"),
    plus a few node presets. The Hermes agent can instead fill overrides itself.
  * `adapt(overrides)` — rebuild PDKRules/RoutingRules/DiffPairConfig (topology
    unchanged) and re-run the joint device+routing optimization, returning a
    before/after comparison.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field

from .generator import DiffPairConfig, PDKRules
from .joint import optimize_joint
from .routing import RoutingRules

# key -> (which object, field). One flat namespace for overrides.
_KEY_MAP = {
    "min_l": ("rules", "min_l"),
    "min_w": ("rules", "min_w"),
    "min_poly_pitch": ("rules", "min_poly_pitch"),
    "min_gr_gap": ("rules", "min_gr_gap"),
    "min_gr_width": ("rules", "min_gr_width"),
    "min_m_width": ("rrules", "min_m_width"),
    "min_m_spacing": ("rrules", "min_m_spacing"),
    "min_via": ("rrules", "min_via"),
    "min_via_enclosure": ("rrules", "min_via_enclosure"),
    "w_min_total": ("cfg", "w_min_total"),
}


@dataclass
class ProcessOverrides:
    values: dict = field(default_factory=dict)   # subset of _KEY_MAP keys -> float

    def is_empty(self) -> bool:
        return not self.values


def apply_overrides(ov: ProcessOverrides):
    """Return (cfg, rules, rrules) with overrides applied; topology untouched."""
    cfg, rules, rrules = DiffPairConfig(), PDKRules(), RoutingRules()
    patch = {"cfg": {}, "rules": {}, "rrules": {}}
    for k, v in ov.values.items():
        if k not in _KEY_MAP:
            raise KeyError(f"unknown override {k!r}")
        obj, fieldname = _KEY_MAP[k]
        patch[obj][fieldname] = float(v)
    cfg = dataclasses.replace(cfg, **patch["cfg"])
    rules = dataclasses.replace(rules, **patch["rules"])
    rrules = dataclasses.replace(rrules, **patch["rrules"])
    return cfg, rules, rrules


# --- natural-language parsing ----------------------------------------------
# Phrase fragments -> override key. Order matters (more specific first).
_NL_PATTERNS = [
    (r"poly\s*pitch|min(?:imum)?\s*poly", "min_poly_pitch"),
    (r"gate\s*length|min(?:imum)?\s*l\b|channel\s*length", "min_l"),
    (r"finger\s*width|min(?:imum)?\s*w\b|device\s*width", "min_w"),
    (r"guard[-\s]*ring\s*gap|guard\s*gap", "min_gr_gap"),
    (r"guard[-\s]*ring\s*width", "min_gr_width"),
    (r"metal\s*spacing|min(?:imum)?\s*spacing|m\d?\s*spacing", "min_m_spacing"),
    (r"metal\s*width|rail\s*width|m\d?\s*width", "min_m_width"),
    (r"via\s*enclosure|enclosure", "min_via_enclosure"),
    (r"via\s*size|min(?:imum)?\s*via", "min_via"),
    (r"drive|total\s*width|tail\s*current|w_?total", "w_min_total"),
]

_NUM = r"([0-9]*\.?[0-9]+)\s*(nm|um|µm|u|mm|ma|ua|a|m|n)?"


def _to_um(val: float, unit: str | None) -> float:
    u = (unit or "um").lower()
    if u in ("nm", "n"):
        return val * 1e-3
    if u in ("mm",):
        return val * 1e3
    return val            # um / u / µm / unitless -> microns


def parse_process_nl(text: str) -> ProcessOverrides:
    """Extract DRC/spec overrides from a natural-language process description.

    Numbers are read in microns by default (nm/mm/um understood). The drive
    spec (w_min_total) is unitless (total W/L sum target). Best-effort: only
    clearly-stated values are captured; the agent path can be more flexible.
    """
    t = text.lower()
    out: dict[str, float] = {}
    for frag, key in _NL_PATTERNS:
        # find the phrase, then the first number after it (within ~30 chars)
        for m in re.finditer(frag, t):
            tail = t[m.end(): m.end() + 30]
            nm = re.search(_NUM, tail)
            if not nm:
                continue
            val = float(nm.group(1))
            unit = nm.group(2)
            if key == "w_min_total":
                out[key] = val           # unitless drive target
            else:
                out[key] = _to_um(val, unit)
            break
    return ProcessOverrides(values=out)


# --- adaptation -------------------------------------------------------------
@dataclass
class AdaptResult:
    overrides: dict
    before: dict
    after: dict
    topology_fixed: dict   # the invariant schematic facts

    @property
    def area_delta_pct(self) -> float:
        b = self.before["total_area_um2"]
        return 100.0 * (self.after["total_area_um2"] - b) / b if b else 0.0


def _joint_summary(cfg, rules, rrules, seed, maxiter) -> dict:
    j = optimize_joint(cfg=cfg, rules=rules, rrules=rrules, seed=seed, maxiter=maxiter)
    return {
        "total_area_um2": round(j.total_area, 4),
        "device_area_um2": round(j.device_area, 4),
        "wirelength_um": round(j.wirelength, 3),
        "drc_clean": j.is_clean,
        "device": {k: round(v, 4) for k, v in zip(j.device.ORDER, j.device.to_vector())},
        "routing": {k: round(v, 4) for k, v in zip(j.routing.ORDER, j.routing.to_vector())},
    }


def adapt(overrides: ProcessOverrides, *, seed: int = 0, maxiter: int = 150) -> AdaptResult:
    """Re-optimize placement+routing for the new process; schematic fixed."""
    base_cfg, base_rules, base_rrules = DiffPairConfig(), PDKRules(), RoutingRules()
    new_cfg, new_rules, new_rrules = apply_overrides(overrides)
    before = _joint_summary(base_cfg, base_rules, base_rrules, seed, maxiter)
    after = _joint_summary(new_cfg, new_rules, new_rrules, seed, maxiter)
    return AdaptResult(
        overrides=dict(overrides.values),
        before=before,
        after=after,
        topology_fixed={
            "nf": new_cfg.nf,
            "total_fingers": 2 * new_cfg.nf,
            "nets": ["VINP", "VINN", "VOUTN", "VOUTP", "VTAIL"],
            "note": "schematic/topology unchanged; only geometry + routing re-optimized",
        },
    )
