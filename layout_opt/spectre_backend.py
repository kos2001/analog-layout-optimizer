"""Spectre backend adapter — first implementation of the closed loop.

Swaps the analytical OTA model (`opamp.evaluate_opamp`) for a **real Spectre**
AC characterization driven through virtuoso-bridge, keeping the identical
``OpAmpParams -> OpAmpSpecs`` contract so the optimizer / surrogate / study code
is unchanged.

What comes from Spectre (parasitic-sensitive): DC gain, GBW, phase margin —
extracted from an AC sweep of |Vout| / phase. What stays analytical (exact given
the sizing): power = VDD*(Itail+I6), slew = Itail/Cc, device overdrives.

Requires, to actually run:
  * `virtuoso-bridge` reachable with Spectre on PATH (or VB_CADENCE_CSHRC), and
  * a PDK model file (``model_include``) + device model names for your process.
The netlist below is a template to adapt to your PDK; the metric-extraction and
the contract are what this module guarantees (and unit-tests offline).
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np

from .opamp import VDD, OpAmpParams, OpAmpSpecs, _vov, KP_N, KP_P
from .pdk import PDKConfig, GENERIC_PDK


class SpectreUnavailable(RuntimeError):
    """Raised when no reachable Spectre/bridge backend is available."""


def preflight() -> dict:
    """Check readiness for a real Spectre run (bridge config + spectre license).

    Returns a dict with booleans + human-readable guidance; does not raise.
    """
    import os
    from pathlib import Path

    env = Path(os.path.expanduser("~/.virtuoso-bridge/.env"))
    status = {"bridge_env": env.exists(), "spectre": False, "ready": False,
              "guidance": []}
    try:
        from virtuoso_bridge.spectre.runner import SpectreSimulator
        sim = SpectreSimulator.from_env()
        status["spectre"] = bool(sim.check_license())
    except Exception as e:  # noqa: BLE001
        status["guidance"].append(f"SpectreSimulator unavailable: {e}")
    if not status["bridge_env"]:
        status["guidance"].append(
            "Run `virtuoso-bridge init user@eda-server [-J jump]` then "
            "`virtuoso-bridge start` (see virtuoso-bridge-lite/AGENTS.md)."
        )
    if not status["spectre"]:
        status["guidance"].append(
            "Spectre not reachable: ensure `spectre` on the remote PATH or set "
            "VB_CADENCE_CSHRC; verify with `virtuoso-bridge status`."
        )
    status["ready"] = status["bridge_env"] and status["spectre"]
    if status["ready"]:
        status["guidance"].append("Ready: pass a real PDKConfig to spectre_evaluate.")
    return status


# Two-stage Miller OTA, AC-characterized. L is fixed; W = (W/L) * L.
# {placeholders} are filled by render_netlist. Adapt device models to your PDK.
OTA_NETLIST_TEMPLATE = """\
// Two-stage Miller OTA - AC characterization (rendered by spectre_backend)
simulator lang=spectre
global 0
{model_include}

// AC stimulus: 1 V differential applied at the input pair
Vcm   (vcm  0) vsource dc={vcm}
Vinp  (vinp vcm) vsource dc=0 mag=0.5  ac=0.5
Vinn  (vinn vcm) vsource dc=0 mag=-0.5 ac=-0.5
Vsup  (vdd  0) vsource dc={vdd}

// Bias current into the tail mirror
Ibias (vdd nbias) isource dc={itail}
M5b   (nbias nbias 0 0) {nmos} w={w5}u l={l}u
M5    (tail  nbias 0 0) {nmos} w={w5}u l={l}u

// Input pair
M1 (outm vinp tail 0) {nmos} w={w1}u l={l}u
M2 (outp vinn tail 0) {nmos} w={w1}u l={l}u
// Mirror load
M3 (outm outm vdd vdd) {pmos} w={w3}u l={l}u
M4 (outp outm vdd vdd) {pmos} w={w3}u l={l}u

// Second stage (M6 driver, M7 current-source load)
M6 (vout outp 0 0)   {nmos} w={w6}u l={l}u
M7 (vout nbias7 vdd vdd) {pmos} w={w7}u l={l}u
Vb7 (nbias7 0) vsource dc={vb7}

Cc (outp vout) capacitor c={cc}f
CL (vout 0)    capacitor c={cl}f

