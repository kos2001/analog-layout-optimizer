"""Post-placement polish: measured single moves, kept only if sign-off holds.

Simulated annealing optimizes a *proxy* (HPWL + overlap, plus matching and
critical-net terms when analog-aware). What the design is judged on comes
later: the routed wirelength and via count, the advisory DRC warnings, and the
post-layout phase margin after parasitic extraction. A placement that is
optimal for the proxy is usually one or two cell moves away from a better
routed result. This phase (ported from ppa-eda-agent's `pnr_polish`) tries
those moves *through the real flow* and keeps a move only when

  * the trial still signs off (DRC errors / LVS / connectivity all PASS);
  * no objective is worse than the incumbent beyond TOLERANCE_PCT, and none has
    drifted beyond TOLERANCE_PCT from the *original* placement either, so
    repeated small concessions cannot accumulate across rounds;
  * at least one cost objective (GAIN_OBJECTIVES) improves by >= GAIN_PCT.

Accepted single moves are ranked by the knee of their objectives
(`ppa.knee_index`); then the accepted moves that touch disjoint devices are
combined and tried once — moves interact, so the combination must earn its
place against the best single move. Each round starts from the new incumbent.

The flow is deterministic (same placement -> same route), so a measured gain is
a fact about that placement, not noise; tolerances only allow trading a
negligible secondary loss for a material primary gain.

Moves: unit shifts of one device, a horizontal mirror (pins flipped left/right),
swaps of same-footprint devices, and pair-preserving moves for matched pairs
(shift together, spread/squeeze about the pair centroid, mirror both).
`placement.py` is only *called* (route_placement, matching_metrics); its SA is
unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import parasitics as _par
from . import signoff as _signoff
from .interactive import Component, Pin
from .placement import (
    H, MATCHED_PAIRS, W, matching_metrics, route_placement,
)
from .ppa import knee_index
from .schematic import CORE_NAMES, Schematic, two_stage_ota

# Objectives, all minimized. pm_loss = pre-layout PM - post-layout PM (deg).
# symmetry / pair_distance are the matching terms (placement.matching_metrics):
# polish may improve them but never trades them away for routing.
OBJECTIVES = ("wirelength", "vias", "pm_loss", "drc_warnings", "symmetry",
              "pair_distance")

# Allowed relative worsening per objective (percent). Zero = must not get worse.
TOLERANCE_PCT = {"wirelength": 2.0, "vias": 0.0, "pm_loss": 2.0,
                 "drc_warnings": 0.0, "symmetry": 0.0, "pair_distance": 0.0}

# A move must buy at least this much on a cost objective to be kept.
GAIN_PCT = 3.0
GAIN_OBJECTIVES = ("wirelength", "vias", "pm_loss")

_SHIFTS = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class Layout:
    """A placement state: positions + per-device horizontal mirror flags."""
    pos: dict[str, tuple[int, int]]
    mirror: dict[str, bool] = field(default_factory=dict)


@dataclass
class Trial:
    layout: Layout
    flow: dict
    objectives: dict[str, float]
    move: str = "incumbent"
    devices: frozenset = frozenset()

    @property
    def signs_off(self) -> bool:
        return self.flow["signoff"]["verdict"] == "PASS"


# --------------------------------------------------------------------------
# Evaluation through the real flow
# --------------------------------------------------------------------------
def _components(sch: Schematic, lay: Layout) -> list[Component]:
    comps = sch.to_components(lay.pos)
    out = []
    for c in comps:
        if lay.mirror.get(c.id):
            pins = [Pin(p.net, c.w - 1 - p.dx, p.dy) for p in c.pins]
            c = Component(id=c.id, label=c.label, x=c.x, y=c.y, w=c.w, h=c.h, pins=pins)
        out.append(c)
    return out


def _hpwl(comps: list[Component]) -> int:
    nets: dict[str, list[tuple[int, int]]] = {}
    for c in comps:
        for net, cell in c.abs_pins():
            nets.setdefault(net, []).append(cell)
    total = 0
    for cells in nets.values():
        if len(cells) >= 2:
            xs = [x for x, _ in cells]; ys = [y for _, y in cells]
            total += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return total


def evaluate_layout(sch: Schematic, lay: Layout, sizing=None) -> dict:
    """Route + sign-off + post-layout for one placement (run_flow's payload)."""
    comps = _components(sch, lay)
    routing = route_placement(comps)
    lvs_pins = [{"id": f"{c.id}.{net}#{i}", "net": net, "cell": list(cell)}
                for c in comps for i, (net, cell) in enumerate(c.abs_pins())]
    signoff = _signoff.run_signoff(lvs_pins, routing)
    postlayout = (_par.post_layout_from_routing(routing, p=sizing)
                  if sizing is not None else _par.post_layout_from_routing(routing))
    kinds = {d.name: d.kind for d in sch.devices}
    return {
        "width": W, "height": H, "layers": 2,
        "hpwl": _hpwl(comps),
        "netlist": {net: [f"{d}.{t}" for d, t in conns]
                    for net, conns in sch.nets().items()},
        "components": [{"id": c.id, "label": c.label, "x": c.x, "y": c.y,
                        "w": c.w, "h": c.h, "kind": kinds[c.id],
                        "mirror": bool(lay.mirror.get(c.id)),
                        "pins": [{"net": p.net, "dx": p.dx, "dy": p.dy} for p in c.pins]}
                       for c in comps],
        "routing": routing, "signoff": signoff, "postlayout": postlayout,
        "matching": matching_metrics(sch, lay.pos),
    }


def objectives(flow: dict) -> dict[str, float]:
    pl = flow["postlayout"]
    return {"wirelength": float(flow["routing"]["totalWirelength"]),
            "vias": float(flow["routing"]["totalVias"]),
            "pm_loss": float(pl["pre"]["pm_deg"] - pl["post"]["pm_deg"]),
            "drc_warnings": float(flow["signoff"]["drcWarnings"]),
            "symmetry": float(flow["matching"]["symmetry_penalty"]),
            "pair_distance": float(sum(flow["matching"]["pair_distance"].values()))}


def _trial(sch, lay, sizing, move="incumbent", devices=frozenset()) -> Trial:
    flow = evaluate_layout(sch, lay, sizing)
    return Trial(layout=lay, flow=flow, objectives=objectives(flow),
                 move=move, devices=frozenset(devices))


# --------------------------------------------------------------------------
# Acceptance
# --------------------------------------------------------------------------
def _rel_pct(trial: float, ref: float) -> float:
    return (trial - ref) / max(abs(ref), 1e-12) * 100.0


def within_tolerance(ref: dict, trial: dict) -> bool:
    return all(_rel_pct(trial[k], ref[k]) <= TOLERANCE_PCT[k] + 1e-9 for k in OBJECTIVES)


def improves(incumbent: Trial, trial: Trial, original: Trial | None = None) -> bool:
    """Signs off, no objective worse beyond tolerance (vs the incumbent and the
    original), and a cost objective better by >= GAIN_PCT."""
    if not trial.signs_off:
        return False
    if not within_tolerance(incumbent.objectives, trial.objectives):
        return False
    if original is not None and not within_tolerance(original.objectives, trial.objectives):
        return False
    return any(_rel_pct(trial.objectives[k], incumbent.objectives[k]) <= -GAIN_PCT
               for k in GAIN_OBJECTIVES)


# --------------------------------------------------------------------------
# Moves
# --------------------------------------------------------------------------
Move = tuple[str, frozenset, Callable[[Layout], Layout]]


def _legal(sch: Schematic, lay: Layout, margin: int = 1) -> bool:
    """Inside the grid (1-cell edge ring kept for routing) and no core-device
    footprint overlap (with `margin` free cells) — cheap pre-filter only; the
    flow's sign-off is what decides."""
    wh = {d.name: (d.w, d.h) for d in sch.devices}
    boxes = []
    for n in CORE_NAMES:
        x, y = lay.pos[n]
        w, h = wh[n]
        if x < 1 or y < 1 or x + w > W - 1 or y + h > H - 1:
            return False
        boxes.append((x, y, w, h))
    for i in range(len(boxes)):
        xi, yi, wi, hi = boxes[i]
        for j in range(i + 1, len(boxes)):
            xj, yj, wj, hj = boxes[j]
            if (min(xi + wi + margin, xj + wj + margin) - max(xi, xj) > 0 and
                    min(yi + hi + margin, yj + hj + margin) - max(yi, yj) > 0):
                return False
    return True


def _with(lay: Layout, pos=None, mirror=None) -> Layout:
    p = dict(lay.pos); p.update(pos or {})
    m = dict(lay.mirror); m.update(mirror or {})
    return Layout(pos=p, mirror=m)


def candidate_moves(sch: Schematic, lay: Layout) -> list[Move]:
    """Deterministic list of (name, devices touched, apply) for this layout."""
    moves: list[Move] = []
    paired = {d for pr in MATCHED_PAIRS for d in pr}
    kinds = {d.name: d.kind for d in sch.devices}

    def shift(n, dx, dy):
        return lambda L: _with(L, pos={n: (L.pos[n][0] + dx, L.pos[n][1] + dy)})

    for n in CORE_NAMES:
        for dx, dy in _SHIFTS:
            moves.append((f"shift {n} ({dx:+d},{dy:+d})", frozenset({n}), shift(n, dx, dy)))
        if n not in paired:          # a lone mirror would break pair matching
            moves.append((f"mirror {n}", frozenset({n}),
                          lambda L, n=n: _with(L, mirror={n: not L.mirror.get(n, False)})))

    for a, b in MATCHED_PAIRS:
        both = frozenset({a, b})
        for dy in (1, -1):
            moves.append((f"pair {a}/{b} y{dy:+d}", both,
                          lambda L, a=a, b=b, dy=dy: _with(L, pos={
                              a: (L.pos[a][0], L.pos[a][1] + dy),
                              b: (L.pos[b][0], L.pos[b][1] + dy)})))
        for k in (1, -1):            # spread (+) / squeeze (-) about the centroid
            def spread(L, a=a, b=b, k=k):
                left, right = (a, b) if L.pos[a][0] <= L.pos[b][0] else (b, a)
                return _with(L, pos={left: (L.pos[left][0] - k, L.pos[left][1]),
                                     right: (L.pos[right][0] + k, L.pos[right][1])})
            moves.append((f"pair {a}/{b} {'spread' if k > 0 else 'squeeze'}", both, spread))
        moves.append((f"mirror pair {a}/{b}", both,
                      lambda L, a=a, b=b: _with(L, mirror={a: not L.mirror.get(a, False),
                                                           b: not L.mirror.get(b, False)})))

    names = list(CORE_NAMES)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if kinds[a] == kinds[b]:
                moves.append((f"swap {a}<->{b}", frozenset({a, b}),
                              lambda L, a=a, b=b: _with(
                                  L, pos={a: L.pos[b], b: L.pos[a]},
                                  mirror={a: L.mirror.get(b, False),
                                          b: L.mirror.get(a, False)})))
    return moves


# --------------------------------------------------------------------------
# Polish driver
# --------------------------------------------------------------------------
def _knee(trials: list[Trial]) -> Trial:
    vecs = [tuple(t.objectives[k] for k in OBJECTIVES) for t in trials]
    return trials[knee_index(vecs, [(v, t.move) for v, t in zip(vecs, trials)])]


def polish_placement(pos: dict[str, tuple[int, int]], sch: Schematic | None = None,
                     sizing=None, rounds: int = 3,
                     mirror: dict[str, bool] | None = None,
                     notify: Callable[[str, dict], None] | None = None) -> dict:
    """Greedy measured polish of a placement (see module docstring).

    Returns {"changed", "pos", "mirror", "flow", "before", "after", "accepted",
    "nTrials", "rounds", "reason"}. `flow` is a run_flow-shaped payload of the
    final placement. A placement that does not sign off is returned unchanged:
    polish starts from a pass, it does not repair.
    """
    sch = sch or two_stage_ota()
    say = notify or (lambda kind, info: None)
    original = _trial(sch, Layout(pos=dict(pos), mirror=dict(mirror or {})), sizing)
    base = {"pos": dict(original.layout.pos), "mirror": dict(original.layout.mirror),
            "before": original.objectives}
    if not original.signs_off:
        return {**base, "changed": False, "flow": original.flow,
                "after": original.objectives, "accepted": [], "nTrials": 0,
                "rounds": 0, "reason": "incumbent does not sign off"}

    incumbent, accepted_log, n_trials, done = original, [], 0, 0
    for _ in range(max(rounds, 0)):
        done += 1
        accepted: list[Trial] = []
        for name, devs, apply in candidate_moves(sch, incumbent.layout):
            lay = apply(incumbent.layout)
            if not _legal(sch, lay):
                continue
            t = _trial(sch, lay, sizing, name, devs)
            n_trials += 1
            ok = improves(incumbent, t, original)
            say("polish_trial", {"move": name, "adopted": ok, "passed": t.signs_off,
                                 "objectives": t.objectives})
            if ok:
                accepted.append(t)
        if not accepted:
            break
        best = _knee(accepted)
        final = best
        # Combine the accepted moves that touch disjoint devices, best first.
        rest = sorted((t for t in accepted if t is not best),
                      key=lambda t: (tuple(t.objectives[k] for k in OBJECTIVES), t.move))
        chosen, used = [best], set(best.devices)
        for t in rest:
            if not (t.devices & used):
                chosen.append(t); used |= t.devices
        if len(chosen) > 1:
            lay = incumbent.layout
            for t in chosen:
                lay = _with(lay, pos={d: t.layout.pos[d] for d in t.devices},
                            mirror={d: t.layout.mirror.get(d, False) for d in t.devices})
            if _legal(sch, lay):
                combo = _trial(sch, lay, sizing, " + ".join(t.move for t in chosen),
                               frozenset(used))
                n_trials += 1
                ok = improves(best, combo, original)
                say("polish_combine", {"moves": [t.move for t in chosen], "adopted": ok})
                if ok:
                    final = combo
        accepted_log.append({"move": final.move, "objectives": final.objectives})
        incumbent = final

    return {"changed": incumbent is not original, "pos": dict(incumbent.layout.pos),
            "mirror": {k: v for k, v in incumbent.layout.mirror.items() if v},
            "flow": incumbent.flow, "before": original.objectives,
            "after": incumbent.objectives, "accepted": accepted_log,
            "nTrials": n_trials, "rounds": done,
            "reason": "improved" if incumbent is not original else "no move cleared the gate"}
