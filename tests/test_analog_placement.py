"""Op-amp-aware placement: matching/symmetry + critical-net weighting."""
from layout_opt.placement import (
    sa_place, matching_metrics, crit_hpwl, symmetry_penalty, run_flow, _wh,
    MATCHED_PAIRS, CRITICAL_NETS,
)
from layout_opt.schematic import two_stage_ota


def test_analog_aware_improves_matching_and_critical_net():
    sch = two_stage_ota()
    plain = sa_place(sch, seed=0, analog_aware=False)
    analog = sa_place(sch, seed=0, analog_aware=True)
    mp, ma = matching_metrics(sch, plain), matching_metrics(sch, analog)
    assert ma["symmetry_penalty"] < mp["symmetry_penalty"]   # pairs more symmetric
    assert ma["critical_wl"] <= mp["critical_wl"]             # high-Z nets shorter


def test_matched_pairs_end_up_close():
    sch = two_stage_ota()
    pos = sa_place(sch, seed=0, analog_aware=True)
    m = matching_metrics(sch, pos)
    for pair in ("M1/M2", "M3/M4"):
        assert m["pair_distance"][pair] < 12.0      # input pair / mirror kept together


def test_run_flow_reports_matching():
    f = run_flow("sa", seed=0, analog_aware=True)
    assert f["analogAware"] is True
    assert "symmetry_penalty" in f["matching"] and "critical_wl" in f["matching"]


def test_critical_nets_and_pairs_defined():
    assert CRITICAL_NETS == {"n1", "n2"}
    assert ("M1", "M2") in MATCHED_PAIRS and ("M3", "M4") in MATCHED_PAIRS
