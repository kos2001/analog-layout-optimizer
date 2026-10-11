"""Provenance digests + the shared-in-flight result cache."""

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np
import pytest

from layout_opt.provenance import ResultCache, cache_key, code_version, digest


def test_digest_is_canonical():
    assert digest({"a": 1, "b": [1, 2]}) == digest({"b": [1, 2], "a": 1})
    assert digest((1, 2)) == digest([1, 2])
    assert digest({3, 1, 2}) == digest({2, 3, 1})
    assert digest({"x": np.float64(1.5), "v": np.arange(3)}) == digest({"x": 1.5, "v": [0, 1, 2]})
    assert digest({"a": 1}) != digest({"a": 1.5})
    assert len(digest(None)) == 64


def test_cache_key_includes_code_version_and_env():
    k = cache_key("ppa", {"seed": 0})
    assert k == cache_key("ppa", {"seed": 0}, version=code_version())
    assert k != cache_key("ppa", {"seed": 0}, version="other")
    assert k != cache_key("ppa", {"seed": 0}, env={"PDK_ROOT": "/x"})
    assert k != cache_key("pvt", {"seed": 0})


def test_lru_is_bounded_and_refreshes_on_hit():
    c = ResultCache(maxsize=2)
    for k in "abc":
        c.get_or_compute(k, lambda k=k: k.upper())
    assert c.peek("a") == (False, None) and c.stats()["size"] == 2
    c.get_or_compute("b", lambda: "never")     # hit refreshes b
    c.get_or_compute("d", lambda: "D")          # evicts c, not b
    assert c.peek("b") == (True, "B") and c.peek("c")[0] is False


def test_concurrent_identical_requests_share_one_computation():
    c, calls, gate = ResultCache(), [], threading.Event()

    def slow():
        calls.append(1)
        gate.wait(5)
        return 42

    with ThreadPoolExecutor(8) as ex:
        futs = [ex.submit(c.get_or_compute, "k", slow) for _ in range(8)]
        time.sleep(0.1)
        gate.set()
        assert [f.result() for f in futs] == [42] * 8
    assert len(calls) == 1
    st = c.stats()
    assert st["misses"] == 1 and st["shared"] == 7 and st["inflight"] == 0


def test_errors_are_propagated_and_never_cached():
    c, n = ResultCache(), []

    def boom():
        n.append(1)
        raise ValueError("boom")

    for _ in range(2):
        with pytest.raises(ValueError, match="boom"):
            c.get_or_compute("k", boom)
    assert len(n) == 2 and c.peek("k")[0] is False and c.stats()["errors"] == 2
    assert c.get_or_compute("k", lambda: "ok") == "ok"


def test_cacheable_veto_and_external_futures():
    c = ResultCache()
    c.get_or_compute("t", lambda: {"status": "tool_unavailable"},
                     cacheable=lambda r: "unavailable" not in r["status"])
    assert c.peek("t")[0] is False

    ext: Future = Future()
    f1, how1 = c.submit("x", lambda: ext)
    f2, how2 = c.submit("x", lambda: pytest.fail("must share the in-flight future"))
    assert (how1, how2) == ("miss", "shared") and f1 is f2
    ext.set_result(7)
    f3, how3 = c.submit("x", lambda: pytest.fail("must hit"))
    assert how3 == "hit" and f3.result() == 7
