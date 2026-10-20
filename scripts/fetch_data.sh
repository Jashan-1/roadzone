#!/usr/bin/env bash
# Download a pinned Geofabrik snapshot and record its checksum.
# Usage: ./scripts/fetch_data.sh [path under north-america/us/, default california-261018]
set -euo pipefail
REGION="${1:-california-261018}"
SNAPSHOT="$(basename "$REGION")"
cd "$(dirname "$0")/../data"
[ -f "$SNAPSHOT.osm.pbf" ] || { curl -fL -o "$SNAPSHOT.osm.pbf.part" \
  "https://download.geofabrik.de/north-america/us/$REGION.osm.pbf" && mv "$SNAPSHOT.osm.pbf.part" "$SNAPSHOT.osm.pbf"; }
printf '{"pbf": "%s.osm.pbf", "sha256": "%s"}\n' "$SNAPSHOT" \
  "$(shasum -a 256 "$SNAPSHOT.osm.pbf" | cut -d' ' -f1)" > snapshot.json
cat snapshot.json
