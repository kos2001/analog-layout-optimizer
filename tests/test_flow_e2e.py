"""End-to-end one-click flow orchestration."""

from layout_opt.flow_e2e import run_end_to_end


def test_e2e_runs_all_stages():
    r = run_end_to_end(place="sa", seed=1, sky130=False, maxiter=40)
    names = [s["name"] for s in r["stages"]]
    assert names[:6] == ["Sizing (DE)", "Schematic", "Placement (SA)",
                         "Routing (negotiated)", "Sign-off (DRC+LVS)",
                         "Post-layout (parasitics)"]


def test_e2e_carries_full_flow_payload():
    r = run_end_to_end(place="sa", seed=1, sky130=False, maxiter=40)
    assert {"routing", "signoff", "postlayout", "components", "netlist"} <= set(r)
    assert "sizing" in r and "verdict" in r


def test_e2e_verdict_gates_on_physical_signoff_not_postlayout():
    # post-layout is advisory (warn); verdict follows sizing/routing/sign-off.
    r = run_end_to_end(place="sa", seed=1, sky130=False, maxiter=40)
    post = next(s for s in r["stages"] if s["name"].startswith("Post-layout"))
    assert post["status"] in ("pass", "warn")
    gating = [s for s in r["stages"] if s["status"] in ("pass", "fail")]
    assert (r["verdict"] == "PASS") == all(s["status"] == "pass" for s in gating)


def test_e2e_no_silicon_stage_when_sky130_off():
    r = run_end_to_end(place="sa", seed=1, sky130=False, maxiter=40)
    assert r["silicon"] is None
    assert not any("Silicon" in s["name"] for s in r["stages"])


def test_e2e_uses_sized_params_for_postlayout():
    # The post-layout sizing should reflect the DE result, not the fixed demo.
    r = run_end_to_end(place="sa", seed=1, sky130=False, maxiter=40)
    assert r["sizing"]["gbw_mhz"] > 0 and r["sizing"]["power_mw"] > 0
