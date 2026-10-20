"""The two M1 deliverables: raw cell map (GeoJSON) and failure report (Markdown), plus the hard-case CSV."""
import csv
import json
import resource
import sys
from collections import Counter

import h3

SNAP_BUCKETS = [(0, 10), (10, 25), (25, 50), (50, 100), (100, 200), (200, 300), (300, 500)]
NOTICE = ("**POC, pre-kickoff.** Not an approved Milestone 1 run. Not a published plan. "
          "Time bands are free-flow estimates (no traffic data).")


def _props(r: dict) -> dict:
    c = r.get("corridor") or {}
    s = r.get("snap") or {}
    return {
        "h3": r["id"], "status": r["status"], "zone_code": r.get("zone_code"),
        "band": r.get("band"), "band_time": r.get("band_time"),
        "out_m": r.get("out_m"), "back_m": r.get("back_m"), "out_s": r.get("out_s"), "back_s": r.get("back_s"),
        "m_dist_mi": round(r["m_dist"] / 1609.344, 2) if r.get("m_dist") is not None else None,
        "m_time_min": round(r["m_time"] / 60, 1) if r.get("m_time") is not None else None,
        "center_lat": r["lat"], "center_lon": r["lon"],
        "snap_lat": s.get("lat"), "snap_lon": s.get("lon"), "snap_dist_m": s.get("dist_m"), "snap_way_id": s.get("way_id"),
        "corridor_status": c.get("status"), "family_key": " | ".join(c["family_key"]) if c.get("family_key") else None,
        "refs": " ; ".join(c.get("refs") or []) or None, "direction": c.get("direction"),
        "direction_method": c.get("direction_method"), "dwell_s": c.get("dwell_s"),
        "tied": json.dumps(c["tied"]) if c.get("tied") else None,
        "candidate_zones": ",".join(r.get("candidate_zones") or []) or None,
        "display_corridor_id": r.get("display_corridor_id"), "display_basis": r.get("display_basis"),
        "hatch_status": r.get("hatch_status"), "verification_required": r.get("verification_required"),
        "reason_codes": ",".join(r.get("reasons") or []) or None, "family_key_version": r.get("family_key_version"),
    }


def _geom(cid: str) -> dict:
    ring = [[round(lon, 6), round(lat, 6)] for lat, lon in h3.cell_to_boundary(cid)]
    return {"type": "Polygon", "coordinates": [ring + ring[:1]]}


def _hist(cells: dict) -> list[tuple[str, int]]:
    rows = []
    dists = [r["snap"]["dist_m"] for r in cells.values() if r.get("snap")]
    for lo, hi in SNAP_BUCKETS:
        rows.append((f"{lo}–{hi} m", sum(lo <= d < hi for d in dists)))
    rows.append(("no road ≤500 m", sum(1 for r in cells.values() if "snap_failed" in r["reasons"])))
    return rows


def _table(header: list, rows: list) -> str:
    out = ["| " + " | ".join(map(str, header)) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in rows]
    return "\n".join(out)


def _score(h: dict, rec: dict) -> dict:
    exp = h.get("expected") or {}
    c = rec.get("corridor") or {}
    row = {"id": h["id"], "name": h["name"], "category": h["category"], "status": rec.get("status"),
           "zone_code": rec.get("zone_code"), "band": rec.get("band"),
           "m_dist_mi": round(rec["m_dist"] / 1609.344, 1) if rec.get("m_dist") else None,
           "refs": " ; ".join(c.get("refs") or []), "direction": c.get("direction"),
           "reasons": ",".join(rec.get("reasons") or []), "confirmed_by": h.get("confirmed_by", "unconfirmed")}
    checks = {}
    if "status" in exp:
        checks["status_ok"] = rec.get("status") == exp["status"]
    if "band" in exp:
        checks["band_ok"] = rec.get("band") == exp["band"]
    if "refs_any" in exp:
        checks["corridor_ok"] = list(c.get("refs") or []) in exp["refs_any"] and \
            ("direction" not in exp or c.get("direction") == exp["direction"])
    row.update(checks)
    row["pass"] = all(checks.values()) if checks else None
    return row


