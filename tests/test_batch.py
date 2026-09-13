"""Batch mode: config handling, run directory, reports, exit codes, profiling."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from layout_opt import batch
from layout_opt.runlog import Profiler, stage

ROOT = Path(__file__).resolve().parent.parent


def test_stage_is_noop_without_profiler():
    with stage("anything"):
        pass                                   # must not raise or record anywhere


def test_profiler_accumulates_repeated_stages():
    seen = []
    with Profiler(on_stage=lambda st, wall: seen.append(st.name)) as prof:
        for _ in range(3):
            with stage("routing"):
                pass
    assert prof.stats["routing"].calls == 3
    assert seen == ["routing"] * 3
    with stage("routing"):                     # profiler no longer active
        pass
    assert prof.stats["routing"].calls == 3


def test_load_config_merges_file_and_overrides(tmp_path):
    f = tmp_path / "flow.json"
    f.write_text(json.dumps({"seeds": [1, 2], "maxiter": 10}))
    cfg = batch.load_config(str(f), {"maxiter": 5, "place": None})
    assert cfg["seeds"] == [1, 2] and cfg["maxiter"] == 5 and cfg["place"] == "sa"


@pytest.mark.parametrize("user, msg", [
    ({"bogus": 1}, "unknown config key"),
    ({"place": "grid"}, "place must be"),
    ({"seeds": []}, "seeds must be"),
    ({"maxiter": 0}, "maxiter must be"),
    ({"design": "ldo"}, "unknown design"),
])
def test_load_config_rejects_bad_input(tmp_path, user, msg):
    f = tmp_path / "flow.json"
    f.write_text(json.dumps(user))
    with pytest.raises(batch.ConfigError, match=msg):
        batch.load_config(str(f), {})


def test_flow_run_directory_reports_and_exit_code(tmp_path):
    out = tmp_path / "run"
    code = batch.main(["flow", "-o", str(out), "--maxiter", "30", "--seeds", "0", "-q"])
    for rel in ("flow.json", "logs/run.log", "outputs/design.json", "outputs/two_stage_ota.gds",
                *(f"reports/{r}.rpt" for r in
                  ("qor", "sizing", "placement", "route", "drc", "lvs", "postlayout"))):
        assert (out / rel).is_file(), rel
    design = json.loads((out / "outputs/design.json").read_text())
    assert code == (batch.EXIT_PASS if design["verdict"] == "PASS" else batch.EXIT_FAIL)
    assert json.loads((out / "flow.json").read_text())["config"]["maxiter"] == 30

    qor = (out / "reports/qor.rpt").read_text()
    assert f"Verdict            : {design['verdict']}" in qor
    for st in ("sizing", "placement", "routing", "signoff", "postlayout", "gds_export"):
        assert f"\n{st} " in qor                  # per-stage resource row
    log = (out / "logs/run.log").read_text()
    assert "(ALO-001)" in log and "(ALO-900)" in log
    lvs = (out / "reports/lvs.rpt").read_text()
    assert ("CORRECT" in lvs) == design["signoff"]["lvs"]["clean"]


def test_cli_config_error_exits_2(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text('{"place": "nowhere"}')
    r = subprocess.run([sys.executable, "-m", "layout_opt", "flow", "-f", str(f),
                        "-o", str(tmp_path / "run")], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == batch.EXIT_ERROR
    assert "place must be" in r.stderr
    assert not (tmp_path / "run").exists()
