"""Bridged T-coil bandwidth-extension model (analytic closed form).

A bridged T-coil absorbs a load capacitance C_L into a coupled-inductor network
to extend bandwidth. Topology modeled (current-in / voltage-out):

    I_in -> node A ; L1: A->T ; L2: T->B (mutual M, k = M/sqrt(L1 L2)) ;
    C_L at tap T to ground ; bridge cap C_B across A-B ; load R at B.

The bandwidth-extended signal is the voltage across the load cap, V_T (NOT V_B:
the bridge cap feeds I_in straight to B at high frequency, so V_B does not roll
off). The transimpedance Z(s) = V_T / I_in was derived symbolically (sympy); for
the symmetric design L1 = L2 = L (M = kL), with R and C_L normalized to 1
(reference bandwidth omega0 = 1/(R*C_L) = 1):

    num(s) =          a2 s^2 + a1 s + a0
    den(s) = b4 s^4 + b3 s^3 + b2 s^2 + b1 s + b0

with
    a2 = 2 C_B L (1+k)          b4 = C_B L^2 (1-k^2)
    a1 = L (1+k)                b3 = 2 C_B L (1+k)
    a0 = 1                      b2 = 2 C_B L (1+k) + L
                                b1 = 1
                                b0 = 1

Sanity: Z(0) = R = 1; Z rolls off as 1/s^2 at high frequency. No coil
(L=0, C_B=0): Z = 1/(1+s) -> first-order, BW = 1 (the reference).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Reference: bandwidth of the bare RC load (R=C_L=1) is omega0 = 1 rad/s.
REFERENCE_BW = 1.0


@dataclass(frozen=True)
class TCoilParams:
    L: float       # each coil inductance (normalized), L1 = L2 = L
    k: float       # coupling coefficient, M = k L  (0 <= k < 1)
    Cb: float      # bridge capacitance (normalized)

    ORDER = ("L", "k", "Cb")

    def to_vector(self):
        return [self.L, self.k, self.Cb]

    @classmethod
    def from_vector(cls, x):
        return cls(L=float(x[0]), k=float(x[1]), Cb=float(x[2]))


def _coeffs(p: TCoilParams):
    L, k, Cb = p.L, p.k, p.Cb
    a2 = 2.0 * Cb * L * (1.0 + k)
    a1 = L * (1.0 + k)
    a0 = 1.0
    b4 = Cb * L * L * (1.0 - k * k)
    b3 = 2.0 * Cb * L * (1.0 + k)
    b2 = 2.0 * Cb * L * (1.0 + k) + L
    b1 = 1.0
    b0 = 1.0
    return (a2, a1, a0), (b4, b3, b2, b1, b0)


def transimpedance(p: TCoilParams, w):
    """Z(j w) for scalar or array w (R = C_L = 1)."""
    w = np.asarray(w, dtype=float)
    (a2, a1, a0), (b4, b3, b2, b1, b0) = _coeffs(p)
    w2 = w * w
    num = (a0 - a2 * w2) + 1j * (a1 * w)
    den = (b4 * w2 * w2 - b2 * w2 + b0) + 1j * (b1 * w - b3 * w2 * w)
    return num / den


def _mag(p: TCoilParams, w):
    return np.abs(transimpedance(p, w))


_W = np.logspace(-2, 2, 6000)   # frequency grid (rad/s), 0.01 .. 100


def peaking_db(p: TCoilParams) -> float:
    """Max magnitude relative to DC (|Z(0)| = 1), in dB. >0 means overshoot."""
    m = _mag(p, _W)
    return 20.0 * np.log10(max(m.max(), 1e-12))


def bandwidth(p: TCoilParams) -> float:
    """-3 dB bandwidth (rad/s): first w where |Z| falls to |Z(0)|/sqrt(2)."""
    m = _mag(p, _W)
    thr = 1.0 / np.sqrt(2.0)        # |Z(0)| = 1
    below = np.where(m < thr)[0]
    if below.size == 0:
        return _W[-1]
    i = below[0]
    if i == 0:
        return _W[0]
    w0, w1 = _W[i - 1], _W[i]
    m0, m1 = m[i - 1], m[i]
    if m1 == m0:
        return float(w1)
    frac = (thr - m0) / (m1 - m0)
    return float(w0 * (w1 / w0) ** frac)


def bw_extension(p: TCoilParams) -> float:
    """Bandwidth relative to the bare RC load (the figure of merit)."""
    return bandwidth(p) / REFERENCE_BW


@dataclass
class TCoilResult:
    params: TCoilParams
    bw_extension: float
    peaking_db: float
    peak_limit_db: float


def optimize_tcoil(peak_limit_db: float = 0.1, seed: int = 0,
                   maxiter: int = 200) -> TCoilResult:
    """Maximize bandwidth extension subject to a flatness (peaking) limit.

    Searches (L, k, Cb). With a ~0 dB (maximally flat) limit this recovers the
    classic ~3x T-coil bandwidth extension; relaxing the limit trades flatness
    for more bandwidth.
    """
    from scipy.optimize import differential_evolution

    def obj(x):
        p = TCoilParams.from_vector(x)
        over = max(0.0, peaking_db(p) - peak_limit_db)
        return -bw_extension(p) + 50.0 * over

    res = differential_evolution(
        obj, bounds=[(0.0, 3.0), (0.0, 0.95), (0.0, 2.0)],
        seed=seed, maxiter=maxiter, tol=1e-10, polish=True, updating="deferred",
    )
    p = TCoilParams.from_vector(res.x)
    return TCoilResult(
        params=p, bw_extension=bw_extension(p),
        peaking_db=peaking_db(p), peak_limit_db=peak_limit_db,
    )
