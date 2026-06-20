"""Process-change effects beyond DRC: device re-size + taxonomy."""
from layout_opt.process_change import device_resize, effect_taxonomy, process_effects, parse_process_nl


def test_taxonomy_covers_categories():
    cats = {t["category"] for t in effect_taxonomy()}
    assert {"DRC geometry", "Device model", "Supply voltage", "Metal stack"} <= cats
    assert any(not t["modeled"] for t in effect_taxonomy())   # some noted-only


def test_device_resize_responds_to_model_change():
    r = device_resize({"kp_n_mult": 1.5, "lambda_mult": 1.4, "vdd": 0.9})
    # gain drops when lambda rises (lower output resistance)
    assert r["after"]["gain_db"] < r["before"]["gain_db"]
    assert r["vdd_after"] == 0.9


def test_device_resize_restores_globals():
    import layout_opt.opamp as O
    kp, vdd = O.KP_N, O.VDD
    device_resize({"kp_n_mult": 2.0, "vdd": 0.8})
    assert O.KP_N == kp and O.VDD == vdd     # restored


def test_process_effects_combines_geometry_and_taxonomy():
    r = process_effects(parse_process_nl("min poly pitch 0.3 um"),
                        {"vdd": 0.9}, maxiter=80)
    assert "geometry" in r and "device" in r and len(r["taxonomy"]) >= 6
    assert r["device"] is not None
