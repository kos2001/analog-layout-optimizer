#!/usr/bin/env python3
"""Demo: natural-language process change -> re-adjusted placement + routing.

Run:  python run_process_adapt_demo.py

The schematic stays fixed; placement (device geometry) and routing are
re-optimized to satisfy the new DRC rules + drive spec stated in plain text.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout_opt.process_change import adapt, parse_process_nl

REQUESTS = [
    "Migrate to a coarser node: min poly pitch 0.30 um, metal spacing 0.12 um, "
    "gate length 0.06, drive spec total W/L 3.0",
    "Tighten the metal: min metal spacing 0.05 um, via size 0.03 um.",
]


def main() -> int:
    for nl in REQUESTS:
        print("=" * 78)
        print("request:", nl)
        ov = parse_process_nl(nl)
        print("parsed overrides:", ov.values)
        r = adapt(ov, maxiter=120)
        b, a = r.before, r.after
        print(f"  placement+routing re-optimized (schematic fixed: "
              f"{r.topology_fixed['total_fingers']} fingers, "
              f"{len(r.topology_fixed['nets'])} nets)")
        print(f"  total cell area : {b['total_area_um2']:.3f} -> {a['total_area_um2']:.3f} um^2 "
              f"({r.area_delta_pct:+.1f}%)   DRC clean: {a['drc_clean']}")
        print(f"  device  : finger_pitch {b['device']['finger_pitch']:.3f} -> "
              f"{a['device']['finger_pitch']:.3f}, w_finger {b['device']['w_finger']:.3f} -> "
              f"{a['device']['w_finger']:.3f}")
        print(f"  routing : rail_pitch {b['routing']['rail_pitch']:.3f} -> "
              f"{a['routing']['rail_pitch']:.3f}, via {b['routing']['via_size']:.3f} -> "
              f"{a['routing']['via_size']:.3f}")
        print()
    print("=" * 78)
    print("Schematic/topology unchanged throughout; only P&R adapted to each "
          "process. (Offline analytical model; real PDK via the Spectre backend.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
