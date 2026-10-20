"""In-process Valhalla adapter (pyvalhalla Actor) and per-probe evaluation (spec §6.3, §6.4, §6.6)."""
import json

import valhalla

from .classify import FAMILY_KEY_VERSION, Segment, band_index, classify_corridor, haversine_m

NO_PATH_CODES = {442, 443}  # "no path could be found" variants: a real negative, not a data outage
_W: dict = {}  # per-process worker state


def init_worker(cfg: dict, refs: dict | None = None):
    _W["actor"] = valhalla.Actor(cfg["data"]["valhalla_config"])
    _W["cfg"] = cfg
    if refs is None:
        from .refs import load_ref_index
        from pathlib import Path
        refs = load_ref_index(Path(cfg["data"]["pbf"]), Path(cfg["data"]["refs_cache"]))
    _W["refs"] = refs


def _call(action: str, req: dict) -> tuple[dict | None, int | None]:
    _W["calls"] = _W.get("calls", 0) + 1
    try:
        return getattr(_W["actor"], action)(req), None
    except (RuntimeError, valhalla.ValhallaError) as e:
        try:
            return None, json.loads(str(e)).get("error_code")
        except (ValueError, AttributeError):
            return None, -1


def decode_polyline6(s: str) -> list[tuple[float, float]]:
    pts, idx, lat, lon = [], 0, 0, 0
    while idx < len(s):
        vals = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(s[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            vals.append(~(result >> 1) if result & 1 else result >> 1)
        lat, lon = lat + vals[0], lon + vals[1]
        pts.append((lat / 1e6, lon / 1e6))
    return pts


def snap(lat: float, lon: float) -> dict | None:
    """Closest acceptable road edge within the shadow cap, via /locate."""
    cfg = _W["cfg"]["snap"]
    loc = {"lat": lat, "lon": lon, "search_cutoff": cfg["shadow_cap_m"], "search_filter": cfg["search_filter"]}
    res, _ = _call("locate", {"locations": [loc], "costing": _W["cfg"]["routing"]["costing"], "verbose": False})
    edges = (res or [{}])[0].get("edges") or []
    best = None
    for e in edges:
        pt = (e["correlated_lat"], e["correlated_lon"])
        d = haversine_m((lat, lon), pt)
        if best is None or d < best["dist_m"]:
            best = {"lat": pt[0], "lon": pt[1], "dist_m": round(d, 1), "way_id": e.get("way_id"),
                    "side_of_street": e.get("side_of_street")}
    return best


def route(a: dict, b: dict) -> tuple[dict | None, int | None]:
    r, flt = _W["cfg"]["routing"], _W["cfg"]["snap"]["search_filter"]
    # same filter as snap(), so routes start/end on the edge the evidence records (not a nearby freeway)
    req = {"locations": [{"lat": p["lat"], "lon": p["lon"], "search_filter": flt} for p in (a, b)],
           "costing": r["costing"], "costing_options": r["costing_options"],
           "directions_type": "none", "units": "kilometers"}
    res, err = _call("route", req)
    if res is None:
        return None, err
    s = res["trip"]["summary"]
    return {"m": s["length"] * 1000, "s": s["time"], "shape": res["trip"]["legs"][0]["shape"]}, None


def trace_segments(shape: str) -> tuple[list[Segment] | None, list[str]]:
    """edge_walk the route's own shape; fall back to walk_or_snap, then report trace_failed (never silent)."""
    r = _W["cfg"]["routing"]
    attrs = ["edge.way_id", "edge.length", "edge.road_class", "edge.use", "edge.begin_heading",
             "edge.begin_shape_index", "edge.end_shape_index", "node.elapsed_time", "shape"]
    for match, reasons in (("edge_walk", []), ("walk_or_snap", ["trace_fallback_walk_or_snap"])):
        req = {"encoded_polyline": shape, "shape_match": match, "costing": r["costing"],
               "costing_options": r["costing_options"], "filters": {"attributes": attrs, "action": "include"}}
        res, _ = _call("trace_attributes", req)
        if res and res.get("edges"):
            pts = decode_polyline6(res["shape"])
            segs, m, t = [], 0.0, 0.0
            for e in res["edges"]:
                end_m = m + e["length"] * 1000
                end_t = e.get("end_node", {}).get("elapsed_time", t)
                segs.append(Segment(e["way_id"], m, end_m, t, end_t, e.get("road_class", ""), e.get("use", ""),
                                    pts[e["begin_shape_index"]], pts[e["end_shape_index"]], e.get("begin_heading", 0)))
                m, t = end_m, end_t
            return segs, reasons
    return None, ["trace_failed"]


def evaluate(probe: dict) -> dict:
    """Route one probe (cell centroid or reviewed point) out and back and classify it. Pure function of inputs."""
    _W["calls"] = 0
    cfg = _W["cfg"]
    cov, tv = cfg["coverage_m"], cfg["time_view_s"]
    rec = {**probe, "reasons": [], "family_key_version": FAMILY_KEY_VERSION}
    sn = snap(probe["lat"], probe["lon"])
    rec["snap"] = sn
    if sn is None:
        rec.update(status="unknown", calls=_W["calls"])
        rec["reasons"].append("snap_failed")
        return rec
    far = sn["dist_m"] > cfg["snap"]["decision_cap_m"]
    base = cfg["base"]
    out, e_out = route(base, sn)
    back, e_back = route(sn, base)
    if out is None or back is None:
        codes = {c for c in (e_out, e_back) if c is not None}
        # a far snap is never trusted enough to call a cell confirmed unreachable (spec §6.3)
        rec["status"] = "unreachable" if codes <= NO_PATH_CODES and not far else "unknown"
        rec["reasons"].append("snap_far" if far else
                              "unreachable" if rec["status"] == "unreachable" else f"route_failed:{sorted(codes)}")
        rec["calls"] = _W["calls"]
        return rec
    m_dist, m_time = max(out["m"], back["m"]), max(out["s"], back["s"])
    rec.update(out_m=round(out["m"], 1), back_m=round(back["m"], 1), out_s=round(out["s"], 1),
               back_s=round(back["s"], 1), m_dist=round(m_dist, 1), m_time=round(m_time, 1))
    rec["band_time"] = band_index(m_time, tv["hub"], tv["step"], tv["limit"])
    band = band_index(m_dist if cov["metric"] == "distance" else m_time, cov["hub"], cov["step"], cov["limit"])
    rec["band"] = band
    corridor = None
    if band is not None and band > 0:
        segs, treasons = trace_segments(out["shape"])
        rec["reasons"] += treasons
        if segs:
            refs = _W["refs"]
            corridor = classify_corridor(segs, cov["hub"], cov["metric"], set(cfg["backbone_classes"]),
                                         refs["way_refs"], refs["way_roles"])
            out_hub = out["m"] if cov["metric"] == "distance" else out["s"]
            if corridor.status == "local" and out_hub < cov["hub"]:
                rec["reasons"].append("asymmetric_hub_access")
            rec["reasons"] += corridor.reasons
    rec["corridor"] = None if corridor is None else {
        "status": corridor.status, "family_key": list(corridor.family_key) if corridor.family_key else None,
        "refs": list(corridor.refs), "direction": corridor.direction, "direction_method": corridor.direction_method,
        "bearing": corridor.bearing, "dwell_s": corridor.dwell_s, "tied": corridor.tied,
        "directed_ways": [list(d) for d in corridor.directed_ways]}
    if far:
        rec["status"] = "unknown"  # shadow result kept above; never classified, not even as outside
        rec["reasons"].append("snap_far")
    elif band is None:
        rec["status"] = "outside_coverage"
        rec["reasons"].append("outside_limit")
    elif band > 0 and (corridor is None or corridor.status == "review_required"):
        rec["status"] = "centroid_sampled"
        rec["reasons"].append("corridor_review_required")
    else:
        rec["status"] = "centroid_sampled"
    rec["calls"] = _W["calls"]
    return rec
