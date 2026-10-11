"""PPA multi-objective optimization (NSGA-II) for the OTA."""

import pytest

from layout_opt.opamp import OpAmpParams
from layout_opt.ppa import (
    area_um2, evaluate_point, nsga2, run_ppa, select_by_weights,
)


def _p(**kw) -> OpAmpParams:
    base = dict(wl1=20, wl3=20, wl5=20, wl6=80, wl7=40,
                itail=20e-6, i6=80e-6, cc=1e-12)
    base.update(kw)
    return OpAmpParams(**base)


def test_area_increases_with_size_and_cap():
    a0 = area_um2(_p())
    assert area_um2(_p(wl6=160)) > a0          # bigger device -> more gate area
    assert area_um2(_p(cc=4e-12)) > a0         # bigger Miller cap -> more area


def test_objectives_minimized_form():
    pt = evaluate_point(_p())
    assert pt.objs == (pt.power_mw, pt.area_um2, -pt.gbw_mhz)


def test_pareto_front_is_nondominated_and_feasible():
    pareto, _ = nsga2(pop_size=40, generations=15, seed=1)
    assert len(pareto) >= 5
    assert all(p.feasible for p in pareto)
    # No front member dominates another on all three objectives.
    for a in pareto:
        for b in pareto:
            if a is b:
                continue
            strictly_better_all = all(x < y for x, y in zip(a.objs, b.objs))
            assert not strictly_better_all


def test_front_spans_a_real_tradeoff():
    pareto, _ = nsga2(pop_size=60, generations=25, seed=2)
    gbws = [p.gbw_mhz for p in pareto]
    powers = [p.power_mw for p in pareto]
    assert max(gbws) > 2 * min(gbws)           # bandwidth actually varies
    # The fastest design costs more power than the slowest (no free lunch).
    fastest = max(pareto, key=lambda p: p.gbw_mhz)
    slowest = min(pareto, key=lambda p: p.gbw_mhz)
    assert fastest.power_mw > slowest.power_mw


def test_weighting_shifts_the_choice():
    pareto, _ = nsga2(pop_size=60, generations=25, seed=3)
    perf = select_by_weights(pareto, 0.0, 0.0, 1.0)      # all-in on performance
    power = select_by_weights(pareto, 1.0, 0.0, 0.0)     # all-in on low power
    assert perf.gbw_mhz >= power.gbw_mhz
    assert power.power_mw <= perf.power_mw


def test_run_ppa_payload():
    r = run_ppa(pop_size=40, generations=12, seed=0)
    assert r["nParetoFront"] == len(r["pareto"])
    assert r["chosen"] is not None
    assert set(r["ranges"]) == {"power_mw", "area_um2", "gbw_mhz"}
    assert {"power_mw", "area_um2", "gbw_mhz", "gain_db", "pm_deg"} <= set(r["pareto"][0])


# --- knee pick + order-independent tie-breaks --------------------------------
import random as _random

from layout_opt.ppa import PPAPoint, _crowded_order, _crowding, knee_point


def _pt(objs, wl1=20.0):
    """A feasible synthetic point with the given (power, area, -gbw) objectives."""
    return PPAPoint(params=_p(wl1=wl1), power_mw=objs[0], area_um2=objs[1],
                    gbw_mhz=-objs[2], gain_db=70.0, pm_deg=70.0, violation=0.0,
                    objs=tuple(objs))


def test_knee_picks_the_compromise_not_an_extreme():
    front = [_pt((0.0, 1.0, -5.0)), _pt((1.0, 0.0, -5.0)), _pt((0.4, 0.4, -5.0))]
    assert knee_point(front).objs == (0.4, 0.4, -5.0)


def test_knee_ignores_a_constant_objective():
    # The third objective is constant: it must not move (or break) the pick.
    a = [_pt((0.0, 1.0, -7.0)), _pt((1.0, 0.0, -7.0)), _pt((0.3, 0.5, -7.0))]
    assert knee_point(a).objs == (0.3, 0.5, -7.0)


def test_knee_is_independent_of_list_order():
    # Two members exactly equidistant from the ideal point: the tie is broken
    # by the objective tuple, so every permutation gives the same answer.
    front = [_pt((0.0, 1.0, 0.0)), _pt((1.0, 0.0, 0.0)),
             _pt((0.5, 0.5, 0.0)), _pt((0.5, 0.5, 0.0), wl1=30.0)]
    picks = set()
    rng = _random.Random(0)
    for _ in range(12):
        rng.shuffle(front)
        k = knee_point(front)
        picks.add((k.objs, k.params.wl1))
    assert picks == {((0.5, 0.5, 0.0), 20.0)}


def test_knee_skips_dominated_and_infeasible_members():
    # (10, 0.9) is dominated by (1, 0); if it were kept it would stretch the
    # power range tenfold and drag the knee to (1, 0). The infeasible point
    # would dominate everything on objectives alone.
    good = [_pt((0.0, 1.0, 0.0)), _pt((1.0, 0.0, 0.0)),
            _pt((0.3, 0.6, 0.0)), _pt((0.6, 0.3, 0.0))]
    dominated = _pt((10.0, 0.9, 0.0))
    infeasible = _pt((0.0, 0.0, 0.0)); infeasible.violation = 1.0
    assert knee_point(good + [dominated, infeasible]).objs == (0.3, 0.6, 0.0)


def test_knee_of_real_front_is_a_front_member_and_order_free():
    pareto, _ = nsga2(pop_size=40, generations=12, seed=4)
    k = knee_point(pareto)
    assert k in pareto
    assert knee_point(list(reversed(pareto))) is k


def test_crowding_extremes_are_ordered_by_design_not_position():
    pts = [_pt((0.0, 3.0, 0.0)), _pt((1.0, 2.0, 0.0)), _pt((2.0, 1.0, 0.0)),
           _pt((3.0, 0.0, 0.0))]
    orders = set()
    for perm in ([0, 1, 2, 3], [3, 2, 1, 0], [1, 3, 0, 2]):
        pop = [pts[i] for i in perm]
        idx = list(range(len(pop)))
        cd = _crowding(pop, list(idx))
        orders.add(tuple(pop[i].objs for i in _crowded_order(pop, idx, cd)))
    assert len(orders) == 1
    first_two = next(iter(orders))[:2]
    assert set(first_two) == {(0.0, 3.0, 0.0), (3.0, 0.0, 0.0)}   # the +inf extremes


def test_select_by_weights_is_order_free():
    pareto, _ = nsga2(pop_size=40, generations=12, seed=5)
    a = select_by_weights(pareto, 1.0, 1.0, 1.0)
    b = select_by_weights(list(reversed(pareto)), 1.0, 1.0, 1.0)
    assert a is b


def test_run_ppa_reports_knee_and_selection_rule():
    default = run_ppa(pop_size=40, generations=12, seed=0)
    assert default["selection"] == "knee"
    assert default["chosen"] == default["knee"]
    weighted = run_ppa(pop_size=40, generations=12, seed=0, weights=(1.0, 0.0, 0.0))
    assert weighted["selection"] == "weights"
    assert weighted["knee"] == default["knee"]            # same front, same knee
    assert weighted["chosen"]["power_mw"] == weighted["ranges"]["power_mw"][0]
