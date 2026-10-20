#!/usr/bin/env bash
# Download a pinned Geofabrik snapshot and its boundary. build-tiles records the checksum.
# Usage: ./scripts/fetch_data.sh [path under north-america/us/, default california-261018]
set -euo pipefail
REGION="${1:-california-261018}"
SNAPSHOT="$(basename "$REGION")"
cd "$(dirname "$0")/../data"
[ -f "$SNAPSHOT.osm.pbf" ] || { curl -fL -o "$SNAPSHOT.osm.pbf.part" \
  "https://download.geofabrik.de/north-america/us/$REGION.osm.pbf" && mv "$SNAPSHOT.osm.pbf.part" "$SNAPSHOT.osm.pbf"; }
curl -fsSL -o "${SNAPSHOT%-*}.poly" "https://download.geofabrik.de/north-america/us/${REGION%-*}.poly"
ls -la "$SNAPSHOT.osm.pbf" "${SNAPSHOT%-*}.poly"
