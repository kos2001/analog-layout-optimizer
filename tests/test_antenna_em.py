"""Antenna (metal/gate area) and EM (current density) sign-off checks on the OTA."""

from layout_opt.antenna import antenna_ota
from layout_opt.em import em_check, branch_currents
from layout_opt.opamp import OpAmpParams


def test_antenna_reports_per_gate_net_ratios():
    r = antenna_ota()
    assert r["nets"], "expected at least one gate net"
    # every reported net has a gate-oxide area and a cumulative-metal ratio
    for n in r["nets"]:
        assert n["gate_um2"] > 0
        assert n["max_ratio"] >= 0
    # cumulative ratio is monotonic across metal layers
    layers = r["nets"][0]["layers"]
    ratios = [L["ratio"] for L in layers]
    assert ratios == sorted(ratios)


def test_antenna_clean_under_default_limit():
    r = antenna_ota()
    assert r["clean"] is True
    assert r["worst_ratio"] < r["ratio_limit"]


def test_antenna_flags_when_limit_tiny():
    from layout_opt.antenna import antenna_ota as _a
    r = _a(ratio_limit=0.1)                          # absurdly strict -> must flag
    assert r["clean"] is False
    assert r["violations"] > 0


def test_branch_currents_follow_topology():
    p = OpAmpParams(wl1=20, wl3=20, wl5=20, wl6=40, wl7=40,
                    itail=100e-6, i6=200e-6, cc=1e-12)
    c = branch_currents(p)
    assert c["VDD"] == p.itail + p.i6                # supply carries both stages
    assert c["TAIL"] == p.itail
    assert abs(c["n1"] - p.itail / 2) < 1e-18        # half the tail per branch
    assert c["VOUT"] == p.i6


def test_em_check_density_and_verdict():
    r = em_check()
    assert r["nets"]
    names = {n["net"] for n in r["nets"]}
    assert {"VDD", "VSS", "TAIL"} <= names           # power/bias rails present
    for n in r["nets"]:
        assert n["capacity_mA"] > 0
        # density % is consistent with current / capacity
        assert abs(n["density_pct"] - 100 * n["current_mA"] / n["capacity_mA"]) < 0.2
    assert r["clean"] is True                         # low-current OTA passes EM
