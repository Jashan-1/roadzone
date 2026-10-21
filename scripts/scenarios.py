"""Tricky-scenario check: our classifier vs expectations, cross-checked with OSRM's public demo router.

Usage (repo root, tiles built): uv run python -m scripts.scenarios [configs/stevens_creek.yaml]
Writes runs/scenarios.md. OSRM is a different engine on OSM data, so disagreement is evidence, not a verdict.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

import yaml

from zonegen import router
from zonegen.classify import band_index, haversine_m, normalize_ref
from zonegen.pipeline import load_config
from zonegen.refs import load_ref_index

OSRM = "https://router.project-osrm.org/route/v1/driving/{},{};{},{}?steps=true&overview=false"
SLOW_DOWN_S = 1.0  # the public demo server asks for light use


def osrm(a: dict, b: dict) -> dict | None:
    url = OSRM.format(a["lon"], a["lat"], b["lon"], b["lat"])
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "roadzone-poc"}), timeout=30) as r:
            data = json.load(r)
    except OSError:
        return None
    finally:
        time.sleep(SLOW_DOWN_S)
    return data["routes"][0] if data.get("code") == "Ok" else None


def osrm_main_ref(route: dict, hub_m: float) -> str | None:
    """Ref with the most post-Hub seconds along OSRM's steps (a rough longest-dwell analogue)."""
    dwell, travelled = {}, 0.0
    for step in route["legs"][0]["steps"]:
        start, travelled = travelled, travelled + step["distance"]
        if travelled <= hub_m or not step.get("ref"):
            continue
        share = 1.0 if start >= hub_m or step["distance"] == 0 else (travelled - hub_m) / step["distance"]
        for ref in step["ref"].split(";"):
            dwell[normalize_ref(ref)] = dwell.get(normalize_ref(ref), 0) + step["duration"] * share
    return max(dwell, key=dwell.get) if dwell else None


def snap_road_class(lat: float, lon: float) -> str | None:
    res = router._W["actor"].locate({"locations": [{"lat": lat, "lon": lon}], "costing": "auto", "verbose": True})
    edges = res[0].get("edges") or []
    return edges[0]["edge"]["classification"]["classification"] if edges else None


def main(cfg_path: str = "configs/stevens_creek.yaml"):
    cfg = load_config(Path(cfg_path))
    router.init_worker(cfg, load_ref_index(Path(cfg["data"]["pbf"]), Path(cfg["data"]["refs_cache"])))
    cov, base = cfg["coverage_m"], cfg["base"]
    cases = yaml.safe_load(Path("tests/scenarios.yaml").read_text())
    recs = {c["id"]: router.evaluate({"id": f"sc:{c['id']}", "kind": "hard_case", "lat": c["lat"], "lon": c["lon"]})
            for c in cases}
    rows = []
    for c in cases:
        r, corr = recs[c["id"]], recs[c["id"]].get("corridor") or {}
        fam = tuple(corr.get("family_key") or ())
        checks = {}
        if "status" in c:
            checks["status"] = r["status"] == c["status"]
        if "status_not" in c:
            checks["status_not"] = r["status"] != c["status_not"]
        if "refs_any" in c:
            checks["refs"] = list(corr.get("refs") or []) in c["refs_any"]
        if "direction" in c:
            checks["direction"] = corr.get("direction") == c["direction"]
        if "differs_from" in c:
            other = tuple((recs[c["differs_from"]].get("corridor") or {}).get("family_key") or ())
            checks["differs"] = bool(fam) and fam != other
        if c.get("farther_than_circle"):
            circle = band_index(haversine_m((base["lat"], base["lon"]), (c["lat"], c["lon"])), cov["hub"], cov["step"], cov["limit"])
            checks["farther_than_circle"] = r.get("band") is None or (circle is not None and r["band"] > circle)
        if "detour_ratio_min" in c and r.get("m_dist"):
            crow = haversine_m((base["lat"], base["lon"]), (c["lat"], c["lon"]))
            checks["detour_ratio"] = r["m_dist"] / crow >= c["detour_ratio_min"]
        if c.get("snap_not_motorway") and r.get("snap"):
            checks["snap_not_motorway"] = snap_road_class(r["snap"]["lat"], r["snap"]["lon"]) not in ("motorway",)
        if c.get("not_extent_review"):
            checks["not_extent_review"] = "extent_review_required" not in r["reasons"]
        again = router.evaluate({"id": f"sc:{c['id']}", "kind": "hard_case", "lat": c["lat"], "lon": c["lon"]})
        checks["deterministic"] = {k: v for k, v in again.items() if k != "calls"} == {k: v for k, v in r.items() if k != "calls"}

        # independent router: band on max(out, back) road miles and main highway after the Hub
        o_out, o_back = osrm(base, c), osrm(c, base)
        o_band = o_ref = None
        if o_out and o_back:
            o_band = band_index(max(o_out["distance"], o_back["distance"]), cov["hub"], cov["step"], cov["limit"])
            o_ref = osrm_main_ref(o_out, cov["hub"])
        ours_ref = (corr.get("refs") or [None])[0]
        rows.append({
            "group": c["group"], "id": c["id"], "status": r["status"], "band": r.get("band"),
            "miles": round(r["m_dist"] / 1609.344, 1) if r.get("m_dist") else None,
            "corridor": " | ".join(fam) or corr.get("status") or "-",
            "reasons": ",".join(r["reasons"]) or "-",
            "osrm_miles": round(max(o_out["distance"], o_back["distance"]) / 1609.344, 1) if o_out and o_back else None,
            "band_agrees": None if o_band is None or r.get("m_dist") is None else o_band == r.get("band"),
            "ref_agrees": None if not (o_ref and ours_ref) else o_ref == ours_ref, "osrm_ref": o_ref,
            "failed": [k for k, ok in checks.items() if not ok], "pass": all(checks.values()),
        })
        print(c["id"], "PASS" if rows[-1]["pass"] else f"FAIL {rows[-1]['failed']}", flush=True)

    groups = sorted({r["group"] for r in rows})
    md = ["# Tricky-scenario results", "", f"Base {base['lat']}, {base['lon']} (confirmed: {base['confirmed']}). "
          "Expectations are engineering judgement. OSRM = public demo router, a cross-check only.", "",
          "| group | pass | OSRM band agrees | OSRM main highway agrees |", "|---|---|---|---|"]
    for g in groups:
        gr = [r for r in rows if r["group"] == g]
        rate = lambda k: f"{sum(r[k] is True for r in gr)}/{sum(r[k] is not None for r in gr)}"
        md.append(f"| {g} | {sum(r['pass'] for r in gr)}/{len(gr)} | {rate('band_agrees')} | {rate('ref_agrees')} |")
    md += ["", "Groups 6 (geocoding) and 7 (ZIP batch) are not applicable yet: those features are Milestone 3.", "",
           "| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
    md += ["| " + " | ".join("" if v is None else str(v) for v in r.values()) + " |" for r in rows]
    Path("runs/scenarios.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:6 + len(groups)]))


if __name__ == "__main__":
    main(*sys.argv[1:])
