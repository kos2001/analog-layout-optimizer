"""Async job API + non-blocking/cached endpoints of the web backend."""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

import webapp.backend.main as main
from layout_opt.provenance import code_version

GATE = threading.Event()


@pytest.fixture
def client():
    """Thread-mode service (closures allowed, fast startup) + test-only kinds."""
    GATE.clear()
    main.configure_service(mode="thread", workers=2, cache_size=64)

    @main._kind("_test_gate")
    def _gate(tag: str = "a") -> dict:
        assert GATE.wait(10), "test gate never opened"
        return {"tag": tag}

    @main._kind("_test_boom")
    def _boom(msg: str = "boom") -> dict:
        raise ValueError(msg)

    with TestClient(main.app) as c:
        yield c
    GATE.set()
    for k in ("_test_gate", "_test_boom"):
        main.KINDS.pop(k, None)
    main.configure_service()                  # back to env defaults for other modules


def _wait(c, job_id, timeout=30.0) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["status"] in ("done", "error", "cancelled"):
            return snap
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish: {snap}")


def _sse_events(c, job_id) -> list[tuple[str, dict]]:
    out = []
    with c.stream("GET", f"/api/jobs/{job_id}/events") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        etype = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                etype = line[7:]
            elif line.startswith("data: "):
                out.append((etype, json.loads(line[6:])))
    return out


def _norm(d):
    return json.loads(json.dumps(d, default=str))


def test_submit_returns_202_then_poll_to_done(client):
    r = client.post("/api/jobs", json={"kind": "opamp/study", "params": {"seeds": 1}})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] in ("queued", "running") and body["deduplicated"] is False
    snap = _wait(client, body["job_id"])
    assert snap["status"] == "done" and snap["error"] is None
    assert snap["runSeconds"] is not None and snap["queueSeconds"] is not None
    # Same payload as the synchronous endpoint (which now hits the cache).
    assert snap["result"] == client.get("/api/opamp/study?seeds=1").json()


def test_identical_request_while_running_is_deduplicated(client):
    a = client.post("/api/jobs", json={"kind": "_test_gate", "params": {"tag": "x"}}).json()
    b = client.post("/api/jobs", json={"kind": "_test_gate", "params": {"tag": "x"}}).json()
    other = client.post("/api/jobs", json={"kind": "_test_gate", "params": {"tag": "y"}}).json()
    assert b["job_id"] == a["job_id"] and b["deduplicated"] is True
    assert other["job_id"] != a["job_id"]
    GATE.set()
    assert _wait(client, a["job_id"])["result"] == {"tag": "x"}


def test_repeat_after_done_is_a_cache_hit(client):
    first = client.post("/api/jobs", json={"kind": "opamp", "params": {}}).json()
    done = _wait(client, first["job_id"])
    again = client.post("/api/jobs", json={"kind": "opamp", "params": {}})
    assert again.status_code == 202
    hit = again.json()
    assert hit["job_id"] != first["job_id"] and hit["status"] == "done" and hit["cache"] == "hit"
    assert client.get(f"/api/jobs/{hit['job_id']}").json()["result"] == done["result"]


def test_endpoint_repeat_is_served_from_cache(client):
    before = main.SERVICE.cache.stats()["hits"]
    r1 = client.get("/api/opamp/study?seeds=1").json()
    r2 = client.get("/api/opamp/study?seeds=1").json()
    assert r1 == r2 and main.SERVICE.cache.stats()["hits"] == before + 1


def test_error_status_propagates_and_is_not_cached(client):
    j = client.post("/api/jobs", json={"kind": "_test_boom", "params": {"msg": "kaput"}}).json()
    snap = _wait(client, j["job_id"])
    assert snap["status"] == "error" and snap["error"] == "ValueError: kaput"
    assert snap["result"] is None
    j2 = client.post("/api/jobs", json={"kind": "_test_boom", "params": {"msg": "kaput"}}).json()
    assert j2["job_id"] != j["job_id"] and j2["cache"] != "hit"   # errors are retried
    assert _wait(client, j2["job_id"])["status"] == "error"
    events = _sse_events(client, j["job_id"])
    assert events[-1] == ("status", {**events[-1][1], "status": "error"})


