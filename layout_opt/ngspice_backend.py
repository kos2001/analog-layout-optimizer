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

from .opamp import VDD, OpAmpParams, OpAmpSpecs, _vov, KP_N, KP_P
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


def sky130_model(corner: str = "tt", pdk_root: str | None = None,
                 l_um: float = 0.5, cl_ff: float = 1000.0) -> NgspiceModel:
    """Real SkyWater SKY130 device models (open PDK) — silicon, not square-law.

    Devices are 1.8 V core FETs (`sky130_fd_pr__{n,p}fet_01v8`) via the PDK's
    ngspice `.lib`. Requires the PDK installed (e.g. `volare enable`); point
    PDK_ROOT at it. L defaults to 0.5 um (more intrinsic gain than 0.15 um min).
    """
    return NgspiceModel(
        name=f"sky130-{corner}",
        header=f'.lib "{sky130_lib_path(pdk_root)}" {corner}',
        nmos="sky130_fd_pr__nfet_01v8", pmos="sky130_fd_pr__pfet_01v8",
        l_um=l_um, vdd=1.8, cl_ff=cl_ff, subckt=True, w_min=0.42,
        w_max=100.0,   # binned models reject total w > 100 um per instance
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
.nodeset v(vout)={vcm} v(vinn)={vcm} v(outp)={vcm}
{devices}
itail tail 0 dc {itail}
i6 vdd vout dc {i6}
cc outp vout {cc}p
cl vout 0 {cl}f
.control
ac dec 30 1 10G
wrdata {out} vr(vout) vi(vout)
.endc
.end
"""


def render_netlist(p: OpAmpParams, model: NgspiceModel, out_path: str) -> str:
    l = model.l_um
    devices = "\n".join([
        _dev(model, "1", "outm", "vinp", "tail", "0", "n", p.wl1 * l, l),
        _dev(model, "2", "outp", "vinn", "tail", "0", "n", p.wl1 * l, l),
        _dev(model, "3", "outm", "outm", "vdd", "vdd", "p", p.wl3 * l, l),
        _dev(model, "4", "outp", "outm", "vdd", "vdd", "p", p.wl3 * l, l),
        _dev(model, "6", "vout", "outp", "0", "0", "n", p.wl6 * l, l),
    ])
    return _NETLIST.format(
        header=model.header, devices=devices, temp=model.temp,
        vdd=model.vdd, vcm=model.vdd / 2.0,
        itail=p.itail, i6=p.i6, cc=p.cc * 1e12, cl=model.cl_ff, out=out_path,
    )


def _parse_wrdata(text: str):
    """ngspice `wrdata` AC output: rows of `freq vr freq vi` -> (freq, complex)."""
    freq, vout = [], []
    for line in text.splitlines():
        toks = line.split()
        if len(toks) < 4:
            continue
        try:
            f = float(toks[0]); vr = float(toks[1]); vi = float(toks[-1])
        except ValueError:
            continue
        freq.append(f); vout.append(complex(vr, vi))
    return freq, vout


def _phase_margin(freq, vout, gbw) -> float:
    """Phase margin = 180 - cumulative phase lag from DC to the unity-gain freq.

    Uses unwrapped phase so the inverting (~180 deg) DC reference doesn't alias.
    """
    import numpy as np
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


def ngspice_evaluate(p: OpAmpParams, model: NgspiceModel = GENERIC_NGSPICE, *,
                     runner=None, work_dir: str | None = None) -> OpAmpSpecs:
    """Run a real ngspice AC sweep and return specs (same contract as evaluate_opamp).

    `runner(netlist_path) -> wrdata_text` lets tests inject a fake ngspice.
    Raises NgspiceUnavailable if ngspice is missing or the run produces no data.
    """
    tmp = Path(work_dir or tempfile.mkdtemp(prefix="ota_ngspice_"))
    tmp.mkdir(parents=True, exist_ok=True)
    out_file = tmp / "ac.txt"
    cir = tmp / "ota.cir"
    cir.write_text(render_netlist(p, model, str(out_file)))

    if runner is not None:
        wrdata = runner(str(cir))
    else:
        if not ngspice_available():
            raise NgspiceUnavailable(
                "ngspice not on PATH. Install: `brew install ngspice` (macOS) / "
                "`apt install ngspice` (Linux), or use the IIC-OSIC-TOOLS docker."
            )
        proc = subprocess.run(["ngspice", "-b", str(cir)],
                              capture_output=True, text=True, timeout=120)
        if not out_file.exists():
            raise NgspiceUnavailable(f"ngspice produced no output: {proc.stderr[-400:]}")
        wrdata = out_file.read_text()

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
