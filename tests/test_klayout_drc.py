"""Real KLayout DRC engine on the exported GDS."""

import gdstk
import pytest

from layout_opt.klayout_drc import run_drc, run_drc_on_flow, klayout_available
from layout_opt.placement import run_flow

pytestmark = pytest.mark.skipif(not klayout_available(), reason="klayout not installed")


def _write(path, rects_met1):
    lib = gdstk.Library("t")
    top = lib.new_cell("T")
    for (x0, y0, x1, y1) in rects_met1:
        top.add(gdstk.rectangle((x0, y0), (x1, y1), layer=68, datatype=20))
    lib.write_gds(str(path))


def test_clean_metal_passes(tmp_path):
    # two wide wires (0.5 um), spaced 0.5 um apart -> no width/space violations
    out = tmp_path / "clean.gds"
    _write(out, [(0, 0, 5.0, 0.5), (0, 1.0, 5.0, 1.5)])
    r = run_drc(str(out))
    assert r["available"] and r["clean"] and r["total"] == 0


def test_thin_wire_flags_width(tmp_path):
    out = tmp_path / "thin.gds"
    _write(out, [(0, 0, 5.0, 0.05)])         # 0.05 um < 0.14 um min width
    r = run_drc(str(out))
    met1 = next(L for L in r["layers"] if L["layer"] == "met1")
    assert met1["width_violations"] > 0 and not r["clean"]


def test_close_wires_flag_spacing(tmp_path):
    out = tmp_path / "close.gds"
    _write(out, [(0, 0, 5.0, 0.5), (0, 0.55, 5.0, 1.05)])   # 0.05 um gap < 0.14
    r = run_drc(str(out))
    met1 = next(L for L in r["layers"] if L["layer"] == "met1")
    assert met1["space_violations"] > 0


def test_drc_on_real_flow_reports_metal():
    r = run_drc_on_flow(run_flow("sa", seed=1))
    assert r["available"] and r["tool"].startswith("KLayout")
    assert any(L["layer"] == "met1" for L in r["layers"])
