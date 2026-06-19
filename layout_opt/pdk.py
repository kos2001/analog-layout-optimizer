"""PDK configuration for the Spectre backend.

Connecting a new process = filling in a PDKConfig (model include + device model
names + a few electrical defaults). No code changes elsewhere. Presets:

  * TEMPLATE_PDK  — placeholders to copy and fill for your real PDK.
  * GENERIC_PDK   — a self-contained ideal-MOS model block usable for a
                    connectivity smoke test on any Spectre install (NOT
                    silicon-accurate; just exercises the real run path).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PDKConfig:
    name: str
    model_include: str   # the spectre line(s) that bring in device models
    nmos: str            # NMOS model/subckt name used in the netlist
    pmos: str            # PMOS model/subckt name
    l_um: float = 0.18   # fixed channel length (W = (W/L)*L)
    vdd: float = 1.8
    cl_ff: float = 1000.0
    vb7: float = 0.9     # second-stage load bias


# Copy this, point model_include at your PDK section, set the real device names.
TEMPLATE_PDK = PDKConfig(
    name="TEMPLATE",
    model_include='include "/path/to/your/pdk/models/spectre/toplevel.scs" section=tt',
    nmos="nch_mac",      # <- your PDK's NMOS device
    pmos="pch_mac",      # <- your PDK's PMOS device
    l_um=0.18,
    vdd=1.8,
)


# Self-contained ideal long-channel MOS models inlined into the netlist, so the
# real Spectre run path can be exercised without a vendor PDK. Not for signoff.
_GENERIC_MODELS = """\
model nmos_g bsim4 type=n version=4.8 toxe=4n nch=1e17 vth0=0.4 u0=0.045 \
  lint=0 wint=0 rdsw=150
model pmos_g bsim4 type=p version=4.8 toxe=4n nch=1e17 vth0=-0.4 u0=0.012 \
  lint=0 wint=0 rdsw=300
"""

GENERIC_PDK = PDKConfig(
    name="GENERIC_IDEAL",
    model_include=_GENERIC_MODELS,
    nmos="nmos_g",
    pmos="pmos_g",
    l_um=0.18,
    vdd=1.8,
)
