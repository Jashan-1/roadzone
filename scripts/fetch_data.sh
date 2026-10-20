#!/usr/bin/env bash
# Download the pinned Geofabrik NorCal snapshot and record its checksum.
set -euo pipefail
SNAPSHOT="${1:-norcal-261018}"
cd "$(dirname "$0")/../data"
[ -f "$SNAPSHOT.osm.pbf" ] || curl -fL -o "$SNAPSHOT.osm.pbf.part" \
  "https://download.geofabrik.de/north-america/us/california/$SNAPSHOT.osm.pbf" && \
  { [ -f "$SNAPSHOT.osm.pbf" ] || mv "$SNAPSHOT.osm.pbf.part" "$SNAPSHOT.osm.pbf"; }
printf '{"pbf": "%s.osm.pbf", "sha256": "%s"}\n' "$SNAPSHOT" \
  "$(shasum -a 256 "$SNAPSHOT.osm.pbf" | cut -d' ' -f1)" > snapshot.json
cat snapshot.json
