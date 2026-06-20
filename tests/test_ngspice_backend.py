"""ngspice backend (open-source closed loop) — offline-verifiable parts.

Render + parse + the full ngspice_evaluate pipeline are checked with a fake
runner (synthesized wrdata), so no ngspice install is required. A live test runs
only if ngspice is actually on PATH.
"""

import math

import numpy as np
import pytest

from layout_opt.opamp import OpAmpParams
from layout_opt.ngspice_backend import (
    GENERIC_NGSPICE, NgspiceUnavailable, ngspice_available, ngspice_evaluate,
    render_netlist, _parse_wrdata,
)


def params() -> OpAmpParams:
    return OpAmpParams(wl1=20, wl3=20, wl5=20, wl6=80, wl7=40,
                       itail=20e-6, i6=80e-6, cc=1e-12)


def test_render_has_models_params_and_ac():
    nl = render_netlist(params(), GENERIC_NGSPICE, "/tmp/x.txt")
    assert "nmos_g" in nl and "pmos_g" in nl
    assert "ac dec" in nl and "wrdata" in nl
    assert "w=3.6u" in nl                     # wl1=20 * 0.18


def test_parse_wrdata():
    txt = "1.0 2.0 1.0 -3.0\n10.0 0.5 10.0 0.1\n"
    freq, vout = _parse_wrdata(txt)
    assert freq == [1.0, 10.0]
    assert vout[0] == complex(2.0, -3.0)


def _fake_wrdata(A0=1000.0, fp=1e5):
    """One-pole response written in ngspice wrdata (freq vr freq vi) format."""
    f = np.logspace(0, 10, 600)
    h = A0 / (1 + 1j * f / fp)
    return "\n".join(f"{fi:.6e} {hi.real:.6e} {fi:.6e} {hi.imag:.6e}"
                     for fi, hi in zip(f, h))


def test_evaluate_full_pipeline_with_fake_runner():
    s = ngspice_evaluate(params(), GENERIC_NGSPICE,
                         runner=lambda _cir: _fake_wrdata(1000.0, 1e5))
    assert s.gain_db == pytest.approx(20 * math.log10(1000.0), abs=0.3)
    assert s.gbw_hz == pytest.approx(1000.0 * 1e5, rel=0.05)
    assert s.pm_deg == pytest.approx(90.0, abs=5.0)        # single pole -> ~90
    # power/slew stay analytical (exact given sizing)
    assert s.power == pytest.approx(1.8 * (20e-6 + 80e-6))


def test_unavailable_when_no_binary(monkeypatch):
    import layout_opt.ngspice_backend as nb
    monkeypatch.setattr(nb.shutil, "which", lambda _x: None)
    with pytest.raises(NgspiceUnavailable):
        ngspice_evaluate(params(), GENERIC_NGSPICE, work_dir="/tmp/ng_none")


@pytest.mark.skipif(not ngspice_available(), reason="ngspice not installed")
def test_live_ngspice_runs_and_gives_sane_gain():
    s = ngspice_evaluate(params(), GENERIC_NGSPICE)
    assert s.gain_db > 20.0           # a real amplifier, not a degenerate node
    assert s.gbw_hz > 1e6
