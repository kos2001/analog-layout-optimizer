"""Design-rule check (DRC) for routed nets.

The router gives geometry; DRC verifies it against manufacturing rules. On a
routing-track grid (adjacent tracks already include the metal spacing) the rules
that actually bite are:

  * short          two different nets on the same cell/layer (electrical short)
  * corner         different nets touching only diagonally (corner clearance)
  * via_spacing    vias of different nets closer than the via-to-via rule
  * open           a net that did not fully route (connectivity)
  * spacing        different nets on orthogonally adjacent tracks — only flagged
                   when min_spacing_tracks >= 1 (off by default: tracks already
                   carry spacing)

Input is the same per-net cell payload the routers emit, so DRC runs on any
result (maze / negotiated / multi-layer).
"""

from __future__ import annotations

from dataclasses import dataclass, field

Cell = tuple[int, int, int]      # (x, y, layer)
_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
_DIAG = ((1, 1), (1, -1), (-1, 1), (-1, -1))


@dataclass(frozen=True)
class DRCRules:
    min_spacing_tracks: int = 0       # >=1 flags orthogonally-adjacent diff nets
    check_corner: bool = True         # diagonal corner clearance
    min_via_spacing: int = 2          # Chebyshev distance required between diff-net vias
    check_via: bool = True


@dataclass
class Violation:
    rule: str
    nets: tuple
    cells: list                       # [[x,y,layer], ...] (1-2 cells)
    message: str


@dataclass
class DRCResult:
    clean: bool
    counts: dict
    violations: list
    checked_rules: list = field(default_factory=list)


def _norm(c) -> Cell:
    return (int(c[0]), int(c[1]), int(c[2]) if len(c) > 2 else 0)


def _vias(cells: set[Cell]) -> set[tuple[int, int]]:
    """(x,y) columns where this net occupies more than one layer (= a via)."""
    bylayer: dict[tuple[int, int], set[int]] = {}
    for (x, y, l) in cells:
        bylayer.setdefault((x, y), set()).add(l)
    return {xy for xy, ls in bylayer.items() if len(ls) > 1}


def check_routing(nets: dict, rules: DRCRules = DRCRules(), max_report: int = 300) -> DRCResult:
    """Run DRC on a per-net routing payload {net: {cells, routed}}."""
    # Occupancy: cell -> set of nets; and per-net cell sets.
    occ: dict[Cell, set] = {}
    cellsets: dict[str, set[Cell]] = {}
    opens = []
    for net, nr in nets.items():
        if not nr.get("routed", True):
            opens.append(net)
        cs = {_norm(c) for c in nr.get("cells", [])}
        cellsets[net] = cs
        for c in cs:
            occ.setdefault(c, set()).add(net)

    viol: list[Violation] = []
    counts = {"short": 0, "corner": 0, "via_spacing": 0, "open": len(opens), "spacing": 0}

    for net in opens:
        viol.append(Violation("open", (net,), [], f"net {net} did not route (open)"))

    # Shorts: a cell shared by >1 net.
    for c, ns in occ.items():
        if len(ns) > 1:
            counts["short"] += 1
            if len(viol) < max_report:
                viol.append(Violation("short", tuple(sorted(ns)), [list(c)],
                                      f"short: {'/'.join(sorted(ns))} overlap at {c}"))

    # Pairwise neighbour checks (corner clearance + optional orthogonal spacing).
    seen_pairs: set = set()
    for c, ns in occ.items():
        x, y, l = c
        net_c = next(iter(ns))
        if rules.min_spacing_tracks >= 1:
            for dx, dy in _ORTHO:
                n = (x + dx, y + dy, l)
                other = occ.get(n)
                if other and net_c not in other:
                    key = ("spacing", *sorted((c, n)))
                    if key not in seen_pairs:
                        seen_pairs.add(key)
                        counts["spacing"] += 1
                        if len(viol) < max_report:
                            viol.append(Violation("spacing", tuple(sorted(ns | other)),
                                                  [list(c), list(n)],
                                                  f"spacing < {rules.min_spacing_tracks+1} tracks at {c}"))
        if rules.check_corner:
            for dx, dy in _DIAG:
                n = (x + dx, y + dy, l)
                other = occ.get(n)
                if other and net_c not in other:
                    # not a violation if they are also orthogonally connected (same wire turn)
                    if (x + dx, y, l) in occ and net_c in occ[(x + dx, y, l)]:
                        continue
                    if (x, y + dy, l) in occ and net_c in occ[(x, y + dy, l)]:
                        continue
                    key = ("corner", *sorted((c, n)))
                    if key not in seen_pairs:
                        seen_pairs.add(key)
                        counts["corner"] += 1
                        if len(viol) < max_report:
                            viol.append(Violation("corner", tuple(sorted(ns | other)),
                                                  [list(c), list(n)],
                                                  f"corner clearance: {'/'.join(sorted(ns | other))} at {c}~{n}"))

    # Via-to-via spacing across nets.
    if rules.check_via:
        vias = {net: _vias(cs) for net, cs in cellsets.items()}
        items = [(net, xy) for net, xys in vias.items() for xy in xys]
        for i in range(len(items)):
            ni, (xi, yi) = items[i]
            for j in range(i + 1, len(items)):
                nj, (xj, yj) = items[j]
                if ni == nj:
                    continue
                if max(abs(xi - xj), abs(yi - yj)) < rules.min_via_spacing:
                    counts["via_spacing"] += 1
                    if len(viol) < max_report:
                        viol.append(Violation("via_spacing", tuple(sorted((ni, nj))),
                                              [[xi, yi], [xj, yj]],
                                              f"via spacing < {rules.min_via_spacing}: {ni}/{nj}"))

    total = sum(counts.values())
    checked = ["short", "corner", "via_spacing", "open"]
    if rules.min_spacing_tracks >= 1:
        checked.append("spacing")
    return DRCResult(clean=(total == 0), counts=counts,
                     violations=[v.__dict__ for v in viol], checked_rules=checked)


def payload(nets: dict, rules: DRCRules = DRCRules()) -> dict:
    r = check_routing(nets, rules)
    return {"clean": r.clean, "counts": r.counts, "total": sum(r.counts.values()),
            "violations": r.violations, "checkedRules": r.checked_rules}
