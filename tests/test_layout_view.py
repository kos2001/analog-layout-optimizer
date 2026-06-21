"""In-browser layout viewer shape extraction."""
from layout_opt.layout_view import layout_shapes


def test_ota_shapes_have_sky130_layers():
    d = layout_shapes("ota")
    assert d["topCell"] == "OTA" and d["nPolygons"] > 100
    names = {L["name"] for L in d["layers"]}
    assert {"diff", "poly", "met1", "met2", "met3", "li1"} <= names
    assert len(d["bbox"]) == 4


def test_mirror_shapes():
    d = layout_shapes("mirror")
    assert d["nPolygons"] > 10 and any(L["name"] == "diff" for L in d["layers"])


def test_layers_carry_polygons_and_colors():
    d = layout_shapes("ota")
    met1 = next(L for L in d["layers"] if L["name"] == "met1")
    assert met1["color"].startswith("#") and len(met1["polys"]) > 0
    assert all(len(p) >= 3 for p in met1["polys"])      # real polygons
