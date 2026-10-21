# RoadZone M1: failure report and recommendation

**Status:** proof of concept, pre-kickoff. Not an approved Milestone 1 run and not a published plan.
**Date:** 2026-10-21 · **Run:** `stevens-creek-poc-c817c05b38` · **Spec:** Technical Specification v0.2, §16.1

> **Read every number with these caveats:**
> - **Provisional base.** The depot point (37.32305, -121.97000) is a placeholder on Stevens Creek Blvd, not the dealer-confirmed van entrance. Every number shifts if it moves.
> - **Road miles are the v1 rule. Minutes are free-flow and optimistic** (no traffic data).
> - **OSRM is a cross-check, not ground truth.** It is a second open-source router on the same OpenStreetMap data, so agreement shows consistency, not real-world correctness.
> - **All expectations are engineering judgement** until the service director reviews them.

## Recommendation: proceed, with known limits

The road-aware approach works and is explainable:
- It agrees with an independent router on road miles within ±10% for **88–94% of cells across three untouched samples (reference 88%)**, and on the distance band for 88–92% (reference 88%).
- It splits same-distance areas by highway as intended (Menlo Park, Milpitas and Newark each get their own corridor).
- It marks uncertainty instead of hiding it.

The real gate now is the **service director's review of 20 known addresses**. Everything so far is router against router.

**Known limits to carry forward:**
1. **Longest-stretch labels.** A trip is named after the highway it spends longest on, so Half Moon Bay is labelled I-280, not CA-92. The spec says to report this, not add route forcing in v1.
2. **Free-flow minutes.** Time bands are optimistic. Faster/slower speed data changes route choice and can move road-mile bands, so traffic is a separate later profile (M2), never an input to distance bands.
3. **Hill and park land is "unknown" at cell level.** 3,774 cells whose nearest road is a farm, forest or park track are not zoned. Real hill homes are resolved per address: all 8 tested got a band, with a review flag where needed (see "Hill homes" below).

## What was built

A repeatable local script that:
1. Covers the area with H3 hexagons (resolution 8, about 0.7 km² each).
2. Snaps each one to a drivable road.
3. Routes it out and back with Valhalla.
4. Assigns the distance band on the longer direction.
5. Names the corridor from the post-Hub highway with the longest drive time.

It writes the two M1 deliverables: a raw GeoJSON cell map and an automatic failure report per run. A Streamlit viewer, a tricky-scenario suite and an OSRM cross-check sit on top.

| Input | Value |
|---|---|
| Map data | Geofabrik California extract, `california-261018` (OSM timestamp 2026-10-18), sha256 `54017130…` |
| Router | pyvalhalla 3.9.1, Valhalla built-in speeds |
| Coverage | 50 road miles, 5-mile Hub, 10-mile bands, max(outbound, return) |
| Grid | H3 resolution 8, 82 km candidate extent: 27,261 cells, 61,427 router calls, 107 s on 10 workers |

Reproduce: see the README.

## Results

### Cell map (Stevens Creek, 50 miles)

| Cells | Count | Meaning |
|---|---|---|
| Zoned (`centroid_sampled`) | 6,313 | Routed both ways, inside 50 miles, band and corridor assigned |
| Mixed | 2 | A test address in the cell disagrees with the cell's centre |
| Outside coverage | 4,952 | Confirmed more than 50 road miles |
| Unknown | 15,994 | No road within 500 m (mostly ocean and bay), track-only land (3,774), or a road just outside the cell (96) |

Snap evidence:
- **4,925 cells** were accepted because their road point lies inside the cell, even though it's 100–500 m from the centre (`snap_in_cell`).
- **1,307 cells** whose nearest road was a track were resolved to a real road (`snapped_past_track`).

### Independent cross-check (local OSRM, 200 cells, 25 per band plus 50 near band edges)

| Sample (never used for tuning) | Road miles within ±10% | Same distance band |
|---|---|---|
| Reproducible reference (seed 2026, sorted) | **88%** | **88%** |
| Two other untouched draws | 92% and 94% | 88% and 92% |

- **Band disagreements are mostly boundary hair-splits.** On the reference sample, 15 of the 23 band disagreements have one router within 0.5 miles of a band edge. Only **8 of 200 (4%)** disagree away from an edge.
- **Cells recovered past a track score in line with the rest:** 95% within ±10% and 90% same band (n=21).

### Corridor checks: edges and forks

- **Directed-edge validation:** 9 zoned cells are `edge_unconfirmed`. Under half of their main-highway road segments are shared by at least 3 cells of the same corridor. They are flagged for review, not regrouped.
- **Fork candidates (recorded, not promoted):** 11 corridors split into 2+ branches of at least 10 cells after leaving the main highway. Examples:
  - **I 680 N:** stays local 465, continues onto I 580 101.
  - **US 101 S:** stays local 532, CA 152 114, CA 25 66.
  - **CA 17 S:** CA 1 518, stays local 495, CA 9 98.

  The spec's cross-branch travel test (at least 10 minutes extra between branches) is not evaluated; that and any zone split belong to M2. The full table is in the run's failure report.

### Tricky scenarios (31 public places, run through the same classifier, cross-checked with public OSRM)

| Group | Pass | Notes |
|---|---|---|
| 1. Corridors at the same distance | 7/7 | Walnut Creek: **expectation corrected**. I first expected it covered via I-680, but both routers put it just past 50 miles (ours 50.9, OSRM 50.6), so "outside" is right unless the director says it's served. |
| 2. Water and bridges | 5/5 | Bay and reservoir points are unknown, never outside |
| 3. Mountains | 3/5 | Half Moon Bay is labelled I-280 (limit 1). Saratoga Gap is borderline (road/straight-line 1.397 against a guessed 1.4 bar), so the expectation needs review. |
| 4. Freeway traps | 2/2 | Points on I-280 and CA-85 snap to a non-motorway road |
| 5. Boundaries | 4/4 | Depot, next door, Gilroy at the edge, Monterey outside |
| 6. Hill homes (address path) | 8/8 | All get a band. Two have a "needs review" corridor (no highway number); two track-access homes are routed and flagged `access_via_track`. |

Geocoding and ZIP-batch cases are not applicable yet (Milestone 3). Stevens Creek hard cases: 16/17. The failure is Livermore labelled I-880 North, which is limit 1.

### Decisions made with evidence

Full table in [decisions.md](decisions.md).
- **Default speeds kept.** OpenStreetMapSpeeds made minutes realistic but bent routes, e.g. Alviso went from 8.5 to 15.7 miles. On the cross-check, road miles within ±10% dropped from 84% to 72%.
- **Snap rule:** a road inside the cell counts.
- **Signed highway direction:** the north/south tag on the highway's route relation is used.
- **Track handling:** cells look past tracks; addresses keep their own access.
- **Missing map data** is shown as such, never as "no road".

## Not done in M1 (by design)

- Production API, database, dealer UI, publishing, ZIP batch, GHL, geocoding, capacity planning.
- Fork **promotion** and the cross-branch travel test (forks are recorded only), gateways and alternate routes.
- Traffic or rush-hour profiles.
- Multi-market qualification (M4).

## Asks before the v1 gate

1. **Service director:** review 20 known service addresses (expected zone and corridor). This turns engineering expectations into ground truth.
2. **Ash / dealer:** confirm the van entrance coordinates and heading. Every number above is provisional until then.
3. **Ash / dealer:** any historical appointment data (the vans have no GPS or telematics in early SaaS versions), for the one-month replay gate.
