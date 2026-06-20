"""Physical-verification sign-off: DRC + LVS + connectivity → tape-out verdict.

Sign-off is the gate before tape-out. Here it runs three checks on the routed
design and returns a pass/fail with a violation list:

  * DRC   geometry vs manufacturing rules (see drc.py)
  * LVS   does the *layout* connect the same nodes as the *schematic*?
          We extract electrical nodes from the routed metal (union-find over
          connected cells + vias), map each device terminal to a node, and
          compare against the schematic netlist:
            - net split across >1 node      -> OPEN
            - >1 schematic net on one node  -> SHORT (nets merged)
  * connectivity   every net fully routed (no unrouted opens)

Errors (shorts, opens, via spacing, LVS mismatches) block sign-off; corner /
spacing issues are warnings. This is what makes the schematic↔layout loop real:
the netlist that drove placement & routing is the golden reference LVS checks.
"""

from __future__ import annotations

from .drc import DRCRules, payload as drc_payload

Cell = tuple[int, int, int]
_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))

ERROR_RULES = {"short", "open", "via_spacing"}     # block sign-off
WARN_RULES = {"corner", "spacing"}                 # advisory


class _UF:
    def __init__(self):
        self.p: dict = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def _components(cells: set[Cell]) -> _UF:
    """Union-find connected metal within one net (adjacency + via)."""
    uf = _UF()
    for (x, y, l) in cells:
        uf.find((x, y, l))
        for dx, dy in _ORTHO:
            if (x + dx, y + dy, l) in cells:
                uf.union((x, y, l), (x + dx, y + dy, l))
        if (x, y, l + 1) in cells:
            uf.union((x, y, l), (x, y, l + 1))
    return uf


def lvs(pins: list[dict], routing_nets: dict) -> dict:
    """Compare layout connectivity with the schematic netlist (track-grid model).

    Each net's own metal is one node; LVS verifies (a) every terminal of a
    schematic net lands on one connected component of that net's metal (else
    OPEN), and (b) no cell carries two nets (else SHORT).

    pins: [{"id": "M3.D#0", "net": "n1", "cell": [x, y]}]  (one per terminal)
    """
    occ: dict[Cell, set] = {}
    net_cells: dict[str, set[Cell]] = {}
    for net, nr in routing_nets.items():
        cs = {(int(c[0]), int(c[1]), int(c[2]) if len(c) > 2 else 0) for c in nr.get("cells", [])}
        net_cells[net] = cs
        for c in cs:
            occ.setdefault(c, set()).add(net)

    # SHORT: a cell shared by more than one net (metal of two nets overlaps).
    shorts, seen = [], set()
    for c, ns in occ.items():
        if len(ns) > 1:
            key = tuple(sorted(ns))
            if key not in seen:
                seen.add(key)
                shorts.append({"nets": list(key)})

    # OPEN: a net whose terminals don't all land on one connected component.
    pins_by_net: dict[str, list] = {}
    for p in pins:
        pins_by_net.setdefault(p["net"], []).append(p)
    opens, floating = [], []
    for net, ps in pins_by_net.items():
        cs = net_cells.get(net, set())
        uf = _components(cs)
        roots = set()
        for p in ps:
            c = (int(p["cell"][0]), int(p["cell"][1]), 0)
            if c not in cs:
                floating.append(p["id"])
            else:
                roots.add(uf.find(c))
        if len(roots) > 1:
            opens.append({"net": net, "components": len(roots)})

    clean = not shorts and not opens and not floating
    return {"clean": clean, "opens": opens, "shorts": shorts,
            "floating": floating,
            "nDevicesChecked": len({p["id"].split(".")[0] for p in pins}),
            "nSchematicNets": len(pins_by_net), "nLayoutNodes": len(net_cells)}


def run_signoff(pins: list[dict], routing: dict, rules: DRCRules = DRCRules()) -> dict:
    """Full sign-off: DRC + LVS + connectivity -> verdict + checklist."""
    drc = drc_payload(routing["nets"], rules)
    lvs_r = lvs(pins, routing["nets"])
    failed = routing.get("failed", [])

    drc_errors = sum(drc["counts"].get(r, 0) for r in ERROR_RULES)
    drc_warns = sum(drc["counts"].get(r, 0) for r in WARN_RULES)

    checks = [
        {"name": "Connectivity", "status": "pass" if not failed else "fail",
         "detail": "all nets routed" if not failed else f"{len(failed)} unrouted: {', '.join(failed)}"},
        {"name": "LVS", "status": "pass" if lvs_r["clean"] else "fail",
         "detail": (f"layout matches schematic ({lvs_r['nSchematicNets']} nets, "
                    f"{lvs_r['nDevicesChecked']} devices)") if lvs_r["clean"]
                   else f"{len(lvs_r['shorts'])} short(s), {len(lvs_r['opens'])} open(s)"},
        {"name": "DRC", "status": "pass" if drc_errors == 0 else "fail",
         "detail": (f"{drc_errors} error(s), {drc_warns} warning(s)" if drc_errors
                    else f"no errors, {drc_warns} warning(s)")},
    ]
    errors = drc_errors + (len(failed) > 0) + (0 if lvs_r["clean"] else 1)
    verdict = "PASS" if all(c["status"] == "pass" for c in checks) else "FAIL"
    return {"verdict": verdict, "checks": checks, "drc": drc, "lvs": lvs_r,
            "drcErrors": drc_errors, "drcWarnings": drc_warns}
