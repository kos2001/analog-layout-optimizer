"""Seed sweep + sign-off ranking: pick the best full-flow run, not a random one."""

from layout_opt.flow_e2e import rank_candidates, run_best_of


def _result(verdict="PASS", unrouted=(), lvs_clean=True, drc_errors=0,
            drc_warnings=0, post_pm=60.0, seed=0):
    """Minimal synthetic run_end_to_end payload for ranking tests."""
    return {
        "verdict": verdict,
        "routing": {"failed": list(unrouted)},
        "signoff": {"lvs": {"clean": lvs_clean},
                    "drcErrors": drc_errors, "drcWarnings": drc_warnings},
        "postlayout": {"post": {"pm_deg": post_pm}},
        "seed": seed,
    }


def test_rank_prefers_pass_over_fail():
    results = [_result(verdict="FAIL", drc_errors=1),
               _result(verdict="PASS")]
    assert rank_candidates(results) == 1


def test_rank_prefers_fewer_unrouted_nets():
    results = [_result(verdict="FAIL", unrouted=["n1", "n2"], lvs_clean=False),
               _result(verdict="FAIL", unrouted=["n1"], lvs_clean=False)]
    assert rank_candidates(results) == 1


def test_rank_prefers_lvs_clean_then_fewer_drc_errors():
    results = [_result(verdict="FAIL", lvs_clean=False),
               _result(verdict="FAIL", drc_errors=3),
               _result(verdict="FAIL", drc_errors=1)]
    assert rank_candidates(results) == 2


def test_rank_breaks_ties_on_postlayout_pm():
    results = [_result(post_pm=48.0), _result(post_pm=61.0)]
    assert rank_candidates(results) == 1


def test_run_best_of_returns_best_with_sweep_summary():
    calls = []

    def fake_runner(place, seed, sky130, maxiter):
        calls.append(seed)
        return _result(verdict="FAIL" if seed != 2 else "PASS",
                       unrouted=["n1"] if seed == 1 else [], seed=seed)

    out = run_best_of(place="sa", seeds=[0, 1, 2], sky130=False,
                      maxiter=40, runner=fake_runner)
    assert calls == [0, 1, 2]
    assert out["verdict"] == "PASS" and out["seed"] == 2
    assert out["sweep"]["bestSeed"] == 2
    assert out["sweep"]["seeds"] == [0, 1, 2]
    assert out["sweep"]["verdicts"] == ["FAIL", "FAIL", "PASS"]
