"""Layout-dependent effects (LDE): STI/LOD stress + well-proximity (WPE) on Vth.

Two well-known LDE mechanisms shift a device's threshold by *how it is drawn*,
not its W/L — so two electrically-identical transistors mismatch:

  * STI / LOD (length-of-diffusion stress): the shallow-trench-isolation edge
    compresses the channel. The stress scales with 1/SA + 1/SB, where SA/SB are
    the gate-to-OD-edge distances. A finger at the **edge** of an active block
    sees a near OD edge (small SA) => more stress => Vth shift; an interior
    finger sees OD continuing on both sides (large SA) => little shift.

  * WPE (well proximity): ions scatter off the well-mask edge during implant, so
    a device within ~1um of the well edge is more heavily doped => Vth rises.
    Modeled as a shift decaying with the well-edge distance SC.

Key consequence for the input pair: **common-centroid cancels a linear gradient
but NOT the edge effect** — in an ABBA block the two outer fingers belong to one
device, so that device carries more STI stress. **Dummy fingers** at the block
ends push every *active* finger to an interior position, equalizing SA/SB and
collapsing the residual Vth mismatch. This module quantifies that.

Coefficients are illustrative (BSIM-LOD/WPE shaped); the meaningful output is the
*relative* mismatch reduction from common-centroid + dummies.
"""

from __future__ import annotations

import math

# Illustrative coefficients (order-of-magnitude realistic).
K_LOD = 0.010      # V * um  : STI/LOD stress -> Vth
K_WPE = 0.030      # V       : WPE Vth bump right at the well edge
WPE_DECAY = 0.80   # um      : WPE decay length
SD_EXT = 0.30      # um      : gate-to-own-OD-edge (matches device_layout)


def lod_stress(sa: float, sb: float, L: float = 0.15) -> float:
    """STI/LOD stress proxy = 1/(SA+L/2) + 1/(SB+L/2) (1/um). Larger => more shift."""
    return 1.0 / (sa + L / 2) + 1.0 / (sb + L / 2)


def lod_vth(sa: float, sb: float, L: float = 0.15) -> float:
    """LOD-induced Vth shift (V) for a finger with OD-edge distances SA, SB."""
    return K_LOD * lod_stress(sa, sb, L)


def wpe_vth(sc: float) -> float:
    """WPE-induced Vth shift (V) for a device SC microns from the well edge."""
    return K_WPE * math.exp(-max(sc, 0.0) / WPE_DECAY)


def _finger_sa_sb(idx: int, n_block: int, pitch: float, sd_ext: float = SD_EXT):
    """SA/SB of finger `idx` inside a shared-OD block of `n_block` fingers.

    OD spans the whole block; distance from this finger's gate to the block's
    left/right OD edge grows with how many fingers sit between it and the edge.
    """
    sa = sd_ext + idx * pitch
    sb = sd_ext + (n_block - 1 - idx) * pitch
    return sa, sb


def array_lod_offset(pattern: list[str], dummies: int, pitch: float,
                     L: float = 0.15, sd_ext: float = SD_EXT) -> dict:
    """Mean LOD Vth per device (A/B) and the A-vs-B mismatch for a finger array.

    `pattern` is the active finger order (e.g. ['A','B','B','A']); `dummies`
    inactive fingers are added at *each* end. Returns shifts in volts/millivolts.
    """
    n_active = len(pattern)
    n_block = n_active + 2 * dummies
    per_dev: dict[str, list[float]] = {"A": [], "B": []}
    for j, dev in enumerate(pattern):
        idx = dummies + j                       # active finger's index in the block
        sa, sb = _finger_sa_sb(idx, n_block, pitch, sd_ext)
        per_dev[dev].append(lod_vth(sa, sb, L))
    mean_a = sum(per_dev["A"]) / len(per_dev["A"])
    mean_b = sum(per_dev["B"]) / len(per_dev["B"])
    dvth = abs(mean_a - mean_b)
    return {"dummies": dummies, "block_fingers": n_block,
            "vth_A_mV": round(mean_a * 1e3, 3), "vth_B_mV": round(mean_b * 1e3, 3),
            "mismatch_mV": round(dvth * 1e3, 3)}


def diffpair_lde(pattern: list[str], pitch: float, dummy_options=(0, 1, 2),
                 L: float = 0.15) -> dict:
    """LOD mismatch of the input pair across dummy counts (shows the benefit)."""
    scans = [array_lod_offset(pattern, d, pitch, L) for d in dummy_options]
    base = scans[0]["mismatch_mV"]
    for s in scans:
        s["reduction_x"] = round(base / s["mismatch_mV"], 1) if s["mismatch_mV"] > 1e-6 else None
    return {"pattern": "".join(pattern), "pitch_um": pitch,
            "note": "common-centroid cancels the linear gradient; dummies cancel "
                    "the residual STI/LOD edge mismatch",
            "scan": scans}
