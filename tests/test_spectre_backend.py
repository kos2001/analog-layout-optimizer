"""Spectre backend adapter — offline-verifiable, incl. the FULL pipeline.

Netlist rendering, AC-metric extraction, AND the end-to-end spectre_evaluate
(render -> run -> parse -> specs) are verified here using a fake Spectre that
returns a synthesized SimulationResult — no real Spectre/PDK needed. The real
run path requires virtuoso-bridge + a PDK, which preflight() reports on.
"""

import math
from types import SimpleNamespace

import numpy as np
import pytest

from layout_opt.opamp import OpAmpParams
from layout_opt.pdk import GENERIC_PDK, TEMPLATE_PDK, PDKConfig
from layout_opt.spectre_backend import (
    SpectreUnavailable,
    extract_ac_metrics,
    preflight,
    render_netlist,
    spectre_evaluate,
)


def params() -> OpAmpParams:
    return OpAmpParams(wl1=20, wl3=20, wl5=20, wl6=80, wl7=40,
                       itail=20e-6, i6=80e-6, cc=1e-12)


# --- netlist rendering ------------------------------------------------------
def test_render_substitutes_sizing_and_pdk():
    nl = render_netlist(params(), GENERIC_PDK)
    assert GENERIC_PDK.nmos in nl and GENERIC_PDK.pmos in nl
    assert "ac ac dec" in nl
    assert "w=3.6u" in nl                  # wl1=20 * 0.18 um
    assert "c=1000.0f" in nl or "c=1000f" in nl


def test_template_pdk_has_placeholders():
    assert "/path/to/your/pdk" in TEMPLATE_PDK.model_include


# --- AC metric extraction (pure) -------------------------------------------
def test_extract_metrics_single_pole():
    A0, fp = 1000.0, 1e5
    f = np.logspace(2, 9, 4000)
    h = A0 / (1 + 1j * f / fp)
    gain_db, gbw, pm = extract_ac_metrics(f, h)
    assert gain_db == pytest.approx(20 * math.log10(A0), abs=0.1)
    assert gbw == pytest.approx(A0 * fp, rel=0.05)
    assert pm == pytest.approx(90.0, abs=3.0)


# --- FULL pipeline via a fake Spectre --------------------------------------
class _FakeSim:
    """Stands in for SpectreSimulator: returns a synthesized AC result."""

    def __init__(self, A0=3000.0, fp=2e5):
        self.A0, self.fp = A0, fp
        self.netlist_seen = None

    def run_simulation(self, netlist, _params):
        self.netlist_seen = netlist.read_text() if hasattr(netlist, "read_text") else str(netlist)
        f = np.logspace(1, 10, 3000)
        h = self.A0 / (1 + 1j * f / self.fp)        # 1-pole
        return SimpleNamespace(
            ok=True,
            data={"freq": list(f), "vout": [complex(v) for v in h]},
            errors=[],
        )


def test_spectre_evaluate_full_pipeline_with_fake():
    sim = _FakeSim(A0=3000.0, fp=2e5)
    specs = spectre_evaluate(params(), GENERIC_PDK, sim=sim)
    # gain/GBW/PM come from the (fake) AC sweep:
    assert specs.gain_db == pytest.approx(20 * math.log10(3000.0), abs=0.2)
    assert specs.gbw_hz == pytest.approx(3000.0 * 2e5, rel=0.05)
    assert specs.pm_deg == pytest.approx(90.0, abs=3.0)
    # power/slew/overdrives stay analytical (exact given the sizing):
    assert specs.power == pytest.approx(1.8 * (20e-6 + 80e-6))
    assert specs.slew == pytest.approx(20e-6 / 1e-12)
    assert specs.vov6 > 0
    # the fake actually received the rendered netlist
    assert "ac ac dec" in sim.netlist_seen


class _FailSim:
    def run_simulation(self, _netlist, _params):
        return SimpleNamespace(ok=False, data={}, errors=["XSTRM: run failed"])


def test_spectre_evaluate_fails_clearly_on_bad_result():
    with pytest.raises(SpectreUnavailable):
        spectre_evaluate(params(), GENERIC_PDK, sim=_FailSim())


# --- readiness / not-connected --------------------------------------------
def test_preflight_reports_not_ready_without_backend():
    st = preflight()
    assert "ready" in st and st["ready"] is False
    assert st["guidance"]                      # actionable guidance present


def test_spectre_unavailable_when_no_backend():
    with pytest.raises(SpectreUnavailable):
        spectre_evaluate(params(), TEMPLATE_PDK, work_dir="/tmp/ota_sx_test")
