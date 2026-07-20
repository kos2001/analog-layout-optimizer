#!/bin/sh
# Run the full SKY130 PDK DRC deck (KLayout, BEOL rules) on a GDS file.
#
# Usage: scripts/run_sky130_drc.sh <input.gds> <top_cell> [report.lyrdb]
#
# Requires:
#   - KLayout app (brew install --cask klayout; binary kept at
#     ~/Applications/klayout.app because macOS quarantine removes the
#     /Applications copy of the unsigned bundle)
#   - SKY130 PDK via volare (PDK_ROOT, default ~/pdk)
set -eu

GDS=${1:?usage: run_sky130_drc.sh <input.gds> <top_cell> [report.lyrdb]}
TOP=${2:?missing top cell name}
REPORT=${3:-${GDS%.gds}_drc.lyrdb}
PDK_ROOT=${PDK_ROOT:-$HOME/pdk}
KLAYOUT=${KLAYOUT:-$HOME/Applications/klayout.app/Contents/MacOS/klayout}
DECK="$PDK_ROOT/sky130A/libs.tech/klayout/drc/sky130A_mr.drc"

[ -x "$KLAYOUT" ] || { echo "klayout binary not found: $KLAYOUT" >&2; exit 1; }
[ -f "$DECK" ] || { echo "DRC deck not found: $DECK" >&2; exit 1; }

"$KLAYOUT" -b -r "$DECK" \
  -rd input="$GDS" -rd report="$REPORT" -rd top_cell="$TOP" \
  -rd beol=true -rd feol=false

ITEMS=$(grep -c "<item>" "$REPORT" || true)
echo "DRC report: $REPORT (${ITEMS} violation items)"
