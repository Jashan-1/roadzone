"""Cross-check a run's road miles against an OSRM server on a band-stratified cell sample.

Usage (repo root): uv run python -m scripts.crosscheck runs/<run_id> [--osrm http://localhost:5050] [--per-band 25]
       [--edge 50] [--seed 7] [--exclude cells.json ...]   (exclude: JSON lists of cell ids, e.g. earlier samples)
Writes <run>/crosscheck.md and <run>/crosscheck_sample.json. OSRM is a different engine on the same OSM data: a cross-check, not ground truth.
"""
import argparse
import json
import random
import statistics
import urllib.request
from pathlib import Path

from zonegen.classify import band_edges, band_index

MI = 1609.344


def osrm(server: str, a: dict, b: dict) -> dict | None:
    url = f"{server}/route/v1/driving/{a['lon']},{a['lat']};{b['lon']},{b['lat']}?overview=false&steps=true"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
    except OSError:
        return None
    return data["routes"][0] | {"summary": data["routes"][0]["legs"][0]["summary"]} if data.get("code") == "Ok" else None



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--osrm", default="http://localhost:5050")
    ap.add_argument("--per-band", type=int, default=25)
    ap.add_argument("--edge", type=int, default=50, help="extra cells within 0.5 mi of a band edge")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--exclude", type=Path, nargs="*", default=[], help="JSON lists of cell ids to leave out")
    a = ap.parse_args()
    excluded = {cid for f in a.exclude for cid in json.loads(f.read_text())}

    meta = json.loads((a.run / "run_meta.json").read_text())
    c = meta["coverage"]
    hub, step, limit = c["hub_miles"] * MI, c["band_step_miles"] * MI, c["limit_miles"] * MI
    edges = [*band_edges(hub, step, limit), limit]
    cells = [r for r in map(json.loads, (a.run / "probes.jsonl").read_text().splitlines())
             if r["kind"] == "cell" and r["status"] == "centroid_sampled" and r.get("band") is not None
             and r["id"] not in excluded]
    rng = random.Random(a.seed)
    by_band = {}
    for r in cells:
        by_band.setdefault(r["band"], []).append(r)
    sample = [r for b in sorted(by_band) for r in rng.sample(by_band[b], min(a.per_band, len(by_band[b])))]
    near = [r for r in cells if r not in sample and min(abs(r["m_dist"] - e) for e in edges) < 0.5 * MI]
    sample += rng.sample(near, min(a.edge, len(near)))

    (a.run / "crosscheck_sample.json").write_text(json.dumps([r["id"] for r in sample]))
    base = meta["base_snap"] or {}
    rows = []
    for r in sample:
        o1, o2 = osrm(a.osrm, base, r["snap"]), osrm(a.osrm, r["snap"], base)
        if not (o1 and o2):
            continue
        om = max(o1["distance"], o2["distance"])
        rows.append({"cell": r["id"], "band": r["band"], "osrm_band": band_index(om, hub, step, limit),
                     "ours_mi": round(r["m_dist"] / MI, 1), "osrm_mi": round(om / MI, 1),
                     "ratio": round(r["m_dist"] / om, 2), "osrm_roads": o1["summary"],
                     "ours_corridor": " | ".join((r.get("corridor") or {}).get("family_key") or []) or "-",
                     "group": "recovered past a track" if "snapped_past_track" in r["reasons"] else "never near a track"})

    within = sum(abs(x["ratio"] - 1) <= 0.10 for x in rows)
    agree = sum(x["band"] == x["osrm_band"] for x in rows)
    worst = sorted(rows, key=lambda x: -abs(x["ratio"] - 1))[:10]
    md = [f"# OSRM cross-check: {meta['run_id']}", "",
          "OSRM is a different engine on the same OSM data: a cross-check, not ground truth.", "",
          f"- Cells compared: {len(rows)} ({a.per_band} per band + {a.edge} within 0.5 mi of a band edge)",
          f"- Road miles within ±10%: **{within}/{len(rows)}** ({within / max(len(rows), 1):.0%})",
          f"- Same distance band: **{agree}/{len(rows)}** ({agree / max(len(rows), 1):.0%})",
          f"- Median ratio ours/OSRM: {statistics.median(x['ratio'] for x in rows):.2f}",
          f"- Sample: seed {a.seed}; excluded {len(excluded)} cells used before", "",
          "## By snap group", "", "| group | cells | within ±10% | same band |", "|---|---|---|---|"]
    for g in sorted({x["group"] for x in rows}):
        gr = [x for x in rows if x["group"] == g]
        md.append(f"| {g} | {len(gr)} | {sum(abs(x['ratio'] - 1) <= 0.10 for x in gr) / len(gr):.0%} | "
                  f"{sum(x['band'] == x['osrm_band'] for x in gr) / len(gr):.0%} |")
    track_only = sum(1 for r in map(json.loads, (a.run / "probes.jsonl").read_text().splitlines()) if "snap_track" in r["reasons"])
    md += [f"| track only (not routed, no comparison) | {track_only} | - | - |", "",
          "## Largest disagreements", "", "| " + " | ".join(worst[0]) + " |", "|" + "---|" * len(worst[0])]
    md += ["| " + " | ".join(str(v) for v in x.values()) + " |" for x in worst]
    (a.run / "crosscheck.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
