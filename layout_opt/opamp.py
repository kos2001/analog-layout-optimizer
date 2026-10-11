r"""Two-stage Miller-compensated OTA - analytical (square-law) model.

A harder, higher-dimensional analog sizing problem than the diff pair: a
5-transistor first stage (M1/M2 input pair, M3/M4 mirror load, M5 tail) plus a
common-source second stage (M6 driver, M7 current-source load) with a Miller
compensation cap Cc driving a load CL.

           VDD
       M7 (load, I6)         M3  M4  (mirror)
        |                     |   |
   o----+---- out2     out1 --+---+
        |   Cc                |   |
   M6 (drv)===||==== out1   M1  M2  (input pair, gm1)
        |                      \ /
       GND                    M5 (tail, Itail)

Square-law relations (simplified but with the right trade-offs):
  gm = sqrt(2 * KP * (W/L) * I)         transconductance
  ro = 1 / (lambda * I)                 output resistance
  A0 = gm1*R1 * gm6*R2                  two-stage DC gain (R1,R2 node resistances)
  GBW = gm1 / Cc                        unity-gain bandwidth (rad/s)
  p2  = gm6 / CL                        non-dominant pole (Miller pole-split)
  z   = gm6 / Cc                        RHP zero
  PM  = 90 - atan(GBW/p2) - atan(GBW/z) phase margin (deg)
  SR  = Itail / Cc                      slew rate
  P   = VDD * (Itail + I6)              power

This is NOT SPICE-accurate; it is a physically-reasonable analytical surrogate
whose purpose is a non-convex, constrained, multi-spec optimization landscape.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Process / environment constants.
KP_N = 200e-6      # NMOS transconductance parameter (A/V^2)
KP_P = 100e-6      # PMOS
LAMBDA_N = 0.10    # channel-length modulation (1/V)
LAMBDA_P = 0.12
VDD = 1.8
CL = 1e-12         # load capacitance (1 pF)
VTH_N = 0.40       # threshold voltages of the square-law devices (V); the
VTH_P = 0.40       # generic ngspice level-1 models use the same vto
SAT_MARGIN = 0.05  # Vds - Vov every device must keep at the bias point (V)


@dataclass(frozen=True)
class OpAmpParams:
    """Sizing knobs. W/L are ratios; currents in A; Cc in F."""
    wl1: float    # input pair M1/M2
    wl3: float    # mirror load M3/M4
    wl5: float    # tail M5
    wl6: float    # second-stage driver M6
    wl7: float    # second-stage load M7
    itail: float  # tail current
    i6: float     # second-stage current
    cc: float     # Miller cap

    ORDER = ("wl1", "wl3", "wl5", "wl6", "wl7", "itail", "i6", "cc")

    def to_vector(self):
        return [getattr(self, k) for k in self.ORDER]

    @classmethod
    def from_vector(cls, x):
        return cls(**{k: float(v) for k, v in zip(cls.ORDER, x)})


# Realistic search bounds (note the multi-decade spans on I and Cc -> log-space
# is a natural transform, which the experiments exploit).
BOUNDS = {
    "wl1": (1.0, 400.0),
    "wl3": (1.0, 400.0),
    "wl5": (1.0, 400.0),
    "wl6": (1.0, 800.0),
    "wl7": (1.0, 800.0),
    "itail": (1e-6, 500e-6),
    "i6": (1e-6, 1e-3),
    "cc": (0.1e-12, 10e-12),
}


def bounds_vector():
    return [BOUNDS[k] for k in OpAmpParams.ORDER]


@dataclass
class OpAmpSpecs:
    gain_db: float
    gbw_hz: float
    pm_deg: float
    slew: float
    power: float
    # Overdrive voltages of every device (saturation/headroom constraints;
    # these make the mirror/tail/load W/L knobs matter).
    vov1: float
    vov3: float
    vov5: float
    vov6: float
    vov7: float
    # Width (V) of the input common-mode window that keeps every device
    # saturated with SAT_MARGIN to spare; < 0 means no valid bias point.
    headroom: float = math.inf

    def unmeasured(self) -> list[str]:
        """Simulated headline metrics that came back NaN (not measured)."""
        return [k for k in ("gain_db", "gbw_hz", "pm_deg")
                if not math.isfinite(getattr(self, k))]

    def summary(self, pm_digits: int = 2) -> dict:
        """JSON-safe headline metrics; an unmeasured metric is None, never NaN
        (which the API can't serialize) and never a made-up number."""
        def r(v: float, nd: int):
            return round(float(v), nd) if math.isfinite(v) else None
        return {"gain_db": r(self.gain_db, 2), "gbw_mhz": r(self.gbw_hz / 1e6, 2),
                "pm_deg": r(self.pm_deg, pm_digits), "power_mw": r(self.power * 1e3, 4)}


def _gm(kp, wl, i):
    return math.sqrt(max(2.0 * kp * wl * i, 1e-30))


def _vov(kp, wl, i):
    # overdrive V_ov = sqrt(2 I / (KP W/L))
    return math.sqrt(max(2.0 * i / (kp * wl), 1e-30))


def ac_response(p: OpAmpParams, freqs_hz):
    """Small-signal AC response H(jw) of the two-stage OTA over freqs (Hz).

    Two-pole + RHP-zero model: H = A0 (1 - s/z) / ((1+s/p1)(1+s/p2)),
    p1 = GBW/A0 (dominant, Miller), p2 = gm6/CL, z = gm6/Cc.
    Returns (magnitude_dB, phase_deg) lists.
    """
    i1 = p.itail / 2.0
    gm1 = _gm(KP_N, p.wl1, i1)
    gm6 = _gm(KP_N, p.wl6, p.i6)
    r1 = 1.0 / ((LAMBDA_N + LAMBDA_P) * i1)
    r2 = 1.0 / ((LAMBDA_N + LAMBDA_P) * p.i6)
    a0 = gm1 * r1 * gm6 * r2
    gbw = gm1 / p.cc            # rad/s
    p1 = gbw / a0              # dominant pole (rad/s)
    p2 = gm6 / CL
    z = gm6 / p.cc
    mag_db, phase_deg = [], []
    for f in freqs_hz:
        w = 2.0 * math.pi * f
        s = 1j * w
        h = a0 * (1 - s / z) / ((1 + s / p1) * (1 + s / p2))
        mag_db.append(20.0 * math.log10(abs(h) + 1e-30))
        phase_deg.append(math.degrees(math.atan2(h.imag, h.real)))
    return mag_db, phase_deg


def cm_window(p: OpAmpParams, vth_n: float = VTH_N, vth_p: float = VTH_P,
              vdd: float = VDD, margin: float = SAT_MARGIN) -> tuple[float, float]:
    """Input common-mode range (V) that keeps all seven devices saturated.

    DC node voltages of the two-stage OTA with the output held at the input
    common mode Vcm (unity-gain / DC-feedback bias):
      tail = Vcm - Vtn - Vov1      outm = VDD - |Vtp| - Vov3
      outp = Vtn + Vov6 (set by M6 carrying the load current)
    Lower edge: M5 needs tail >= Vov5 (and M6 needs Vcm >= Vov6).
    Upper edge: M2 needs outp - tail >= Vov1, i.e. Vcm <= 2 Vtn + Vov6;
    M1 needs outm - tail >= Vov1; M7 needs VDD - Vcm >= Vov7.
    Every limit keeps *margin* volts to spare.
    """
    i1 = p.itail / 2.0
    vov1 = _vov(KP_N, p.wl1, i1)
    vov3 = _vov(KP_P, p.wl3, i1)
    vov5 = _vov(KP_N, p.wl5, p.itail)
    vov6 = _vov(KP_N, p.wl6, p.i6)
    vov7 = _vov(KP_P, p.wl7, p.i6)
    lo = max(vth_n + vov1 + vov5 + margin, vov6 + margin)
    hi = min(2 * vth_n + vov6 - margin,
             vdd - vth_p + vth_n - vov3 - margin,
             vdd - vov7 - margin)
    return lo, hi


def headroom(p: OpAmpParams, vth_n: float = VTH_N, vth_p: float = VTH_P,
             vdd: float = VDD, margin: float = SAT_MARGIN) -> float:
    """Spare DC headroom (V): the common-mode window width, also capped by
    M4's |Vds| margin (VDD - outp - Vov3), which no choice of Vcm can fix."""
    lo, hi = cm_window(p, vth_n, vth_p, vdd, margin)
    i1 = p.itail / 2.0
    m4 = vdd - (vth_n + _vov(KP_N, p.wl6, p.i6)) - _vov(KP_P, p.wl3, i1) - margin
    return min(hi - lo, m4)


def evaluate_opamp(p: OpAmpParams) -> OpAmpSpecs:
    i1 = p.itail / 2.0
    gm1 = _gm(KP_N, p.wl1, i1)
    gm6 = _gm(KP_N, p.wl6, p.i6)

    r1 = 1.0 / ((LAMBDA_N + LAMBDA_P) * i1)     # ro2 || ro4
    r2 = 1.0 / ((LAMBDA_N + LAMBDA_P) * p.i6)   # ro6 || ro7

    a0 = gm1 * r1 * gm6 * r2
    gain_db = 20.0 * math.log10(max(a0, 1e-12))

    gbw = gm1 / p.cc                 # rad/s
    p2 = gm6 / CL                    # rad/s
    z = gm6 / p.cc                   # RHP zero (rad/s)
    pm = 90.0 - math.degrees(math.atan(gbw / p2)) - math.degrees(math.atan(gbw / z))
    sr = p.itail / p.cc
    power = VDD * (p.itail + p.i6)

    return OpAmpSpecs(
        gain_db=gain_db,
        gbw_hz=gbw / (2.0 * math.pi),
        pm_deg=pm,
        slew=sr,
        power=power,
        vov1=_vov(KP_N, p.wl1, i1),         # input pair (I = Itail/2)
        vov3=_vov(KP_P, p.wl3, i1),         # mirror load (I = Itail/2)
        vov5=_vov(KP_N, p.wl5, p.itail),    # tail (I = Itail)
        vov6=_vov(KP_N, p.wl6, p.i6),       # 2nd-stage driver
        vov7=_vov(KP_P, p.wl7, p.i6),       # 2nd-stage load
        headroom=headroom(p),
    )
