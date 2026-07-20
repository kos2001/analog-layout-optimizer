"""Regressions found wiring the improved flow together end to end."""

import pytest

from layout_opt.ngspice_backend import (
    ngspice_available, sky130_available, sky130_model, ngspice_evaluate,
    render_netlist,
)
from layout_opt.opamp import OpAmpParams
from layout_opt.placement import run_flow

# Guard-banded sizings need big output devices; this one broke SKY130.
BIG = OpAmpParams(wl1=86.8, wl3=24, wl5=40, wl6=743.4, wl7=90,
                  itail=177.8e-6, i6=200e-6, cc=3.53e-12)


@pytest.mark.skipif(not sky130_available(), reason="SKY130 PDK not installed")
def test_render_splits_wide_devices_within_sky130_bins():
    # SKY130 binned models reject total w > 100 um per instance; wide devices
    # must be emitted as m parallel instances with w <= 100 and legal fingers.
    net = render_netlist(BIG, sky130_model(), "/dev/null")
    for line in net.splitlines():
        if not line.startswith("x"):
            continue
        params = dict(t.split("=") for t in line.split()[6:])
        assert float(params["w"]) <= 100.0 + 1e-9
        finger = float(params["w"]) / float(params["nf"])
        assert 0.42 - 1e-9 <= finger <= 7.0 + 1e-9


@pytest.mark.skipif(not (ngspice_available() and sky130_available()),
                    reason="ngspice/SKY130 not installed")
def test_guardband_scale_sizing_simulates_on_sky130():
    s = ngspice_evaluate(BIG, sky130_model())   # raised NgspiceUnavailable before
    assert s.gain_db > 0


def test_signoff_via_spacing_matches_real_deck():
    # The full SKY130 KLayout deck reports 0 BEOL violations on this flow
    # (0.15 um cuts on a 0.5 um grid can't violate via.2 = 0.17 um), so the
    # grid precheck must not fail sign-off on adjacent-cell vias.
    for seed in range(4):
        f = run_flow(place="sa", seed=seed, analog_aware=True)
        assert f["signoff"]["drc"]["counts"]["via_spacing"] == 0, f"seed {seed}"
