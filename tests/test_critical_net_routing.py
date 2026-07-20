"""Critical-net aware P&R: n1/n2/VOUT get placement weight + routing priority."""

from layout_opt.flow_e2e import run_end_to_end
from layout_opt.placement import ROUTE_PRIORITY, run_flow


def test_route_priority_covers_pm_critical_nets():
    # The post-layout PM model keys on n2 and VOUT parasitics; both must be
    # routed before the non-critical nets grab the short paths.
    assert "n2" in ROUTE_PRIORITY and "VOUT" in ROUTE_PRIORITY


def test_run_flow_routes_priority_nets_first():
    f = run_flow(place="sa", seed=0, analog_aware=True)
    order = f["routing"]["netNames"]
    crit = [n for n in order if n in ROUTE_PRIORITY]
    rest = [n for n in order if n not in ROUTE_PRIORITY]
    assert order[:len(crit)] == crit and order[len(crit):] == rest


def test_e2e_flow_is_analog_aware():
    r = run_end_to_end(place="sa", seed=0, sky130=False, maxiter=40)
    assert r["analogAware"] is True


def test_critical_aware_pnr_improves_postlayout_pm():
    # The observable that matters: post-layout PM (dominated by the n2 pole)
    # must not get worse when placement/routing favours the critical nets.
    base = run_flow(place="sa", seed=0, analog_aware=False)
    crit = run_flow(place="sa", seed=0, analog_aware=True)
    assert (crit["postlayout"]["post"]["pm_deg"]
            >= base["postlayout"]["post"]["pm_deg"])
