"""Process rules read from the foundry tech LEF, instead of typed in by hand.

Several modules carry SKY130 numbers as literals: metal min width/space
(`klayout_drc.METAL_RULES`), the EM current-density limits (`em.JMAX_PER_UM`),
the routed-geometry constants (`gds.TRACK_UM` / `VIA_UM` / `VIA_PAD_UM`) and the
wire R/C used for post-layout re-simulation (`parasitics.Tech`). An invented
design rule reads exactly like a measured one, so this module parses the real
tech LEF (ported from ppa-eda-agent's `design_rules.read_pdk_rules`) and

  * `read_tech_lef(path)`       every routing layer's direction, pitch, min width,
                                min spacing (plain SPACING or the first
                                SPACINGTABLE entry), min area, thickness, max
                                density, sheet resistance, DC current density and
                                capacitance; cut layers' size/spacing/R/enclosure;
                                the manufacturing grid.
  * `metal_rules(path)`         a `klayout_drc.METAL_RULES`-shaped dict built
                                from the LEF (the hardcoded table when no LEF).
  * `parasitic_tech(path)`      a `parasitics.Tech` whose wire R comes from the
                                LEF sheet resistance and via R (fallback: Tech()).
  * `compare_to_hardcoded(path)` every place a literal disagrees with the LEF.

Nothing here changes the hardcoded constants; callers opt in by passing the
LEF-derived values (e.g. `klayout_drc.run_drc(gds, rules=metal_rules())`).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_SCL = "sky130_fd_sc_hd"


class TechLefError(RuntimeError):
    """Raised rather than returning partial rules: a rule table that silently
    omits a layer is worse than one that fails to load."""


# --------------------------------------------------------------------------
# Locating and parsing
# --------------------------------------------------------------------------
def find_tech_lef(pdk_root: str | None = None, scl: str = DEFAULT_SCL,
                  corner: str = "nom") -> Path | None:
    """Locate `<scl>__<corner>.tlef` under a SKY130 PDK root, or None.

    Search order: `pdk_root`, $PDK_ROOT, ~/pdk (the same roots
    `ngspice_backend.sky130_lib_path` uses), each as `<root>/sky130A/...` and as
    a volare tree `<root>/volare/sky130/versions/*/sky130A/...`.
    """
    roots = [r for r in (pdk_root, os.environ.get("PDK_ROOT"),
                         os.path.expanduser("~/pdk")) if r]
    rel = Path("libs.ref") / scl / "techlef" / f"{scl}__{corner}.tlef"
    for root in roots:
        root = Path(root)
        cand = root / "sky130A" / rel
        if cand.is_file():
            return cand
        versions = root / "volare" / "sky130" / "versions"
        if versions.is_dir():
            for v in sorted(versions.iterdir()):
                cand = v / "sky130A" / rel
                if cand.is_file():
                    return cand
    return None


def _num(body: str, pattern: str) -> float | None:
    m = re.search(pattern, body, re.M)
    return float(m.group(1)) if m else None


_NUM = r"([-+]?[\d.]+(?:[eE][-+]?\d+)?)"


def read_tech_lef(path: str | Path) -> dict:
    """Parse the process rules of a tech LEF (units: um, ohm, pF, mA)."""
    path = Path(path)
    if not path.is_file():
        raise TechLefError(f"tech LEF not found: {path}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    # Strip comments: the SKY130 LEF keeps superseded rules as `# SPACING ...`.
    txt = re.sub(r"#[^\n]*", "", raw)

    grid = _num(txt, r"^\s*MANUFACTURINGGRID\s+([\d.]+)\s*;")
    dbu = _num(txt, r"^\s*DATABASE MICRONS\s+([\d.]+)\s*;")

    routing: dict[str, dict] = {}
    cut: dict[str, dict] = {}
    for m in re.finditer(r"^LAYER (\w+)\s*$(.*?)^END \1", txt, re.S | re.M):
        name, body = m.group(1), m.group(2)
        if re.search(r"TYPE\s+ROUTING", body):
            # Plain SPACING, else the first (narrowest-width) SPACINGTABLE entry;
            # both mean "minimum spacing".
            spacing = _num(body, r"^\s*SPACING\s+([\d.]+)\s*;")
            if spacing is None:
                st = re.search(r"SPACINGTABLE(.*?);", body, re.S)
                if st:
                    widths = re.findall(r"WIDTH\s+[\d.]+\s+([\d.]+)", st.group(1))
                    if widths:
                        spacing = float(widths[0])
            dm = re.search(r"^\s*DIRECTION\s+(\w+)\s*;", body, re.M)
            routing[name] = {
                "direction": dm.group(1).lower() if dm else None,
                "pitch_um": _num(body, r"^\s*PITCH\s+([\d.]+)\s*;"),
                "min_width_um": _num(body, r"^\s*WIDTH\s+([\d.]+)\s*;"),
                "min_spacing_um": spacing,
                "min_area_um2": _num(body, r"^\s*AREA\s+([\d.]+)\s*;"),
                "thickness_um": _num(body, r"^\s*THICKNESS\s+([\d.]+)\s*;"),
                "max_density_pct": _num(body, r"^\s*MAXIMUMDENSITY\s+([\d.]+)\s*;"),
                "resistance_ohm_per_sq": _num(
                    body, rf"^\s*RESISTANCE RPERSQ\s+{_NUM}\s*;"),
                "dc_current_ma_per_um": _num(
                    body, rf"^\s*DCCURRENTDENSITY AVERAGE\s+{_NUM}\s*;"),
                "cap_pf_per_um2": _num(
                    body, rf"^\s*CAPACITANCE CPERSQDIST\s+{_NUM}\s*;"),
                "edge_cap_pf_per_um": _num(
                    body, rf"^\s*EDGECAPACITANCE\s+{_NUM}\s*;"),
            }
        elif re.search(r"TYPE\s+CUT", body):
            enc = re.findall(r"^\s*ENCLOSURE\s+(BELOW|ABOVE)\s+([\d.]+)\s+([\d.]+)\s*;",
                             body, re.M)
            cut[name] = {
                "width_um": _num(body, r"^\s*WIDTH\s+([\d.]+)\s*;"),
                "spacing_um": _num(body, r"^\s*SPACING\s+([\d.]+)\s*;"),
                "resistance_ohm": _num(body, rf"^\s*RESISTANCE\s+{_NUM}\s*;"),
                "enclosure_um": {side.lower(): (float(a), float(b))
                                 for side, a, b in enc},
            }

    if not routing:
        raise TechLefError(f"{path}: no routing layers found")
    return {"source": str(path), "manufacturing_grid_um": grid,
            "database_units_per_um": dbu, "routing_layers": routing,
            "cut_layers": cut}


def _load(lef: str | Path | dict | None) -> dict | None:
    """Accept a parsed dict, a path, or None (auto-locate; None if absent)."""
    if isinstance(lef, dict):
        return lef
    if lef is None:
        found = find_tech_lef()
        return read_tech_lef(found) if found else None
    return read_tech_lef(lef)


# --------------------------------------------------------------------------
# LEF -> the values the rest of layout_opt uses
# --------------------------------------------------------------------------
def metal_rules(lef: str | Path | dict | None = None) -> dict:
    """`klayout_drc.METAL_RULES`-shaped rules from the LEF; hardcoded fallback.

    GDS layer numbers are not in a LEF, so they are taken from the hardcoded
    table; only layers present in both are emitted.
    """
    from .klayout_drc import METAL_RULES
    rules = _load(lef)
    if rules is None:
        return {k: dict(v) for k, v in METAL_RULES.items()}
    out = {}
    for name, spec in METAL_RULES.items():
        layer = rules["routing_layers"].get(name)
        if layer is None or layer["min_width_um"] is None or layer["min_spacing_um"] is None:
            raise TechLefError(f"{rules['source']}: no width/spacing for {name}")
        out[name] = {"gds": spec["gds"], "min_width": layer["min_width_um"],
                     "min_space": layer["min_spacing_um"]}
    return out


def em_limits(lef: str | Path | dict | None = None) -> dict[str, float]:
    """DC current-density limit (mA/um) per metal, from the LEF (Tj = 90 C);
    `em.JMAX_PER_UM` (illustrative, more conservative) as the fallback."""
    from .em import JMAX_PER_UM
    rules = _load(lef)
    if rules is None:
        return dict(JMAX_PER_UM)
    out = {}
    for name, fallback in JMAX_PER_UM.items():
        j = (rules["routing_layers"].get(name) or {}).get("dc_current_ma_per_um")
        out[name] = j if j is not None else fallback
    return out


def parasitic_tech(lef: str | Path | dict | None = None, layer: str = "met1",
                   via: str = "via", pitch_um: float | None = None,
                   track_um: float | None = None):
    """`parasitics.Tech` with wire R and C derived from the LEF.

    One routing-grid cell is a `track_um`-wide wire `pitch_um` long, so its
    resistance is RPERSQ * pitch/track and its ground capacitance is the area
    term (CPERSQDIST * pitch * track) plus both fringe edges
    (2 * EDGECAPACITANCE * pitch). Via R is the cut's RESISTANCE. Coupling is
    not in a LEF, so `c_couple_fF` keeps the hardcoded value. Returns Tech()
    unchanged when no LEF is available.
    """
    from .gds import PITCH_UM, TRACK_UM
    from .parasitics import Tech
    rules = _load(lef)
    fallback = Tech()
    if rules is None:
        return fallback
    pitch = PITCH_UM if pitch_um is None else pitch_um
    track = TRACK_UM if track_um is None else track_um
    m = rules["routing_layers"].get(layer) or {}
    v = rules["cut_layers"].get(via) or {}
    rsq, carea, cedge = (m.get("resistance_ohm_per_sq"), m.get("cap_pf_per_um2"),
                         m.get("edge_cap_pf_per_um"))
    r_cell = rsq * pitch / track if rsq is not None else fallback.r_per_cell
    c_cell = ((carea * pitch * track + 2.0 * cedge * pitch) * 1e3
              if carea is not None and cedge is not None else fallback.c_area_fF)
    r_via = v.get("resistance_ohm") or fallback.r_via
    return Tech(r_per_cell=r_cell, r_via=r_via, c_area_fF=c_cell,
                c_couple_fF=fallback.c_couple_fF)


def _on_grid(value: float, grid: float) -> bool:
    q = value / grid
    return abs(q - round(q)) < 1e-6


def compare_to_hardcoded(lef: str | Path | dict | None = None) -> list[dict]:
    """Every hardcoded SKY130 literal that disagrees with the tech LEF.

    Each entry: {"where", "item", "hardcoded", "lef", "severity", "note"}.
    severity "error" = the literal would produce illegal geometry or a DRC deck
    weaker than the foundry rule; "conservative" = stricter / more pessimistic
    than the LEF (safe, but not foundry-grounded). Empty list = all agree.
    """
    from .em import JMAX_PER_UM
    from .gds import PITCH_UM, TRACK_UM, VIA_PAD_UM, VIA_UM
    from .klayout_drc import METAL_RULES
    from .parasitics import Tech
    rules = _load(lef)
    if rules is None:
        raise TechLefError("no tech LEF found (set PDK_ROOT or pass a path)")
    rl, cl = rules["routing_layers"], rules["cut_layers"]
    out: list[dict] = []

    def add(where, item, hard, lefv, severity, note):
        out.append({"where": where, "item": item, "hardcoded": hard, "lef": lefv,
                    "severity": severity, "note": note})

    # 1. KLayout DRC deck: a smaller-than-LEF value lets violations through.
    for name, spec in METAL_RULES.items():
        layer = rl.get(name, {})
        for key, lkey in (("min_width", "min_width_um"), ("min_space", "min_spacing_um")):
            lv = layer.get(lkey)
            if lv is None or abs(spec[key] - lv) < 1e-9:
                continue
            add("klayout_drc.METAL_RULES", f"{name}.{key}", spec[key], lv,
                "error" if spec[key] < lv else "conservative",
                "DRC deck weaker than foundry rule" if spec[key] < lv
                else "DRC deck stricter than foundry rule")

    # 2. Routed geometry written to GDS (met1/met2, `via` cut).
    via = cl.get("via", {})
    for name in ("met1", "met2"):
        layer = rl.get(name, {})
        if layer.get("min_width_um") and TRACK_UM < layer["min_width_um"]:
            add("gds.TRACK_UM", f"{name} width", TRACK_UM, layer["min_width_um"],
                "error", "routed track narrower than min width")
        if layer.get("min_spacing_um") and PITCH_UM - TRACK_UM < layer["min_spacing_um"]:
            add("gds.PITCH_UM-TRACK_UM", f"{name} spacing", PITCH_UM - TRACK_UM,
                layer["min_spacing_um"], "error", "adjacent tracks closer than min spacing")
    if via.get("width_um") and abs(VIA_UM - via["width_um"]) > 1e-9:
        add("gds.VIA_UM", "via width", VIA_UM, via["width_um"], "error",
            "via cut must be the exact LEF size")
    enc = max((e[1] for e in via.get("enclosure_um", {}).values()), default=None)
    if enc is not None and (VIA_PAD_UM - VIA_UM) / 2 + 1e-9 < enc:
        add("gds.VIA_PAD_UM", "via enclosure", (VIA_PAD_UM - VIA_UM) / 2, enc,
            "error", "metal pad does not enclose the via cut")
    # Vias of different nets on adjacent cells (drc.DRCRules.min_via_spacing=1).
    if via.get("spacing_um") and PITCH_UM - VIA_UM < via["spacing_um"]:
        add("gds.PITCH_UM-VIA_UM", "via spacing", PITCH_UM - VIA_UM,
            via["spacing_um"], "error", "adjacent-cell vias closer than via spacing")
    m1_space = rl.get("met1", {}).get("min_spacing_um")
    if m1_space and PITCH_UM - VIA_PAD_UM < m1_space:
        add("gds.PITCH_UM-VIA_PAD_UM", "via pad spacing", PITCH_UM - VIA_PAD_UM,
            m1_space, "error", "adjacent-cell via pads closer than met1 spacing")
    grid = rules.get("manufacturing_grid_um")
    if grid:
        for nm, val in (("PITCH_UM", PITCH_UM), ("TRACK_UM", TRACK_UM),
                        ("VIA_UM", VIA_UM), ("VIA_PAD_UM", VIA_PAD_UM)):
            if not _on_grid(val, grid):
                add(f"gds.{nm}", "manufacturing grid", val, grid, "error",
                    "off the manufacturing grid")

    # 3. EM limits: lower than the LEF is conservative, higher is unsafe.
    for name, j in JMAX_PER_UM.items():
        lj = rl.get(name, {}).get("dc_current_ma_per_um")
        if lj is not None and abs(j - lj) > 1e-9:
            add("em.JMAX_PER_UM", name, j, lj,
                "error" if j > lj else "conservative",
                "EM limit above the foundry DC limit" if j > lj
                else "EM limit below the foundry DC limit (Tj=90C average)")

    # 4. Parasitic estimate per routed met1 cell.
    hard, lef_t = Tech(), parasitic_tech(rules)
    for field_, unit in (("r_per_cell", "ohm/cell"), ("r_via", "ohm"),
                         ("c_area_fF", "fF/cell")):
        hv, lv = getattr(hard, field_), getattr(lef_t, field_)
        if abs(hv - lv) > 0.05 * max(abs(lv), 1e-12):
            add("parasitics.Tech", f"{field_} ({unit})", hv, round(lv, 4),
                "conservative" if hv > lv else "error",
                f"hardcoded is {hv / lv:.2f}x the LEF-derived value"
                if lv else "LEF value is zero")
    return out
