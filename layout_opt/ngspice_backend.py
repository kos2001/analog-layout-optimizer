"""Open-source closed loop: evaluate the OTA with **ngspice** (no Cadence).

Same `OpAmpParams -> OpAmpSpecs` contract as `spectre_backend`, so the optimizer
/ surrogate / study code is unchanged — but the simulator is the free, open
ngspice (github.com/imr/ngspice) instead of Spectre, and the model is an inline
level-1 MOSFET (or a real open PDK like SkyWater SKY130 via `.lib`).

gain / GBW / phase-margin come from a real ngspice `.ac` sweep; power / slew /
overdrives stay analytical (exact given the sizing), as in the Spectre backend.

This makes the whole flow runnable with zero commercial licenses:
    layout_opt optimizer  ->  ngspice_evaluate()  ->  ngspice (.ac)  ->  specs
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .opamp import (
    VDD, VTH_N, VTH_P, OpAmpParams, OpAmpSpecs, _vov, KP_N, KP_P, cm_window, headroom,
)
from .spectre_backend import extract_ac_metrics   # pure (freq, complex) -> metrics


class NgspiceUnavailable(RuntimeError):
    """Raised when the ngspice binary is not on PATH or the run failed."""


@dataclass(frozen=True)
class NgspiceModel:
    """Device models for the ngspice netlist (level-1 generic, or a PDK .lib)."""
    name: str
    header: str          # .model / .include / .lib lines
    nmos: str
    pmos: str
    l_um: float = 0.18
    vdd: float = VDD
    cl_ff: float = 1000.0
    subckt: bool = False     # True: PDK devices are X-instance subckts (W/L in um)
    w_min: float = 0.0       # minimum device width (um), clamp for real PDKs
    temp: float = 27.0       # circuit temperature (deg C) for the sim
    w_max: float = 0.0       # max total width per instance (um); 0 = unlimited
    w_finger: float = 5.0    # target finger width (um) when splitting into nf
    vth_n: float = VTH_N     # device thresholds (V) used to place the input
    vth_p: float = VTH_P     # common mode inside the all-saturated window
    # Channel length (um) of the gain-setting devices — input pair, mirror
    # load and output load M7 — whose output resistance sets the DC gain.
    # 0 = same as l_um. M5 and M6 stay at l_um: M6 sits on the Miller-split
    # node, where a long, wide device's Cgs would pull in the second pole.
    l_gain_um: float = 0.0
    vth_n6: float = 0.0      # M6 threshold when l_gain_um differs (0 = vth_n)


# Generic square-law (level=1) models — mirror the analytical opamp constants
# (KP in A/V^2, lambda in 1/V), so ngspice ≈ the analytical model. Not silicon.
GENERIC_NGSPICE = NgspiceModel(
    name="generic-level1",
    header=(
        f".model nmos_g nmos level=1 kp={KP_N} vto=0.4 lambda=0.10 gamma=0\n"
        f".model pmos_g pmos level=1 kp={KP_P} vto=-0.4 lambda=0.12 gamma=0"
    ),
    nmos="nmos_g", pmos="pmos_g", l_um=0.18, vdd=VDD,
)

import os


def sky130_lib_path(pdk_root: str | None = None) -> str:
    root = pdk_root or os.environ.get("PDK_ROOT") or os.path.expanduser("~/pdk")
    return os.path.join(root, "sky130A", "libs.tech", "ngspice", "sky130.lib.spice")


def sky130_available(pdk_root: str | None = None) -> bool:
    return os.path.isfile(sky130_lib_path(pdk_root))


# SKY130 tt |Vth| (V) of nfet_01v8 / pfet_01v8 vs channel length, from the BSIM
# operating point at |Vgs| = |Vds| = 0.9 V. The testbench places its common
# mode with these, so they must follow L (Vtn falls ~85 mV from 0.5 to 2 um).
SKY130_TT_VTH = {0.5: (0.628, 0.982), 0.75: (0.598, 1.018), 1.0: (0.577, 1.030),
                 1.5: (0.552, 1.043), 2.0: (0.544, 1.049), 3.0: (0.534, 1.056)}


# Channel length (um) of SKY130's gain-setting devices in the full flow. At
# 0.5 um the two-stage OTA's silicon gain stalls near 73 dB (output resistance,
# not sizing: +/-25% on every knob moves it < 0.5 dB); at 1.5 um gain reaches
# 83 dB but the larger devices cost ~10 deg of phase margin. 1.1 um balances
# them: >= 80.8 dB and >= 51 MHz on every sweep seed, PM 58-66 deg, so the
# silicon-aware sweep picks a design meeting all three specs. 1.0 um sits on
# a model-bin edge (non-convergent / erratic), so it is avoided.
SKY130_GAIN_L_UM = 1.1


def sky130_vth(l_um: float) -> tuple[float, float]:
    """(Vtn, |Vtp|) at *l_um*, linearly interpolated (clamped at the ends)."""
    ls = sorted(SKY130_TT_VTH)
    if l_um <= ls[0]:
        return SKY130_TT_VTH[ls[0]]
    if l_um >= ls[-1]:
        return SKY130_TT_VTH[ls[-1]]
    hi = next(x for x in ls if x >= l_um)
    lo = ls[ls.index(hi) - 1]
    f = (l_um - lo) / (hi - lo) if hi != lo else 0.0
    (n0, p0), (n1, p1) = SKY130_TT_VTH[lo], SKY130_TT_VTH[hi]
    return n0 + f * (n1 - n0), p0 + f * (p1 - p0)


def sky130_model(corner: str = "tt", pdk_root: str | None = None,
                 l_um: float = 0.5, cl_ff: float = 1000.0,
                 l_gain_um: float | None = None) -> NgspiceModel:
    """Real SkyWater SKY130 device models (open PDK) — silicon, not square-law.

    Devices are 1.8 V core FETs (`sky130_fd_pr__{n,p}fet_01v8`) via the PDK's
    ngspice `.lib`. Requires the PDK installed (e.g. `volare enable`); point
    PDK_ROOT at it. L defaults to 0.5 um (more intrinsic gain than 0.15 um min).
    *l_gain_um* lengthens only the gain-setting devices (see NgspiceModel).
    """
    lg = l_gain_um or l_um
    vtn, vtp = sky130_vth(lg)
    return NgspiceModel(
        name=f"sky130-{corner}",
        header=f'.lib "{sky130_lib_path(pdk_root)}" {corner}',
        nmos="sky130_fd_pr__nfet_01v8", pmos="sky130_fd_pr__pfet_01v8",
        l_um=l_um, vdd=1.8, cl_ff=cl_ff, subckt=True, w_min=0.42,
        w_max=100.0,   # binned models reject total w > 100 um per instance
        vth_n=vtn, vth_p=vtp, l_gain_um=lg if lg != l_um else 0.0,
        vth_n6=sky130_vth(l_um)[0] if lg != l_um else 0.0,
    )


def _dev(model: NgspiceModel, idx: str, d: str, g: str, s: str, b: str,
         kind: str, w_um: float, l_um: float) -> str:
    """One device line — primitive `m` (level-1) or PDK `X` subckt.

    Wide PDK devices are split into `m` parallel instances (total width per
    instance <= w_max) and `nf` fingers (finger width near w_finger), because
    the binned SKY130 models reject out-of-range geometries outright.
    """
    name = model.nmos if kind == "n" else model.pmos
    if model.subckt:
        w = max(round(w_um, 4), model.w_min)
        mult = 1
        if model.w_max and w > model.w_max:
            mult = math.ceil(w / model.w_max)
            w = round(w / mult, 4)
        nf = max(1, math.ceil(w / model.w_finger))
        return (f"x{idx} {d} {g} {s} {b} {name} "
                f"l={round(l_um, 4)} w={w} nf={nf} m={mult}")
    return f"m{idx} {d} {g} {s} {b} {name} w={round(w_um, 4)}u l={round(l_um, 4)}u"


_NETLIST = """\
* Two-stage Miller OTA — ngspice open-loop AC gain testbench.
* DC feedback (huge L sets vout DC = vinn) biases the output to vcm; at AC the
* huge C grounds vinn to vcm (open loop), so vout/vinp = open-loop gain.
{header}
.options gmin=1e-10 reltol=1e-3 abstol=1e-9 vntol=1e-6 itl1=500 temp={temp}
vdd vdd 0 {vdd}
vcm vcm 0 {vcm}
vinp vinp vcm dc 0 ac 1
* DC feedback (Lfb short) sets vout DC = vinn -> loop drives vout to vcm;
* Cfb grounds vinn to vcm at AC (open loop). nodeset seeds the high-Z output.
Lfb vout vinn 1e9
Cfb vinn vcm 1e9
.nodeset v(vout)={vcm} v(vinn)={vcm} v(outp)={v_outp} v(outm)={v_outm} v(tail)={v_tail} v(nb5)={v_nb5} v(pb7)={v_pb7}
{devices}
* Bias: ideal references feed 1:1 diode mirrors (mb5 / mb7); the tail M5 and
* the output load M7 are real transistors, so their headroom and output
* resistance are simulated rather than assumed ideal.
iref5 vdd nb5 dc {itail}
iref7 pb7 0 dc {i6}
cc outp vout {cc}p
cl vout 0 {cl}f
.control
ac dec 30 1 10G
wrdata {out} vr(vout) vi(vout)
.endc
.end
"""


def bias_cm(p: OpAmpParams, model: NgspiceModel) -> float:
    """Input / output common mode for the testbench: the centre of the window
    where every device is saturated for this model's thresholds (VDD/2 is
    not safe — with low-Vth devices it drives M2 into triode)."""
    lo, hi = cm_window(p, model.vth_n, model.vth_p, model.vdd, vth_n6=_vth6(model))
    return round(min(max((lo + hi) / 2.0, 0.0), model.vdd), 4)


def _vth6(model: NgspiceModel) -> float:
    return model.vth_n6 or model.vth_n


def _dc_seeds(p: OpAmpParams, model: NgspiceModel) -> dict:
    """Analytic DC node voltages, used as .nodeset seeds. Seeding the high-
    impedance nodes near their real values (rather than all at vcm) is what
    lets the operating point converge for long-channel PDK devices."""
    vcm, vtn, vtp, vdd = bias_cm(p, model), model.vth_n, model.vth_p, model.vdd
    i1 = p.itail / 2.0
    vov = lambda kp, wl, i: _vov(kp, wl, i)                      # noqa: E731
    r = lambda v: round(min(max(v, 0.0), vdd), 4)                 # noqa: E731
    return {
        "v_tail": r(vcm - vtn - vov(KP_N, p.wl1, i1)),
        "v_outm": r(vdd - vtp - vov(KP_P, p.wl3, i1)),
        "v_outp": r(_vth6(model) + vov(KP_N, p.wl6, p.i6)),
        "v_nb5": r(vtn + vov(KP_N, p.wl5, p.itail)),
        "v_pb7": r(vdd - vtp - vov(KP_P, p.wl7, p.i6)),
    }


def render_netlist(p: OpAmpParams, model: NgspiceModel, out_path: str) -> str:
    l = model.l_um
    lg = model.l_gain_um or l           # gain-setting devices (W/L preserved)
    devices = "\n".join([
        _dev(model, "1", "outm", "vinp", "tail", "0", "n", p.wl1 * lg, lg),
        _dev(model, "2", "outp", "vinn", "tail", "0", "n", p.wl1 * lg, lg),
        _dev(model, "3", "outm", "outm", "vdd", "vdd", "p", p.wl3 * lg, lg),
        _dev(model, "4", "outp", "outm", "vdd", "vdd", "p", p.wl3 * lg, lg),
        _dev(model, "5", "tail", "nb5", "0", "0", "n", p.wl5 * l, l),
        _dev(model, "b5", "nb5", "nb5", "0", "0", "n", p.wl5 * l, l),
        _dev(model, "6", "vout", "outp", "0", "0", "n", p.wl6 * l, l),
        _dev(model, "7", "vout", "pb7", "vdd", "vdd", "p", p.wl7 * lg, lg),
        _dev(model, "b7", "pb7", "pb7", "vdd", "vdd", "p", p.wl7 * lg, lg),
    ])
    return _NETLIST.format(
        header=model.header, devices=devices, temp=model.temp,
        vdd=model.vdd, vcm=bias_cm(p, model), **_dc_seeds(p, model),
        itail=p.itail, i6=p.i6, cc=p.cc * 1e12, cl=model.cl_ff, out=out_path,
    )


def _parse_wrdata(text: str):
    """ngspice `wrdata` AC output: rows of `freq vr freq vi` -> (freq, complex).

    Leading non-numeric lines (a vector-name header) are skipped, but once data
    has started a short/garbled row or a non-finite value (a diverged or
    truncated run) raises NgspiceUnavailable instead of silently yielding a
    partial sweep that would still produce plausible-looking specs.
    """
    freq, vout = [], []
    for n, line in enumerate(text.splitlines(), 1):
        toks = line.split()
        if not toks:
            continue
        try:
            if len(toks) < 4:
                raise ValueError("short row")
            f = float(toks[0]); vr = float(toks[1]); vi = float(toks[-1])
        except ValueError:
            if not freq:
                continue                 # header before the first data row
            raise NgspiceUnavailable(f"incomplete ngspice AC output at line {n}: {line[:80]!r}")
        if not all(math.isfinite(v) for v in (f, vr, vi)):
            raise NgspiceUnavailable(f"non-finite ngspice AC output at line {n}: {line[:80]!r}")
        freq.append(f); vout.append(complex(vr, vi))
    return freq, vout


def _phase_margin(freq, vout, gbw) -> float:
    """Phase margin = 180 - cumulative phase lag from DC to the unity-gain freq.

    Uses unwrapped phase so the inverting (~180 deg) DC reference doesn't alias.
    An unmeasured (NaN) GBW gives an unmeasured (NaN) phase margin.
    """
    import numpy as np
    if not math.isfinite(gbw):
        return math.nan
    f = np.asarray(freq, dtype=float)
    ph = np.degrees(np.unwrap(np.angle(np.asarray(vout, dtype=complex))))
    order = np.argsort(f)
    f, ph = f[order], ph[order]
    ph_dc = ph[0]
    ph_gbw = float(np.interp(gbw, f, ph))
    lag = ph_dc - ph_gbw                 # cumulative lag (deg, positive)
    return 180.0 - lag


def ngspice_available() -> bool:
    return shutil.which("ngspice") is not None


def _run_ngspice(p: OpAmpParams, model: NgspiceModel, tmp: Path, runner,
                 timeout: float) -> str:
    """Write the netlist into *tmp*, run ngspice (or *runner*), return wrdata text."""
    out_file = tmp / "ac.txt"
    cir = tmp / "ota.cir"
    cir.write_text(render_netlist(p, model, str(out_file)))

    if runner is not None:
        return runner(str(cir))
    if not ngspice_available():
        raise NgspiceUnavailable(
            "ngspice not on PATH. Install: `brew install ngspice` (macOS) / "
            "`apt install ngspice` (Linux), or use the IIC-OSIC-TOOLS docker."
        )
    # -n: skip the user's/local .spiceinit so a stray config can't change the
    # numerics (the netlist carries every option it needs); -b: batch mode.
    try:
        proc = subprocess.run(["ngspice", "-n", "-b", str(cir)], cwd=tmp,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise NgspiceUnavailable(f"ngspice timed out after {timeout:g} s") from e
    if not out_file.exists():
        raise NgspiceUnavailable(f"ngspice produced no output: {proc.stderr[-400:]}")
    return out_file.read_text()


def ngspice_evaluate(p: OpAmpParams, model: NgspiceModel = GENERIC_NGSPICE, *,
                     runner=None, work_dir: str | None = None,
                     timeout: float = 120.0) -> OpAmpSpecs:
    """Run a real ngspice AC sweep and return specs (same contract as evaluate_opamp).

    `runner(netlist_path) -> wrdata_text` lets tests inject a fake ngspice.
    Raises NgspiceUnavailable if ngspice is missing, times out after *timeout*
    seconds, or the run produces no / incomplete / non-finite data.

    Without *work_dir* the run uses a private temp dir that is always removed
    (also on failure); a caller-supplied *work_dir* is kept for inspection.
    """
    if work_dir is not None:
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        wrdata = _run_ngspice(p, model, Path(work_dir), runner, timeout)
    else:
        with tempfile.TemporaryDirectory(prefix="ota_ngspice_") as tmp:
            wrdata = _run_ngspice(p, model, Path(tmp), runner, timeout)

    freq, vout = _parse_wrdata(wrdata)
    if not freq:
        raise NgspiceUnavailable("could not parse ngspice AC output")
    gain_db, gbw, _ = extract_ac_metrics(freq, vout)
    pm = _phase_margin(freq, vout, gbw)

    i1 = p.itail / 2.0
    return OpAmpSpecs(
        gain_db=gain_db, gbw_hz=gbw, pm_deg=pm,
        slew=p.itail / p.cc, power=model.vdd * (p.itail + p.i6),
        vov1=_vov(KP_N, p.wl1, i1), vov3=_vov(KP_P, p.wl3, i1),
        vov5=_vov(KP_N, p.wl5, p.itail), vov6=_vov(KP_N, p.wl6, p.i6),
        vov7=_vov(KP_P, p.wl7, p.i6),
        headroom=headroom(p, model.vth_n, model.vth_p, model.vdd, vth_n6=_vth6(model)),
    )


def make_ngspice_objective(model: NgspiceModel = GENERIC_NGSPICE, **kw):
    """Drop-in objective(x) backed by real ngspice (open-source closed loop)."""
    from .opamp_opt import _violation_from_specs, POWER_SCALE

    def objective(x) -> float:
        p = OpAmpParams.from_vector(x)
        specs = ngspice_evaluate(p, model, **kw)
        v = _violation_from_specs(specs, p)
        return 1e3 * v + 10.0 if v > 0 else specs.power / POWER_SCALE

    return objective
