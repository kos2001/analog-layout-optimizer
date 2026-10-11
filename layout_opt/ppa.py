"""PPA optimization for the two-stage OTA — multi-objective (NSGA-II).

PPA (Power · Performance · Area) has no single optimum: more bandwidth costs
more current (power) and bigger devices + a bigger Miller cap (area). The honest
answer is a **Pareto front** — the set of designs where you can't improve one
axis without giving up another. NSGA-II (constrained non-dominated sorting +
crowding distance) is the industry-standard evolutionary algorithm for it.

Objectives (all minimized internally):
    power  = VDD·(Itail + I6)                     -> minimize
    area   = Σ gate area + Miller-cap area         -> minimize
    -GBW   = -(gain-bandwidth)                      -> maximize GBW

Constraints (hard): phase margin, device overdrive headroom, a gain floor.
Gain/GBW are otherwise free so the front spans the real speed/cost trade-off.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .opamp import (
    VDD, OpAmpParams, OpAmpSpecs, bounds_vector, evaluate_opamp,
)
from .opamp_opt import PM_MIN, VOV_MIN, VOV_MAX

L_UM = 0.18                 # drawn channel length (microns)
CAP_DENSITY = 5e-15         # Miller-cap density (F per µm^2), MIM-ish
GAIN_FLOOR = 60.0           # dB — keep it a real amplifier (GBW is the objective)


def area_um2(p: OpAmpParams) -> float:
    """Active gate area (ΣW·L, W = (W/L)·L) + Miller-cap area, in µm^2."""
    wl_sum = 2 * p.wl1 + 2 * p.wl3 + p.wl5 + p.wl6 + p.wl7   # pair + load are ×2
    gate = wl_sum * (L_UM ** 2)
    cap = p.cc / CAP_DENSITY
    return gate + cap


def _ppa_violation(s: OpAmpSpecs) -> float:
    """Hard-constraint shortfall (0 == feasible): PM, overdrive, gain floor."""
    v = max(0.0, (PM_MIN - s.pm_deg) / PM_MIN)
    v += max(0.0, (GAIN_FLOOR - s.gain_db) / GAIN_FLOOR)
    for vov in (s.vov1, s.vov3, s.vov5, s.vov6, s.vov7):
        v += max(0.0, (VOV_MIN - vov) / VOV_MIN)
        v += max(0.0, (vov - VOV_MAX) / VOV_MAX)
    return v


@dataclass
class PPAPoint:
    params: OpAmpParams
    power_mw: float
    area_um2: float
    gbw_mhz: float
    gain_db: float
    pm_deg: float
    violation: float
    objs: tuple = field(default=())     # (power, area, -gbw) — minimized

    @property
    def feasible(self) -> bool:
        return self.violation <= 1e-9


def evaluate_point(p: OpAmpParams) -> PPAPoint:
    s = evaluate_opamp(p)
    pw = s.power / 1e-3
    ar = area_um2(p)
    gbw = s.gbw_hz / 1e6
    viol = _ppa_violation(s)
    return PPAPoint(params=p, power_mw=pw, area_um2=ar, gbw_mhz=gbw,
                    gain_db=s.gain_db, pm_deg=s.pm_deg, violation=viol,
                    objs=(pw, ar, -gbw))


# --------------------------------------------------------------------------
# NSGA-II
# --------------------------------------------------------------------------
_BOUNDS = bounds_vector()
_LOG = [(math.log(lo), math.log(hi)) for lo, hi in _BOUNDS]   # search in log space


def _rand_vec(rng: random.Random) -> list[float]:
    return [math.exp(rng.uniform(lo, hi)) for lo, hi in _LOG]


def _clip_log(xl: list[float]) -> list[float]:
    return [min(max(x, lo), hi) for x, (lo, hi) in zip(xl, _LOG)]


def _to_log(x: list[float]) -> list[float]:
    return [math.log(max(v, 1e-30)) for v in x]


def _dominates(a: PPAPoint, b: PPAPoint) -> bool:
    """Constrained domination: feasibility first, then Pareto on objectives."""
    if a.violation <= 1e-9 and b.violation > 1e-9:
        return True
    if a.violation > 1e-9 and b.violation <= 1e-9:
        return False
    if a.violation > 1e-9 and b.violation > 1e-9:
        return a.violation < b.violation
    le = all(x <= y for x, y in zip(a.objs, b.objs))
    lt = any(x < y for x, y in zip(a.objs, b.objs))
    return le and lt


def _fast_nondominated_sort(pop: list[PPAPoint]) -> list[list[int]]:
    n = len(pop)
    S = [[] for _ in range(n)]
    ndom = [0] * n
    fronts: list[list[int]] = [[]]
    for p in range(n):
        for q in range(n):
            if p == q:
                continue
            if _dominates(pop[p], pop[q]):
                S[p].append(q)
            elif _dominates(pop[q], pop[p]):
                ndom[p] += 1
        if ndom[p] == 0:
            fronts[0].append(p)
    i = 0
    while fronts[i]:
        nxt = []
        for p in fronts[i]:
            for q in S[p]:
                ndom[q] -= 1
                if ndom[q] == 0:
                    nxt.append(q)
        i += 1
        fronts.append(nxt)
    return fronts[:-1]


def _tie_key(pt: PPAPoint) -> tuple:
    """Order-independent tie-break: objective tuple, then the sizing vector."""
    return (pt.objs, tuple(pt.params.to_vector()))


def _crowding(pop: list[PPAPoint], idx: list[int]) -> dict[int, float]:
    """NSGA-II crowding distance over one front (extremes get +inf).

    Each per-objective sort breaks ties on the full objective tuple, so which
    of several equal-valued members becomes the boundary (inf) point depends
    on the designs, not on their position in the population list.
    """
    dist = {i: 0.0 for i in idx}
    if len(idx) <= 2:
        return {i: float("inf") for i in idx}
    for m in range(3):
        idx.sort(key=lambda i: (pop[i].objs[m], _tie_key(pop[i])))
        dist[idx[0]] = dist[idx[-1]] = float("inf")
        lo, hi = pop[idx[0]].objs[m], pop[idx[-1]].objs[m]
        span = hi - lo or 1.0
        for k in range(1, len(idx) - 1):
            dist[idx[k]] += (pop[idx[k + 1]].objs[m] - pop[idx[k - 1]].objs[m]) / span
    return dist


def _crowded_order(pop: list[PPAPoint], front: list[int],
                   cd: dict[int, float]) -> list[int]:
    """Front members, most isolated first; equal distances (notably the many
    +inf extremes) are ordered by the objective tuple, not by list position."""
    return sorted(front, key=lambda i: (-cd[i], _tie_key(pop[i])))


def knee_point(front: list[PPAPoint]) -> PPAPoint | None:
    """The compromise member of a Pareto front: closest to the ideal point.

    Each objective is min-max normalized across the front and the member with
    the smallest Euclidean distance to the ideal (all-minimum) corner wins —
    compromise programming (Yu 1973; Zeleny 1973), the standard knee heuristic
    for an NSGA front when no preference is stated. It is not a claim that the
    knee is "the best" design, only that it is not an arbitrary extreme (a
    crowding-distance tie-break would hand the pick to whichever +inf extreme
    comes first in the list).

    An objective that is constant across the front contributes nothing. Only
    the non-dominated, feasible members of `front` are considered, so passing a
    whole population is safe. Ties are broken by the lexicographic objective
    tuple (then the sizing), so the result does not depend on the order of
    `front`.
    """
    pts = [p for p in front if p.feasible] or list(front)
    if not pts:
        return None
    pts = [pts[i] for i in _fast_nondominated_sort(pts)[0]]
    return pts[knee_index([p.objs for p in pts], [_tie_key(p) for p in pts])]


def knee_index(objs: list[tuple], tie_keys: list | None = None) -> int | None:
    """Index of the member closest to the ideal point (see `knee_point`).

    `objs` are minimized objective vectors of an already non-dominated set.
    Objectives are min-max normalized across the set; a constant objective
    contributes nothing. Ties go to the smallest `tie_keys[i]` (default: the
    objective vector itself), never to list position.
    """
    if not objs:
        return None
    keys = tie_keys if tie_keys is not None else [tuple(o) for o in objs]
    n_obj = len(objs[0])
    lo = [min(o[m] for o in objs) for m in range(n_obj)]
    hi = [max(o[m] for o in objs) for m in range(n_obj)]

    def distance(o) -> float:
        total = 0.0
        for m in range(n_obj):
            span = hi[m] - lo[m]
            if span > 0:
                total += ((o[m] - lo[m]) / span) ** 2
        return math.sqrt(total)

    return min(range(len(objs)), key=lambda i: (distance(objs[i]), keys[i]))


def _crossover_mutate(a: list[float], b: list[float], rng: random.Random,
                      mut_rate: float = 0.25, mut_sigma: float = 0.35) -> list[float]:
    """Blend crossover + Gaussian mutation, in log space."""
    al, bl = _to_log(a), _to_log(b)
    child = []
    for (av, bv), (lo, hi) in zip(zip(al, bl), _LOG):
        w = rng.random()
        v = w * av + (1 - w) * bv
        if rng.random() < mut_rate:
            v += rng.gauss(0.0, mut_sigma) * (hi - lo)
        child.append(v)
    return [math.exp(v) for v in _clip_log(child)]


def _tournament(pop, ranks, dist, rng):
    i, j = rng.randrange(len(pop)), rng.randrange(len(pop))
    if ranks[i] != ranks[j]:
        return i if ranks[i] < ranks[j] else j
    return i if dist.get(i, 0) >= dist.get(j, 0) else j


def nsga2(pop_size: int = 80, generations: int = 40, seed: int = 0):
    """Run NSGA-II; return (pareto_points, all_final_points)."""
    rng = random.Random(seed)
    pop = [evaluate_point(OpAmpParams.from_vector(_rand_vec(rng)))
           for _ in range(pop_size)]

    for _ in range(generations):
        fronts = _fast_nondominated_sort(pop)
        ranks = {}
        dist = {}
        for r, fr in enumerate(fronts):
            cd = _crowding(pop, list(fr))
            for i in fr:
                ranks[i] = r
                dist[i] = cd[i]
        # Offspring.
        kids = []
        while len(kids) < pop_size:
            pa = pop[_tournament(pop, ranks, dist, rng)]
            pb = pop[_tournament(pop, ranks, dist, rng)]
            xv = _crossover_mutate(pa.params.to_vector(), pb.params.to_vector(), rng)
            kids.append(evaluate_point(OpAmpParams.from_vector(xv)))
        # Elitist merge: keep best pop_size from parents+kids.
        merged = pop + kids
        fronts = _fast_nondominated_sort(merged)
        newpop: list[PPAPoint] = []
        for fr in fronts:
            if len(newpop) + len(fr) <= pop_size:
                newpop.extend(merged[i] for i in fr)
            else:
                cd = _crowding(merged, list(fr))
                fr_sorted = _crowded_order(merged, fr, cd)
                newpop.extend(merged[i] for i in fr_sorted[:pop_size - len(newpop)])
                break
        pop = newpop

    fronts = _fast_nondominated_sort(pop)
    pareto = [pop[i] for i in fronts[0] if pop[i].feasible]
    pareto.sort(key=lambda pt: (pt.gbw_mhz, _tie_key(pt)))
    return pareto, pop


def _pt_payload(pt: PPAPoint) -> dict:
    return {"power_mw": round(pt.power_mw, 4), "area_um2": round(pt.area_um2, 2),
            "gbw_mhz": round(pt.gbw_mhz, 2), "gain_db": round(pt.gain_db, 2),
            "pm_deg": round(pt.pm_deg, 1), "feasible": pt.feasible,
            "sizing": {"wl1": round(pt.params.wl1, 1), "wl3": round(pt.params.wl3, 1),
                       "wl6": round(pt.params.wl6, 1),
                       "itail_uA": round(pt.params.itail * 1e6, 1),
                       "i6_uA": round(pt.params.i6 * 1e6, 1),
                       "cc_pF": round(pt.params.cc * 1e12, 2)}}


def select_by_weights(pareto: list[PPAPoint], w_power: float, w_area: float,
                      w_perf: float) -> PPAPoint | None:
    """Pick the Pareto design best matching a P/P/A preference (normalized)."""
    if not pareto:
        return None
    pw = [p.power_mw for p in pareto]; ar = [p.area_um2 for p in pareto]
    gb = [p.gbw_mhz for p in pareto]
    def norm(v, arr):
        lo, hi = min(arr), max(arr)
        return (v - lo) / (hi - lo) if hi > lo else 0.0
    tot = (w_power + w_area + w_perf) or 1.0
    wp, wa, wf = w_power / tot, w_area / tot, w_perf / tot
    def score(p: PPAPoint) -> float:
        return (wp * norm(p.power_mw, pw) + wa * norm(p.area_um2, ar)
                + wf * (1.0 - norm(p.gbw_mhz, gb)))     # higher GBW is better

    # Equal scores are broken by the objective tuple, not by list order.
    return min(pareto, key=lambda p: (score(p), _tie_key(p)))


def run_ppa(pop_size: int = 80, generations: int = 40, seed: int = 0,
            weights: tuple | None = None) -> dict:
    """Pareto front + the chosen design.

    With `weights` (power, area, perf) the chosen design is the preference-
    weighted pick; without, it is the front's knee (`knee_point`). The knee is
    always reported under "knee", and "selection" says which rule chose.
    """
    pareto, pop = nsga2(pop_size, generations, seed)
    knee = knee_point(pareto)
    if weights is None:
        chosen, selection = knee, "knee"
    else:
        chosen, selection = select_by_weights(pareto, *weights), "weights"
    # Dominated cloud (feasible, non-Pareto) for context, capped.
    pset = {id(p) for p in pareto}
    cloud = [p for p in pop if p.feasible and id(p) not in pset][:200]
    return {
        "pareto": [_pt_payload(p) for p in pareto],
        "cloud": [{"power_mw": round(p.power_mw, 4), "area_um2": round(p.area_um2, 2),
                   "gbw_mhz": round(p.gbw_mhz, 2)} for p in cloud],
        "chosen": _pt_payload(chosen) if chosen else None,
        "knee": _pt_payload(knee) if knee else None,
        "selection": selection,
        "weights": ({"power": weights[0], "area": weights[1], "perf": weights[2]}
                    if weights is not None
                    else {"power": None, "area": None, "perf": None}),
        "ranges": {
            "power_mw": [round(min(p.power_mw for p in pareto), 4),
                         round(max(p.power_mw for p in pareto), 4)],
            "area_um2": [round(min(p.area_um2 for p in pareto), 2),
                         round(max(p.area_um2 for p in pareto), 2)],
            "gbw_mhz": [round(min(p.gbw_mhz for p in pareto), 2),
                        round(max(p.gbw_mhz for p in pareto), 2)],
        } if pareto else {},
        "nParetoFront": len(pareto),
        "constraints": {"gain_floor_db": GAIN_FLOOR, "pm_min_deg": PM_MIN},
    }
