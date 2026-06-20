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
