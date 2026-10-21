#!/usr/bin/env bash
# Bundle one run's M1 deliverables into deliverables/<run_id>.zip to send to reviewers (not committed: the cell
# map is an OSM-derived database (ODbL) and describes a dealer's service area).
# Usage: ./scripts/package.sh runs/<run_id>
set -euo pipefail
RUN="${1:?usage: package.sh runs/<run_id>}"
ID="$(basename "$RUN")"
OUT="deliverables/$ID"
rm -rf "$OUT" && mkdir -p "$OUT"
cp "$RUN"/cells.geojson "$RUN"/failure_report.md "$OUT"/
for f in hard_cases_results.csv crosscheck.md run_meta.json; do [ -f "$RUN/$f" ] && cp "$RUN/$f" "$OUT/"; done
[ -f runs/scenarios.md ] && cp runs/scenarios.md "$OUT/"
cp docs/m1-failure-report.md "$OUT/M1-REPORT.md"
cat > "$OUT/README.txt" <<EOF
RoadZone M1 deliverables: $ID

Start with M1-REPORT.md (summary and recommendation).

To view the map without installing anything, open https://kepler.gl/demo and drag cells.geojson onto it.
Colour by "zone_code" (zones) or "band" (road-mile bands). It also opens in QGIS.

Files:
  cells.geojson           raw cell map (deliverable 1): status, band, corridor and reason codes per hexagon
  failure_report.md       automatic failure report for this run (deliverable 2)
  M1-REPORT.md            written summary and recommendation
  crosscheck.md           200-cell comparison with an independent router (OSRM)
  scenarios.md            tricky-scenario results
  hard_cases_results.csv  Stevens Creek hard cases

Caveats: the base point is a placeholder (provisional), minutes are free-flow and optimistic, OSRM is a
cross-check not ground truth, and all expectations are engineering judgement until the service director reviews them.
Map data (c) OpenStreetMap contributors, ODbL. For internal review only; do not redistribute.
EOF
(cd deliverables && rm -f "$ID.zip" && zip -qr "$ID.zip" "$ID")
ls -la "deliverables/$ID.zip"
