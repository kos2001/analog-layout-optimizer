"""Real DRC on the exported GDS with the KLayout geometric engine.

This is the "heavy tool" step beyond the in-house grid DRC: KLayout's actual
C++ Region engine runs min-width and min-spacing checks on the met1/met2 metal
of the GDS, with SKY130 metal rules. It cross-validates the grid DRC — both flag
the corner/notch regions, now at true geometry.

Scope, honestly: this is **metal-layer geometric DRC**. Full device-level DRC
(poly/diff/well/contact rules) and **Netgen LVS** need a transistor-level layout
(real devices, contacts, wells) that this PoC's abstract router does not emit —
that is a separate layout-synthesis effort, not a check on this GDS.

Needs the `klayout` pip module (no PDK/GUI required).
"""

from __future__ import annotations

# SKY130 metal rules (microns): min width / min spacing.
METAL_RULES = {
    "met1": {"gds": (68, 20), "min_width": 0.14, "min_space": 0.14},
    "met2": {"gds": (69, 20), "min_width": 0.14, "min_space": 0.14},
    "met3": {"gds": (70, 20), "min_width": 0.30, "min_space": 0.30},
}


def klayout_available() -> bool:
    try:
        import klayout.db  # noqa: F401
        return True
    except ImportError:
        return False


def run_drc(gds_path: str, rules: dict = METAL_RULES, max_samples: int = 8) -> dict:
    """Run KLayout width/space DRC on the metal layers of a GDS file."""
    if not klayout_available():
        return {"available": False, "tool": "klayout",
                "error": "klayout pip module not installed (`pip install klayout`)."}

    import klayout.db as db
    ly = db.Layout()
    ly.read(gds_path)
    top = ly.top_cell()
    dbu = ly.dbu

    layers, total = [], 0
    for name, spec in rules.items():
        idx = ly.find_layer(spec["gds"][0], spec["gds"][1])
        region = db.Region(top.begin_shapes_rec(idx)) if idx is not None else db.Region()
        region.merge()
        wch = region.width_check(int(round(spec["min_width"] / dbu)))
        sch = region.space_check(int(round(spec["min_space"] / dbu)))

        def samples(edge_pairs):
            out = []
            for ep in edge_pairs.each():
                e = ep.first
                out.append([round(e.x1 * dbu, 3), round(e.y1 * dbu, 3)])
                if len(out) >= max_samples:
                    break
            return out

        w_n, s_n = wch.size(), sch.size()
        total += w_n + s_n
        layers.append({
            "layer": name, "gds": list(spec["gds"]), "polygons": region.size(),
            "min_width_um": spec["min_width"], "min_space_um": spec["min_space"],
            "width_violations": w_n, "space_violations": s_n,
            "samples": (samples(wch) + samples(sch))[:max_samples],
        })

    return {"available": True, "tool": f"KLayout {db.__version__ if hasattr(db, '__version__') else ''}".strip(),
            "clean": total == 0, "total": total, "layers": layers}


def run_drc_on_flow(flow: dict, rules: dict = METAL_RULES) -> dict:
    """Export a flow to a temp GDS and DRC it with KLayout."""
    import os
    import tempfile
    from .gds import flow_to_gds
    fd, path = tempfile.mkstemp(suffix=".gds")
    os.close(fd)
    try:
        run_drc.__doc__  # keep import side-effect-free
        flow_to_gds(flow, path)
        return run_drc(path, rules)
    finally:
        os.unlink(path)
