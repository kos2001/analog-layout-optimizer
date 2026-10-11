"""Offline end-to-end contract of the live Virtuoso path, via mock-virtuoso.

layout_opt geometry -> emit_skill_progn (SKILL text) -> VirtuosoClient over the
real RAMIC wire -> mock-virtuoso (a pure-Python SKILL interpreter) -> the
bridge's own layout_read_geometry + parse_layout_geometry_output reader. Every
shape must come back exactly where layout_opt put it: same count, layers and
bounding boxes, coordinate for coordinate.

Skips cleanly unless both mock-virtuoso and virtuoso-bridge are installed:
    uv pip install -e ../virtuoso-bridge-lite
    uv pip install -e ../../virtuso_bridge/mock-virtuoso
"""

from __future__ import annotations

from collections import Counter

import pytest

pytest.importorskip("mock_virtuoso")
pytest.importorskip("virtuoso_bridge")

from mock_virtuoso.auth import TOKEN_PATH_ENV  # noqa: E402
from mock_virtuoso.bridge_compat import match_client_auth  # noqa: E402
from mock_virtuoso.server import MockVirtuosoServer  # noqa: E402
from mock_virtuoso.session import Session  # noqa: E402
from virtuoso_bridge import ExecutionStatus, VirtuosoClient  # noqa: E402
from virtuoso_bridge.virtuoso.layout.ops import layout_read_geometry  # noqa: E402
from virtuoso_bridge.virtuoso.layout.reader import parse_layout_geometry_output  # noqa: E402
from virtuoso_bridge.virtuoso.ops import open_window  # noqa: E402

from layout_opt.generator import DesignParams, DiffPairConfig  # noqa: E402
from layout_opt.geometry import Layout, Rect  # noqa: E402
from layout_opt.routing import RoutingParams, routed_layout  # noqa: E402
from layout_opt.skill import emit_skill_progn, snap_coord  # noqa: E402

CLIENT_TOKEN_PATH_ENV = "VB_BRIDGE_TOKEN"   # virtuoso_bridge.daemon_auth
LIB, CELL = "LAYOUT_OPT", "DIFFPAIR"


@pytest.fixture
def bridge_client(tmp_path, monkeypatch):
    """A real VirtuosoClient talking to an in-process mock on a free port.

    Mirrors mock-virtuoso's own conftest: both ends read the token from a file
    inside tmp_path (never the developer's ~/.virtuoso-bridge/bridge_token), and
    the daemon adopts whatever secret the client carries - none for a tokenless
    bridge such as 0.7.0, which then gets the legacy wire it expects.
    """
    token_file = tmp_path / "bridge_token"
    monkeypatch.setenv(TOKEN_PATH_ENV, str(token_file))
    monkeypatch.setenv(CLIENT_TOKEN_PATH_ENV, str(token_file))
    session = Session(artifact_dir=tmp_path)
    server = MockVirtuosoServer(session)      # binds port 0; serves on start()
    client = VirtuosoClient.local(port=server.port)
    match_client_auth(server, client)
    server.start()
    try:
        yield client, session
    finally:
        server.stop()


def _layout() -> Layout:
    """The placed + routed diff pair (66 rects on OD/PO/M1/VIA12/M2), plus one
    rect beyond 1 mm whose 5 nm step a 6-significant-digit format would drop."""
    p = DesignParams(w_finger=0.5, l=0.03, finger_pitch=0.18,
                     guard_gap=0.20, gr_width=0.05)
    rp = RoutingParams(rail_width=0.10, rail_pitch=0.30, via_size=0.06)
    lay = routed_layout(p, rp, DiffPairConfig(nf=4))
    lay.add(Rect("M2", "drawing", 1000.005, 0.0, 1000.5, 2.0))
    return lay


def _expected(lay: Layout) -> Counter:
    """(layer, purpose, bbox) multiset as layout_opt intends it, on the 1 nm grid."""
    return Counter(
        (r.layer, r.purpose,
         ((float(snap_coord(r.x0)), float(snap_coord(r.y0))),
          (float(snap_coord(r.x1)), float(snap_coord(r.y1)))))
        for r in lay.rects)


def _read_back(client, lib: str, cell: str) -> list[dict]:
    result = client.execute_skill(layout_read_geometry(lib, cell))
    assert result.status == ExecutionStatus.SUCCESS, result.errors
    return parse_layout_geometry_output(result.output)


def _actual(rows: list[dict]) -> Counter:
    return Counter((r["layer"], r["purpose"], tuple(r["bbox"])) for r in rows)


def test_emitted_layout_round_trips_exactly(bridge_client):
    client, session = bridge_client
    lay = _layout()

    result = client.execute_skill(emit_skill_progn(lay, LIB, CELL))
    assert result.status == ExecutionStatus.SUCCESS, result.errors

    rows = _read_back(client, LIB, CELL)
    assert len(rows) == len(lay.rects) == 67
    assert {r["kind"] for r in rows} == {"shape"}
    assert {r["objType"] for r in rows} == {"rect"}
    assert {r["layer"] for r in rows} == {"OD", "PO", "M1", "VIA12", "M2"}
    assert _actual(rows) == _expected(lay)            # every bbox, exactly

    # the >1 mm edge survived the wire with its 5 nm step intact
    far = [r for r in rows if r["bbox"][0][0] > 999]
    assert far and far[0]["bbox"] == [(1000.005, 0.0), (1000.5, 2.0)]

    # the overall extent matches layout_opt's own bbox
    xs = [x for r in rows for x, _ in r["bbox"]]
    ys = [y for r in rows for _, y in r["bbox"]]
    x0, y0, x1, y1 = lay.bbox()
    assert (min(xs), min(ys), max(xs), max(ys)) == (
        float(snap_coord(x0)), float(snap_coord(y0)),
        float(snap_coord(x1)), float(snap_coord(y1)))

    # the block bound cv itself and saved the cellview
    assert session.design.find_cellview(LIB, CELL, "layout").saved is True


def test_reemitting_into_the_same_cell_is_idempotent(bridge_client):
    # mode "w" rebuilds the cell rather than appending a second copy
    client, _ = bridge_client
    lay = _layout()
    for _ in range(2):
        result = client.execute_skill(emit_skill_progn(lay, LIB, CELL))
        assert result.status == ExecutionStatus.SUCCESS, result.errors
    assert _actual(_read_back(client, LIB, CELL)) == _expected(lay)


def test_progn_without_lib_cell_draws_into_open_edit_window(bridge_client):
    client, _ = bridge_client
    opened = client.execute_skill(open_window(LIB, "EDITED"))
    assert opened.status == ExecutionStatus.SUCCESS, opened.errors

    lay = Layout("small", [Rect("M1", "drawing", 0.0, 0.0, 2.5, 1.0),
                           Rect("M2", "drawing", 1234.565, 0.5, 1235.0, 0.75)])
    result = client.execute_skill(emit_skill_progn(lay))
    assert result.status == ExecutionStatus.SUCCESS, result.errors
    assert _actual(_read_back(client, LIB, "EDITED")) == _expected(lay)


def test_progn_without_any_cellview_fails_loudly(bridge_client):
    # no lib/cell and no open window: cv is nil, so the run must error rather
    # than report success with nothing drawn
    client, _ = bridge_client
    lay = Layout("small", [Rect("M1", "drawing", 0.0, 0.0, 1.0, 1.0)])
    result = client.execute_skill(emit_skill_progn(lay))
    assert result.status != ExecutionStatus.SUCCESS
