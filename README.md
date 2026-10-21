# RoadZone

**Road-aware service territory generation and address classification using H3, OpenStreetMap, and Valhalla.**

RoadZone is a geospatial engine designed to generate mobile service zones based on real-world road-network accessibility rather than straight-line distance alone.

The goal is to help mobile service businesses determine which areas they can reliably serve, classify locations into distance or travel-time bands, and identify addresses that require manual review.

> **Status:** M1 proof of concept complete (pre-kickoff). Recommendation: **proceed, with known limits**. See the [M1 failure report](docs/m1-failure-report.md).
> **Next gate:** service-director review of 20 known addresses, and the confirmed van entrance (the current base point is a placeholder).

## M1 results at a glance

All numbers use a **provisional base** (placeholder point, not the confirmed van entrance). **Road miles are the v1 rule; minutes are free-flow and optimistic.**

| Check | Result |
|---|---|
| Agreement with an independent router (OSRM), 200 cells never used for tuning | Road miles within ±10%: **88–94% across three untouched samples (reference 88%)** · same distance band: 88–92% (reference 88%; most disagreements are within 0.5 mi of a band edge) |
| Tricky scenarios (corridors, water, mountains, freeway traps, edges, hill homes) | **29/31** pass. The 2 failures are documented: Half Moon Bay labelled I-280 (the longest-stretch limit) and Saratoga Gap borderline (expectation needs review). Walnut Creek's expectation was corrected: both routers put it just past 50 miles. |
| Hill homes on the address path | **8/8** get a band; track or unnamed-road access is flagged for review, never left as a silent "unknown" |
| Stevens Creek hard cases | 16/17 |

OSRM is a cross-check, not ground truth, and every expectation is engineering judgement until the service director reviews it.

## Why RoadZone?

Traditional radius-based service areas treat every location within a fixed radius as equally accessible. In practice, road networks, disconnected streets, highways, bridges, and routing constraints can make two nearby addresses very different in terms of actual travel distance.

RoadZone aims to address this by combining spatial indexing with road-network routing and explicit confidence diagnostics.

## Core Objectives

- Generate candidate service areas using **H3 hexagonal spatial indexing**.
- Calculate road-network distances using **Valhalla**.
- Evaluate outbound and return journeys separately.
- Classify locations into configurable service-distance or travel-time bands.
- Capture snapping and routing evidence for transparency.
- Flag unreliable or ambiguous results instead of silently accepting them.
- Export generated zones and diagnostic results as GeoJSON.
- Make results reproducible through pinned map data and configuration.

## How It Works

The planned processing pipeline is:

1. **Generate candidate cells** — Create an H3 grid covering the target service area.
2. **Snap to the road network** — Associate candidate locations with routable roads and record snap diagnostics.
3. **Calculate routes** — Route between the service origin and candidate locations using Valhalla.
4. **Evaluate both directions** — Calculate outbound and return distances, accounting for road-network asymmetry.
5. **Build routing evidence** — Associate route results with road-network evidence where supported.
6. **Classify service bands** — Assign zones based on configured thresholds and the more restrictive directional result.
7. **Validate and report** — Flag routing failures, distant snaps, missing evidence, and other review conditions.
8. **Export results** — Produce GeoJSON and diagnostic reports for inspection.

### Directional classification

For a candidate location \(x\), the planned conservative metric is:

\[
m(x)=\max(m_{\text{out}}(x),m_{\text{back}}(x))
\]

This prevents a location from appearing serviceable solely because the outbound journey is easier than the return journey.

Distance-based and travel-time-based classification will remain distinct modes. Travel-time estimates must be interpreted according to the routing model and its traffic-data limitations.

## Technology Stack

| Component | Purpose |
|---|---|
| Python | Core processing pipeline |
| H3 | Spatial grid generation and indexing |
| OpenStreetMap (OSM) | Road-network data |
| Valhalla | Road-network routing |
| GeoJSON | Zone and diagnostic exports |
| pytest | Automated tests and regression checks |

Additional geocoding, address-quality checks, and cross-router validation may be introduced in later milestones where they provide measurable value.

## Project Structure

```text
roadzone/
├── app.py                    # Streamlit viewer: map, legend, new runs
├── configs/stevens_creek.yaml
├── zonegen/                  # the engine
│   ├── pipeline.py           # grid, resumable parallel runs, lettering, display fallback
│   ├── router.py             # Valhalla adapter: snap, route out/back, trace, per-probe status
│   ├── classify.py           # bands and the longest-dwell corridor classifier
│   ├── refs.py               # highway names and signed directions from OSM route relations
│   └── report.py             # cells.geojson + failure_report.md
├── scripts/                  # fetch data, 7-site sweep, scenarios, OSRM cross-check, run comparison
├── tests/                    # unit tests, hard_cases.yaml, scenarios.yaml
├── docs/                     # decisions.md, m1-failure-report.md
└── runs/                     # generated outputs (git-ignored)
```

## Initial Milestone: M1

The first milestone is intentionally limited to one target market.

### Scope

- Configure a single service origin in the Stevens Creek area.
- Generate candidate H3 cells.
- Route candidates through a pinned Valhalla and OSM dataset.
- Capture snap distances and routing failures.
- Calculate outbound and return distances.
- Apply configurable classification bands.
- Export a raw zone map and failure report.
- Test against a small, curated set of known addresses and difficult routing cases.

### Deliverables

- Reproducible local generation pipeline.
- GeoJSON output for map inspection.
- Routing and snapping diagnostics.
- Failure report with explicit reason codes.
- Initial hard-case test results.

### Out of scope for M1

- Production API or multi-tenant service.
- Customer-facing map UI.
- GoHighLevel (GHL) integration or dispatch mutations.
- Multi-market batch processing.
- Capacity planning and operational optimization.

