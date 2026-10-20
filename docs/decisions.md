# M1 POC decisions

Status: proof of concept for a CEO demo, **pre-kickoff**. This does not change the approved Technical Spec v0.2 or authorize Milestone 1.

| # | Decision | Why |
|---|---|---|
| 1 | **Snap rule (revised): a cell probe is accepted within 100 m of the centre, or up to 500 m if the road point lies inside the same hexagon** (`snap_in_cell`). Anything else is `unknown: snap_far`. Hard-case addresses keep the strict 100 m rule. | The seven-location sweep showed 97–100% of 100–500 m snaps land inside their own hexagon: the centre is just off-road. A road point inside the cell still probes that cell; one in the neighbouring cell does not. Approved by the user on 2026-10-21. |
| 2 | **Snap filter:** `exclude_ramp`, `exclude_tunnel`, `exclude_bridge`, `max_road_class: trunk`. | Stops centroids from snapping onto freeways, ramps or bridge decks. That is the main centroid-probe trap. |
| 3 | **Distance is primary; time bands are free-flow.** | Valhalla runs here without traffic data. Time bands are a display view computed from the same routes and are never converted from miles. |
| 4 | **Only the outbound route is traced** (`/trace_attributes`, edge_walk, then walk_or_snap, then `trace_failed`). | The family key is outbound-only (§6.5). The return route only checks coverage and access. That gives 3–4 calls per cell instead of 5. |
| 5 | **Refs come from OSM route relations** (`network` US:I / US:US / US:CA) in the same pinned PBF, with way `ref` tags as a fallback. The direction comes from the member role or the relation's `direction` tag; if neither exists, from the entry-to-exit bearing quadrant. | Way refs are inconsistent; relations give canonical refs and signed direction. A way that sits in both directional relations has no signed direction. |
| 6 | **In-process Valhalla (pyvalhalla 3.9.1), no Docker.** | One `uv sync` gives the tile builder and the router. One Actor per worker process, no HTTP server. |
| 7 | **The base is a placeholder** on Stevens Creek Blvd (`base_confirmed: false`). | The spec forbids guessing the van entrance. Changing it is a one-line config edit plus a rerun. |
| 8 | **Display letters are clockwise** by the circular-mean bearing of member cells from the base. The zone ID is the family key plus the band. | Spec §6.8. Letters are display only; the family key is the identity. |
| 9 | **Hatched fallback colour** is the nearest supported corridor by H3 grid distance, with ties broken by corridor id. | Spec §6.8. It is display only and never feeds classification. |
| 10 | **Routes use the same `search_filter` as the snap.** | Otherwise Valhalla re-snaps the base and the destination without the filter, so routes can start on a freeway while the evidence shows a side street. |
| 11 | **A far snap (100–500 m) always means `unknown`**, even when the route is long or missing. | Spec §6.3: a cap exceedance gives an unknown cell. It never becomes `outside_coverage` or `unreachable`. |
| 12 | **Cells outside the extract polygon are `data_unavailable`** and are never routed. | Spec §6.1: missing graph data is not "no road". At South Lake Tahoe, 6,185 of 11,032 "no road" cells were really Nevada. |
| 13 | **The run ID includes a hash of the router, classifier and refs code.** The refs cache is keyed the same way. | A code change can never silently resume results produced by older code. |
| 14 | **`snapshot.json` is written by `build-tiles`, not by the download.** `run` refuses to start if it names a different PBF than the config. | The snapshot record always describes the routing graph that was actually built. |
| 15 | **The signed direction comes from the relation's `direction` tag (north/N…) before the member role.** Roles `forward`/`backward` carry no cardinal direction. | California splits most freeways into north/south relations whose members are `forward`. Letting `forward` win, plus clashes with the undirected parent relation, threw the signed direction away, so 33–47% of compass-guessed directions sat within 15° of a quadrant edge. |

## Draft accuracy definitions (needed before any 99%/95% claim)

These are proposed. Ash needs to approve them.

- **Status-correct:** the result's status (`centroid_sampled` / `unknown` / `outside_coverage` / `unreachable`) matches the reviewed expectation.
- **Band-correct:** the distance band matches the reviewed band. A result within ±0.2 mi of a boundary is reported separately and not counted as an error.
- **Corridor-correct:** the normalized ref set and direction are in the reviewer's list of acceptable answers (more than one sensible corridor is allowed, §15.2).
- **Denominator:** "accuracy" means corridor-correct among matched results. "Match rate" means matched divided by all clean in-scope addresses. `review_required` and `unknown` count against the match rate, never as correct.

## Known POC limits

- Centroid probes only. One centroid does not prove a whole cell (§6.3).
- Hard-case expectations are engineering guesses until a service director confirms them.
- No ferry or toll policy checks beyond the costing penalties.
- Fork promotion and the demand gate are not evaluated (M2).