def write_outputs(out, cfg, meta, cells, hard_out, hard):
    feats = [{"type": "Feature", "id": cid, "geometry": _geom(cid), "properties": _props(cells[cid])}
             for cid in sorted(cells)]
    b = cfg["base"]
    feats.append({"type": "Feature", "id": "base", "geometry": {"type": "Point", "coordinates": [b["lon"], b["lat"]]},
                  "properties": {"kind": "base", "base_confirmed": b["confirmed"]}})
    fc = {"type": "FeatureCollection", "properties": {"run_id": meta["run_id"], "notice": NOTICE,
                                                     "base_confirmed": b["confirmed"],
                                                     "family_key_version": meta["family_key_version"]},
          "features": feats}
    (out / "cells.geojson").write_text(json.dumps(fc, separators=(",", ":")))

    by_id = {h["id"]: h for h in hard}
    scored = [_score(by_id[r["id"].removeprefix("hc:")], r) for r in hard_out]
    cols = list(dict.fromkeys(k for s in scored for k in s))
    if scored:
        with (out / "hard_cases_results.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(scored)

    status = Counter(r["status"] for r in cells.values())
    reasons = Counter(x.split(":")[0] for r in cells.values() for x in r["reasons"])
    covered = [r for r in cells.values() if r["status"] in ("centroid_sampled", "mixed")]
    post_hub = [r for r in covered if (r.get("band") or 0) > 0]
    cstat = Counter((r.get("corridor") or {}).get("status", "no_trace") for r in post_hub)
    dmeth = Counter((r.get("corridor") or {}).get("direction_method") for r in post_hub
                    if (r.get("corridor") or {}).get("status") == "supported")
    zones = Counter(r["zone_code"] for r in covered if r.get("zone_code"))
    fams = Counter(((r.get("corridor") or {}).get("family_key") and " | ".join(r["corridor"]["family_key"]))
                   for r in post_hub if (r.get("corridor") or {}).get("status") == "supported")
    shadow = [r for r in cells.values() if "snap_far" in r["reasons"]]
    shadow_bands = Counter("outside" if r.get("band") is None else r["band"] for r in shadow)
    crosstab = Counter((r.get("band"), r.get("band_time")) for r in covered)
    rss_unit = 1e6 if sys.platform == "darwin" else 1e3  # ru_maxrss is bytes on macOS, KiB on Linux
    rss_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
              + resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss) / rss_unit

    md = [f"# Failure report — {meta['run_id']}", "", NOTICE, "",
          f"- **Base entrance confirmed:** {b['confirmed']}" + ("" if b["confirmed"] else
            " — placeholder public-road point; every result is `base_unconfirmed`."),
          f"- **20-address director review:** not run (addresses not supplied).",
          "", "## Frozen inputs", "",
          _table(["input", "value"], [
              ["OSM snapshot", meta["snapshot"].get("pbf")], ["PBF sha256", meta["snapshot"].get("sha256")],
              ["router", meta["valhalla"]], ["family_key_version", meta["family_key_version"]],
              ["base (lat, lon)", f"{b['lat']}, {b['lon']}"], ["base snap", json.dumps(meta["base_snap"])],
              ["coverage", json.dumps(cfg["coverage"])], ["time view (free-flow)", json.dumps(cfg["time_view"])],
              ["extent radius km / H3 res", f"{cfg['grid']['extent_radius_km']} / {cfg['grid']['resolution']}"],
              ["snap caps", f"decision {cfg['snap']['decision_cap_m']} m, shadow {cfg['snap']['shadow_cap_m']} m"],
              ["search_filter", json.dumps(cfg["snap"]["search_filter"])],
              ["costing", json.dumps(cfg["routing"])], ["backbone classes", ", ".join(cfg["backbone_classes"])],
              ["ref index", json.dumps(meta["refs_counts"])], ["request budget", cfg["request_budget"]]]),
          "", "## Reproduce", "", "```sh", "./scripts/fetch_data.sh && uv run python -m zonegen build-tiles "
          f"{meta['config']}", f"uv run python -m zonegen run {meta['config']} --fresh", "```",
          "", "## Counts", "",
          _table(["measure", "value"], [["candidate cells", meta["candidate_cells"]],
                                        ["Valhalla calls (total, incl. resumed)", meta["calls"]],
                                        ["elapsed this session (s)", meta["elapsed_s_this_session"]],
                                        ["peak RSS main+largest child (MB)", round(rss_mb)]]
                 + [[f"cells: {k}", v] for k, v in sorted(status.items())]),
          "", "## Snap distance histogram (centroid → nearest permitted edge)", "",
          _table(["bucket", "cells"], _hist(cells)),
          "", f"**Snap rule:** a cell's probe is accepted within {cfg['snap']['decision_cap_m']} m of its centre, "
          f"or anywhere up to {cfg['snap']['shadow_cap_m']} m if the road point is inside the cell "
          f"({sum('snap_in_cell' in r['reasons'] for r in cells.values())} cells, reason `snap_in_cell`). "
          f"{len(shadow)} cells snapped outside their cell; they were routed but stay `unknown: snap_far`. "
          f"Their shadow bands would be: "
          + (", ".join(f"{k}: {v}" for k, v in sorted(shadow_bands.items(), key=str)) or "none") + ".",
          "", "## Corridor evidence (covered, post-Hub cells)", "",
          _table(["corridor status", "cells"], sorted(cstat.items())), "",
          _table(["direction method", "cells"], sorted(dmeth.items(), key=str)), "",
          _table(["family_key", "cells"], fams.most_common()), "",
          _table(["zone", "cells"], sorted(zones.items())),
          "", "## Reason codes (cells)", "", _table(["reason", "cells"], reasons.most_common()),
          "", "## Distance band × free-flow time band (covered cells)", "",
          _table(["distance band", "time band", "cells"], [[k[0], k[1], v] for k, v in sorted(crosstab.items(), key=str)]),
          "", "## Hard cases", ""]
    if scored:
        md.append(_table(cols, [[s.get(k) for k in cols] for s in scored]))
        md.append(f"\nPass: {sum(1 for s in scored if s['pass'])}/{sum(1 for s in scored if s['pass'] is not None)} "
                  "of cases with expectations. Expectations are engineering guesses, not director-confirmed.")
    md += ["", "## Recommendation", "", "_Proceed / narrow / stop — to be written after a human reviews this map._", ""]
    (out / "failure_report.md").write_text("\n".join(md))
    (out / "run_meta.json").write_text(json.dumps(meta, indent=2))