def test_sse_stream_ends_with_terminal_event(client):
    j = client.post("/api/jobs", json={"kind": "_test_gate", "params": {"tag": "sse"}}).json()
    threading.Timer(0.2, GATE.set).start()       # finish while the stream is open
    events = _sse_events(client, j["job_id"])
    statuses = [d["status"] for t, d in events if t == "status"]
    assert statuses[0] == "queued" and statuses[-1] == "done"
    assert "running" in statuses
    assert all(d["job_id"] == j["job_id"] for _, d in events)


def test_cancel_only_while_queued(client):
    main.configure_service(mode="thread", workers=2, max_running=1)
    running = client.post("/api/jobs", json={"kind": "_test_gate", "params": {"tag": "r"}}).json()
    queued = client.post("/api/jobs", json={"kind": "_test_gate", "params": {"tag": "q"}}).json()
    assert client.get(f"/api/jobs/{queued['job_id']}").json()["status"] == "queued"
    d = client.delete(f"/api/jobs/{queued['job_id']}")
    assert d.status_code == 200 and d.json()["status"] == "cancelled"
    assert client.delete(f"/api/jobs/{running['job_id']}").status_code == 409
    assert client.delete("/api/jobs/nope").status_code == 404
    GATE.set()
    assert _wait(client, running["job_id"])["status"] == "done"
    assert client.get(f"/api/jobs/{queued['job_id']}").json()["status"] == "cancelled"


def test_registry_is_bounded(client):
    main.configure_service(mode="thread", workers=2, max_jobs=3)
    GATE.set()
    ids = [client.post("/api/jobs", json={"kind": "_test_gate", "params": {"tag": str(i)}}).json()["job_id"]
           for i in range(6)]
    for i in ids[-3:]:
        _wait(client, i)
    client.post("/api/jobs", json={"kind": "_test_gate", "params": {"tag": "last"}})
    assert client.get("/api/jobs").json()["counts"]["total"] <= 3
    assert client.get(f"/api/jobs/{ids[0]}").status_code == 404


def test_validation_and_unknown_ids(client):
    assert client.post("/api/jobs", json={"kind": "nope"}).status_code == 422
    assert client.post("/api/jobs", json={"kind": "ppa", "params": {"bogus": 1}}).status_code == 422
    assert client.post("/api/jobs", json={"kind": "joint", "params": {"maxiter": 1}}).status_code == 422
    assert client.get("/api/jobs/does-not-exist").status_code == 404
    assert client.get("/api/jobs/does-not-exist/events").status_code == 404


def test_health(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["version"] == main.CODE_VERSION
    assert h["executor"]["mode"] == "thread" and "full-flow" in h["kinds"]


def test_existing_endpoints_keep_their_shape(client):
    from layout_opt.flow_e2e import run_best_of
    sweep = client.get("/api/full-flow?place=sa&seed=0&sky130=false&sweep=2").json()
    assert sweep == _norm(run_best_of(seeds=[0, 1], workers=1))
    opt = client.post("/api/optimize", json={"seed": 0, "maxiter": 5})
    assert opt.status_code == 200 and set(opt.json()) == {"nEvals", "best", "frames"}
    assert opt.json() == _norm(main._compute_optimize(0, 5))
    assert client.post("/api/optimize", json={"seed": 0, "maxiter": 1}).status_code == 422


def test_process_mode_streams_stage_progress(client):
    """Real worker process: picklable kinds, stage hooks crossing the process boundary."""
    code_version.cache_clear()                 # workers must hash the same sources
    main.configure_service(mode="process", workers=1)
    j = client.post("/api/jobs", json={"kind": "full-flow", "params": {"seed": 0}}).json()
    events = _sse_events(client, j["job_id"])
    stages = [d["stage"] for t, d in events if t == "progress" and d["event"] == "stage"]
    assert {"sizing", "placement", "routing", "signoff", "postlayout"} <= set(stages)
    assert events[-1][1]["status"] == "done"
    snap = client.get(f"/api/jobs/{j['job_id']}").json()
    assert snap["result"]["verdict"] in ("PASS", "FAIL") and snap["stages"]
    assert main.SERVICE.stats()["mode"] == "process"
