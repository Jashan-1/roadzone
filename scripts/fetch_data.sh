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
# pinned OpenStreetMapSpeeds typical speeds (MIT); keep in sync with data.default_speeds_source
[ -f default_speeds.json ] || curl -fsSL -o default_speeds.json \
  https://raw.githubusercontent.com/OpenStreetMapSpeeds/schema/c9c6872d5ec656f5d290944b44eb1a103ed539fa/default_speeds.json
ls -la "$SNAPSHOT.osm.pbf" default_speeds.json "${SNAPSHOT%-*}.poly"