ac ac dec 30 1 10G
"""


def render_netlist(p: OpAmpParams, pdk: PDKConfig) -> str:
    """Render the OTA netlist for sizing *p* against *pdk*. W (µm) = (W/L) * L."""
    l = pdk.l_um
    return OTA_NETLIST_TEMPLATE.format(
        model_include=pdk.model_include,
        nmos=pdk.nmos, pmos=pdk.pmos, l=l,
        vdd=pdk.vdd, vcm=pdk.vdd / 2.0, vb7=pdk.vb7,
        w1=round(p.wl1 * l, 4), w3=round(p.wl3 * l, 4),
        w5=round(p.wl5 * l, 4), w6=round(p.wl6 * l, 4),
        w7=round(p.wl7 * l, 4),
        itail=p.itail, cc=p.cc * 1e15, cl=pdk.cl_ff,
    )


def extract_ac_metrics(freq, vout_complex):
    """Pure: from an AC sweep (freq[Hz], complex Vout) compute (gain_dB, GBW_Hz, PM_deg).

    DC gain = |H| at the lowest frequency. GBW = frequency where |H| crosses 1
    (0 dB). Phase margin = 180 + phase(at GBW) in degrees.
    """
    f = np.asarray(freq, dtype=float)
    h = np.asarray(vout_complex, dtype=complex)
    order = np.argsort(f)
    f, h = f[order], h[order]
    mag = np.abs(h)
    gain_db = 20.0 * math.log10(max(mag[0], 1e-30))

    # Unity-gain crossing (|H| = 1).
    below = np.where(mag < 1.0)[0]
    if below.size == 0:
        gbw = float(f[-1])
        ph = np.angle(h[-1], deg=True)
    else:
        i = below[0]
        if i == 0:
            gbw = float(f[0]); ph = np.angle(h[0], deg=True)
        else:
            # interpolate crossing in log-freq on log-mag
            lf0, lf1 = math.log10(f[i - 1]), math.log10(f[i])
            lm0, lm1 = math.log10(mag[i - 1]), math.log10(mag[i])
            frac = (0.0 - lm0) / (lm1 - lm0) if lm1 != lm0 else 0.0
            gbw = 10.0 ** (lf0 + frac * (lf1 - lf0))
            ph = np.angle(h[i - 1], deg=True) + frac * (
                np.angle(h[i], deg=True) - np.angle(h[i - 1], deg=True)
            )
    pm = 180.0 + ph
    return gain_db, float(gbw), float(pm)


def _freq_and_vout(result) -> tuple[list, list]:
    """Best-effort pull of (freq, complex Vout) from a SimulationResult.data dict.

    Real PSF shapes vary by Spectre version; adapt the key matching to yours.
    """
    data = getattr(result, "data", None) or {}
    if not isinstance(data, dict) or not data:
        raise SpectreUnavailable("Spectre result has no data (sim did not run)")
    freq_key = next((k for k in data if "freq" in k.lower()), None)
    vout_key = next((k for k in data if k.lower() in ("vout", "out", "v(vout)")), None)
    if freq_key is None or vout_key is None:
        raise SpectreUnavailable(f"could not find freq/vout in PSF signals {list(data)}")
    raw = data[vout_key]
    vout = [complex(v) for v in raw]
    return list(data[freq_key]), vout


def spectre_evaluate(
    p: OpAmpParams,
    pdk: PDKConfig,
    *,
    sim=None,
    work_dir: str | None = None,
) -> OpAmpSpecs:
    """Run real Spectre AC against *pdk* and return specs (same contract as
    evaluate_opamp). Raises SpectreUnavailable if no backend is reachable."""
    if sim is None:
        try:
            from virtuoso_bridge.spectre.runner import SpectreSimulator
            sim = SpectreSimulator.from_env(work_dir=Path(work_dir) if work_dir else None)
        except Exception as e:  # noqa: BLE001
            raise SpectreUnavailable(f"cannot create SpectreSimulator: {e}") from e

    netlist = render_netlist(p, pdk)
    tmp = Path(work_dir or tempfile.mkdtemp(prefix="ota_spectre_"))
    tmp.mkdir(parents=True, exist_ok=True)
    nl_path = tmp / "ota.scs"
    nl_path.write_text(netlist)

    result = sim.run_simulation(nl_path, {})
    if not getattr(result, "ok", False):
        raise SpectreUnavailable(
            f"Spectre run failed: {getattr(result, 'errors', None)}"
        )
    freq, vout = _freq_and_vout(result)
    gain_db, gbw, pm = extract_ac_metrics(freq, vout)

    # Exact-given-sizing quantities stay analytical.
    i1 = p.itail / 2.0
    return OpAmpSpecs(
        gain_db=gain_db, gbw_hz=gbw, pm_deg=pm,
        slew=p.itail / p.cc,
        power=VDD * (p.itail + p.i6),
        vov1=_vov(KP_N, p.wl1, i1), vov3=_vov(KP_P, p.wl3, i1),
        vov5=_vov(KP_N, p.wl5, p.itail), vov6=_vov(KP_N, p.wl6, p.i6),
        vov7=_vov(KP_P, p.wl7, p.i6),
    )


def make_spectre_objective(pdk: PDKConfig, *, sim=None, work_dir: str | None = None):
    """Drop-in objective(x) for the optimizer, backed by real Spectre.

    Mirrors opamp_opt._objective but with spectre_evaluate. Use with the same
    optimizer/surrogate code; keep the eval count small (surrogate-assisted).
    """
    from .opamp_opt import _violation_from_specs, POWER_SCALE

    def objective(x) -> float:
        p = OpAmpParams.from_vector(x)
        specs = spectre_evaluate(p, pdk, sim=sim, work_dir=work_dir)
        v = _violation_from_specs(specs, p)
        pw = specs.power / POWER_SCALE
        return 1e3 * v + 10.0 if v > 0 else pw

    return objective