These can be evaluated after the initial prototype demonstrates useful, repeatable results.

## Accuracy and Reliability

RoadZone is intended to make its decisions inspectable, not simply produce a map that looks plausible.

The validation approach will include:

- A curated set of known addresses and difficult routing cases.
- Snap-distance diagnostics and configurable snap limits.
- Explicit handling of failed or incomplete routes.
- Separate outbound and return metrics.
- Versioned routing configuration and map-data snapshots.
- Defined acceptance metrics with a documented denominator.
- A `review_required` outcome when available evidence is insufficient.

**Accuracy targets are not yet validated.** Any target such as 95% or 99% must be defined against a specific ground-truth set and outcome—such as zone assignment, band classification, or address-level correctness—before it can be treated as a meaningful performance claim.

## Design Principles

**Road-network truth over geometric proximity**  
Straight-line distance can help generate candidates, but should not replace road-routing evidence for final classification.

**Reproducibility over hidden assumptions**  
Pin map-data versions, routing configuration, and classification thresholds so runs can be compared.

**Explicit uncertainty over false confidence**  
Failed routes, distant snaps, and incomplete evidence must be surfaced for review.

**Small, measurable milestones**  
Prove the single-market pipeline before expanding into more complex infrastructure or product features.

**Separation of concerns**  
Zone generation and classification should not directly trigger dispatch, booking, or CRM mutations.

## Development Roadmap

| Milestone | Focus |
|---|---|
| M1 | Single-market routing, zone generation, GeoJSON, and failure diagnostics |
| M2 | Expanded validation, routing cross-checks, and performance improvements |
| M3 | Address-quality enhancements and broader classification validation |
| M4 | Multi-market validation |
| M5 | Capacity scenarios and operational planning |

The later milestones are proposed development phases, not completed deliverables or committed dates.

## Running the Project

Requires [uv](https://docs.astral.sh/uv/) and about 12 GB of free RAM for the tile build. Docker is not needed: Valhalla runs in-process via `pyvalhalla`.

```sh
uv sync                                                    # Python 3.12 + pinned deps
./scripts/fetch_data.sh                                    # pinned Geofabrik California snapshot + boundary -> data/
uv run python -m zonegen build-tiles configs/stevens_creek.yaml
uv run pytest                                              # classifier unit tests (no router needed)
uv run python -m zonegen run configs/stevens_creek.yaml --max-probes 200   # smoke test
uv run python -m zonegen run configs/stevens_creek.yaml    # full run; resumable
uv run streamlit run app.py                                # map viewer at http://localhost:8501
uv run python -m scripts.sweep                             # same pipeline at 7 California test bases
uv run python -m scripts.compare_runs runs/OLD:runs/NEW    # per-cell band/corridor changes between two runs
uv run python -m scripts.scenarios                         # 23 tricky cases + public OSRM cross-check -> runs/scenarios.md
uv run python -m scripts.crosscheck runs/<run_id>          # 200-cell road-mile check vs a local OSRM (below)
./scripts/package.sh runs/<run_id>                         # zip the M1 deliverables for reviewers (not committed)
```

The local OSRM cross-check needs Docker (port 5050; macOS uses 5000 for AirPlay):

```sh
./scripts/fetch_data.sh california/norcal-261018   # smaller NorCal extract; fits Docker's default memory
mkdir -p data/osrm && ln -f data/norcal-261018.osm.pbf data/osrm/norcal.osm.pbf
IMG=ghcr.io/project-osrm/osrm-backend:v26.4.0
docker run --rm -v "$PWD/data/osrm:/data" $IMG osrm-extract -p /opt/car.lua /data/norcal.osm.pbf
docker run --rm -v "$PWD/data/osrm:/data" $IMG osrm-partition /data/norcal.osrm
docker run --rm -v "$PWD/data/osrm:/data" $IMG osrm-customize /data/norcal.osrm
docker run -d --name roadzone-osrm -p 127.0.0.1:5050:5000 -v "$PWD/data/osrm:/data" $IMG osrm-routed --algorithm mld /data/norcal.osrm
```

Each run writes `runs/<run_id>/cells.geojson`, `failure_report.md` and `hard_cases_results.csv`. The run ID is a hash of the config, the snapshot and the classifier version, so rerunning resumes, and `--fresh` starts over. Decisions and draft accuracy definitions are in [docs/decisions.md](docs/decisions.md).

## Data and Reproducibility

- Do not commit API keys, credentials, or private configuration.
- Do not commit large routing tiles or generated datasets.
- Keep generated run artifacts out of Git unless intentionally included as small, sanitized test fixtures.
- Record the OSM snapshot, router version, and configuration used for each run.
- Respect applicable OpenStreetMap data attribution and licensing requirements.

## Current Limitations

- RoadZone is an M1 proof of concept: agreement with a second router is measured, but real-world accuracy is not, until the service director's review.
- The base point is a placeholder, not the dealer-confirmed van entrance.
- Corridors are named after the longest-driven highway, so a later highway can dominate (e.g. Half Moon Bay labelled I-280, not CA-92).
- Hill and park land whose only road is a track is "unknown" at cell level; real homes there are resolved per address.
- Routing results depend on the quality and version of the underlying road network.
- Snapping to a road does not guarantee that the destination is reachable or correctly represented.
- Travel-time estimates without live traffic should not be treated as real-time ETAs.
- Service-zone acceptance criteria require validation against known addresses and real-world service data.

## Intended Outcome

RoadZone aims to provide a transparent, reproducible foundation for generating mobile service territories that reflect road accessibility, classify serviceability consistently, and expose uncertainty before the results are used in operational decisions.
