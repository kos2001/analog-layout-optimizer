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


# --------------------------------------------------------------------------
# Parallel sweep: must be indistinguishable from the serial one
# --------------------------------------------------------------------------
import json

from layout_opt import flow_e2e
from layout_opt.runlog import Profiler


def _tie_runner(place, seed, sky130, maxiter):
    """Top-level (picklable) runner where every seed ties: first seed must win."""
    return _result(verdict="PASS", post_pm=60.0, seed=seed)


def _canon(d):
    return json.dumps(d, sort_keys=True, default=str)


def test_parallel_sweep_matches_serial_on_real_flow():
    seeds = [3, 0, 2, 1]                      # unsorted: output order must follow input
    serial = run_best_of(seeds=seeds, maxiter=20, workers=1)
    parallel = run_best_of(seeds=seeds, maxiter=20, workers=2)
    assert _canon(parallel) == _canon(serial)
    assert parallel["sweep"]["seeds"] == seeds


def test_parallel_sweep_keeps_serial_tie_breaking():
    seeds = [5, 1, 9]
    serial = run_best_of(seeds=seeds, runner=_tie_runner, workers=1)
    parallel = run_best_of(seeds=seeds, runner=_tie_runner, workers=3)
    assert parallel == serial and parallel["sweep"]["bestSeed"] == 5


def test_parallel_sweep_replays_stage_stats_into_parent_profiler():
    with Profiler() as prof:
        run_best_of(seeds=[0, 1], maxiter=10, workers=2)
    assert prof.stats["sizing"].calls == 2    # stages ran in workers, recorded here
    assert prof.stats["routing"].calls == 2


def test_sweep_falls_back_to_serial_when_no_process_pool(monkeypatch):
    def no_pool(*a, **k):
        raise OSError("process spawning disabled")
    monkeypatch.setattr(flow_e2e, "ProcessPoolExecutor", no_pool)
    out = run_best_of(seeds=[0, 1, 2], runner=_tie_runner, workers=3)
    assert out["sweep"]["bestSeed"] == 0


def test_select_best_does_not_mutate_inputs():
    results = [_result(post_pm=50.0), _result(post_pm=70.0)]
    out = flow_e2e.select_best([0, 1], results)
    assert out["sweep"]["bestSeed"] == 1 and "sweep" not in results[1]
