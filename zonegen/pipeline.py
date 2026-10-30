"""Run orchestration: candidate grid, resumable parallel evaluation, post-run grouping (spec §6.2-§6.8)."""
import hashlib
import itertools
import json
import math
import threading
import time
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

import h3
import yaml
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

from . import classify, refs as refs_mod, router
from .classify import FAMILY_KEY_VERSION, Corridor, bearing_deg, haversine_m, validate_families
from .refs import load_ref_index

MI, MAX_CALLS_PER_PROBE = 1609.344, 5
FORK_MIN_BRANCH_CELLS = 10  # spec §6.7: at least 10 supported probes per branch before a fork is even recorded
HIGHWAY_RANK = {"I": 0, "US": 1, "CA": 2}
RESERVED_CODES = {"CA", "US"}  # a zone like 1CA would read as California or a US route


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text())
    c, tv = cfg["coverage"], cfg["time_view"]
    if c["metric"] == "distance":
        cfg["coverage_m"] = {"metric": "distance", "limit": c["limit_miles"] * MI, "hub": c["hub_miles"] * MI,
                             "step": c["band_step_miles"] * MI}
    else:
        cfg["coverage_m"] = {"metric": "time", "limit": c["limit_minutes"] * 60, "hub": c["hub_minutes"] * 60,
                             "step": c["band_step_minutes"] * 60}
    cfg["time_view_s"] = {"limit": tv["limit_minutes"] * 60, "hub": tv["hub_minutes"] * 60,
                          "step": tv["band_step_minutes"] * 60}
    return cfg


def code_version() -> str:
    """Hash of the code that produces ledger records, so a code change never resumes stale results."""
    src = b"".join(Path(m.__file__).read_bytes() for m in (router, classify, refs_mod))
    return hashlib.sha256(src).hexdigest()[:10]


def run_id(cfg: dict, snapshot: dict) -> str:
    pinned = {k: v for k, v in cfg.items() if k != "workers"}  # parallelism must not change results
    h = hashlib.sha256(json.dumps([pinned, snapshot, FAMILY_KEY_VERSION, code_version()],
                                  sort_keys=True).encode()).hexdigest()
    return f"{cfg['label']}-{h[:10]}"


def route_cache_path(cfg: dict, snapshot: dict) -> Path:
    """Cell measurements depend on the base, snap and routing rules, never on Hub/band/limit sizes."""
    pinned = [cfg["base"], cfg["snap"], cfg["routing"], cfg["grid"]["resolution"], cfg["backbone_classes"],
              snapshot, FAMILY_KEY_VERSION, code_version()]
    return Path("data/route_cache") / (hashlib.sha256(json.dumps(pinned, sort_keys=True).encode()).hexdigest()[:16]
                                       + ".jsonl")


def letters_path(cfg: dict) -> Path:
    """Letters given out so far at this base for this highway choice: a corridor keeps its letter across runs."""
    # rounded to ~10 m: the same dealer pasted a little differently must not restart its letters
    pinned = [round(cfg["base"]["lat"], 4), round(cfg["base"]["lon"], 4), cfg.get("highway_types")]
    return Path("data/letters") / (hashlib.sha256(json.dumps(pinned).encode()).hexdigest()[:16] + ".json")


def _read_jsonl(path: Path) -> dict:
    recs = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # a line cut off by a crash: that probe is simply routed again
            recs[rec["id"]] = rec
    return recs


def load_boundary(path: str | None):
    """Geofabrik .poly extract boundary -> prepared polygon (None if not configured). Holes ('!') are skipped."""
    if not path:
        return None
    polys, ring, hole = [], None, False
    lines = Path(path).read_text().splitlines()[1:]  # first line is the file name
    for line in lines:
        t = line.split()
        if not t:
            continue
        if t[0] == "END":
            if ring is not None and not hole and len(ring) >= 3:
                polys.append(Polygon(ring))
            ring = None
        elif ring is None:
            ring, hole = [], t[0].startswith("!")
        else:
            ring.append((float(t[0]), float(t[1])))
    return prep(unary_union(polys))


def in_boundary(boundary, lat: float, lon: float) -> bool:
    return boundary is None or boundary.contains(Point(lon, lat))


def candidate_cells(cfg: dict) -> list[str]:
    """H3 cells whose centers fall inside the pinned extent circle, nearest first (deterministic)."""
    b, g = cfg["base"], cfg["grid"]
    # a degree-space ellipse matching the radius in km at this latitude
    r_lat = g["extent_radius_km"] / 111.32
    r_lon = r_lat / math.cos(math.radians(b["lat"]))
    ring = Point(0, 0).buffer(1, 128).exterior.coords
    shell = [(b["lat"] + y * r_lat, b["lon"] + x * r_lon) for x, y in ring]
    cells = h3.polygon_to_cells(h3.LatLngPoly(shell), g["resolution"])
    return sorted(cells, key=lambda c: (h3.grid_distance(h3.latlng_to_cell(b["lat"], b["lon"], g["resolution"]), c), c))


def run(cfg_path: Path, fresh: bool = False, max_probes: int | None = None) -> Path:
    cfg = load_config(cfg_path)
    snapshot = json.loads(Path(cfg["data"]["snapshot"]).read_text())
    if snapshot.get("pbf") != Path(cfg["data"]["pbf"]).name:
        raise SystemExit(f"Tiles were built from {snapshot.get('pbf')} but the config pins "
                         f"{Path(cfg['data']['pbf']).name}. Run: python -m zonegen build-tiles {cfg_path}")
    boundary = load_boundary(cfg["data"].get("boundary"))
    if not in_boundary(boundary, cfg["base"]["lat"], cfg["base"]["lon"]):
        raise SystemExit("The base is outside the loaded map data.")
    rid = run_id(cfg, snapshot)
    out = Path("runs") / rid
    out.mkdir(parents=True, exist_ok=True)
    ledger = out / "probes.jsonl"
    if fresh and ledger.exists():
        ledger.unlink()

    refs = load_ref_index(Path(cfg["data"]["pbf"]), Path(cfg["data"]["refs_cache"]))
    router.init_worker(cfg, refs)
    base_snap = router.snap(cfg["base"]["lat"], cfg["base"]["lon"])

    cells = candidate_cells(cfg)
    probes = [{"id": c, "kind": "cell", "lat": round(h3.cell_to_latlng(c)[0], 7),
               "lon": round(h3.cell_to_latlng(c)[1], 7)} for c in cells]
    hard = yaml.safe_load(Path(cfg["hard_cases"]).read_text()) if cfg.get("hard_cases") else []
    probes += [{"id": f"hc:{h['id']}", "kind": "hard_case", "lat": h["lat"], "lon": h["lon"]} for h in hard]
    if max_probes:
        probes = probes[:max_probes] + [p for p in probes if p["kind"] == "hard_case"][: max_probes // 10]

    done = _read_jsonl(ledger)
    cache_path = route_cache_path(cfg, snapshot)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = _read_jsonl(cache_path)
    reused = 0
    with ledger.open("a") as f:
        for p in probes:
            raw = cache.get(p["id"])
            if p["kind"] == "cell" and p["id"] not in done and raw and router.reusable(raw, cfg["coverage_m"]):
                rec = {**router.decide(p, raw), "calls": 0}  # already routed for this base: labelling only
                done[p["id"]] = rec
                f.write(json.dumps(rec) + "\n")
                reused += 1
    spent = {"calls": sum(r.get("calls", 0) for r in done.values()), "inflight": 0}
    # no graph data there: distinct from "no road", never routed (spec §6.1); not written to the ledger
    for p in probes:
        if p["id"] not in done and not in_boundary(boundary, p["lat"], p["lon"]):
            done[p["id"]] = {**p, "status": "unknown", "reasons": ["data_unavailable"], "calls": 0}
    lock = threading.Lock()  # the pool's feeder thread runs todo() while the main thread counts results

    def todo():
        for p in probes:
            if p["id"] in done:
                continue
            with lock:
                if spent["calls"] + spent["inflight"] * MAX_CALLS_PER_PROBE >= cfg["request_budget"]:
                    return
                spent["inflight"] += 1
            yield p

    t0 = time.time()
    with (Pool(cfg["workers"], initializer=router.init_worker, initargs=(cfg,)) as pool, ledger.open("a") as f,
          cache_path.open("a") as cf):
        for i, (raw, rec) in enumerate(pool.imap_unordered(router.measure_and_decide, todo(), chunksize=16), 1):
            with lock:
                spent["inflight"] -= 1
                spent["calls"] += rec["calls"]
            done[rec["id"]] = rec
            f.write(json.dumps(rec) + "\n")
            if rec["kind"] == "cell":
                cf.write(json.dumps({"id": rec["id"], **raw}) + "\n")
            if i % 1000 == 0:
                print(f"{len(done)}/{len(probes)} probes, {spent['calls']} calls, {time.time() - t0:.0f}s", flush=True)

    meta = {"run_id": rid, "config": str(cfg_path), "snapshot": snapshot, "family_key_version": FAMILY_KEY_VERSION,
            "valhalla": "pyvalhalla " + __import__("valhalla").__version__, "base_snap": base_snap,
            "coverage": cfg["coverage"], "time_view": cfg["time_view"], "code_version": code_version(),
            "highway_types": cfg.get("highway_types"), "min_corridor_cells": cfg.get("min_corridor_cells", 0),
            "candidate_cells": len(cells), "probes_total": len(probes), "calls": spent["calls"],
            "reused_from_route_cache": reused, "route_cache": str(cache_path),
            "elapsed_s_this_session": round(time.time() - t0, 1), "refs_counts": refs["counts"]}
    registry_path = letters_path(cfg)
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else {}
    cells_out, hard_out = postprocess(cfg, [p for p in probes if p["kind"] == "cell"], done, hard, registry)
    if not max_probes:  # a smoke test sees only part of the map and must not hand out letters
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True))
    meta["forks"] = fork_candidates(cells_out)
    from .report import write_outputs
    write_outputs(out, cfg, meta, cells_out, hard_out, hard)
    return out


def merge_small(cells: dict, min_cells: int) -> dict:
    """Corridors under `min_cells` -> a bigger corridor, smallest first. Display grouping only.

    Road logic first: the corridor most of its cells arrive through, if it touches them or nothing else does.
    Otherwise the neighbour it touches most, or the nearest corridor if it touches none.
    """
    fam = {cid: tuple(r["corridor"]["family_key"]) for cid, r in cells.items()}
    prev = {cid: tuple(r["corridor"].get("prev_family") or ()) for cid, r in cells.items()}
    size, merged = Counter(fam.values()), {}

    def target(f: tuple) -> tuple | None:
        members = [cid for cid, g in fam.items() if g == f]
        via = Counter(merged.get(prev[c], prev[c]) for c in members)
        via = {k: n for k, n in via.items() if k in size and k != f}
        top = min(via, key=lambda k: (-via[k], k), default=None)
        touch = Counter(fam[n] for cid in members for n in h3.grid_ring(cid, 1) if n in fam and fam[n] != f)
        if top and via[top] * 2 > len(members) and (top in touch or not touch):  # never split a zone across a gap
            return top
        if touch:
            return min(touch, key=lambda t: (-touch[t], -size[t], t))
        others = [cid for cid, g in fam.items() if g != f]
        points = [(cells[c]["lat"], cells[c]["lon"]) for c in members]
        near = min(others, key=lambda o: (min(haversine_m((cells[o]["lat"], cells[o]["lon"]), p) for p in points), o),
                   default=None)
        return fam[near] if near else None

    while small := sorted((f for f, n in size.items() if n < min_cells), key=lambda f: (size[f], f)):
        f, t = small[0], target(small[0])
        if t is None:  # the last corridor left has nothing to join
            return merged
        fam = {cid: t if g == f else g for cid, g in fam.items()}
        size[t] += size.pop(f)
        merged = {k: t if v == f else v for k, v in merged.items()} | {f: t}
    return merged


def _rank(fk: tuple) -> int:
    return HIGHWAY_RANK.get(fk[0].split()[0], len(HIGHWAY_RANK))


def branch_parents(cells: dict, merged: dict) -> dict:
    """Corridor -> the main corridor it branches off: over half its cells arrive via a bigger corridor.

    A branch can't outrank its parent: an Interstate reached through a US route is still a main corridor.
    """
    size, via = Counter(), defaultdict(Counter)
    for r in cells.values():
        c = r["corridor"]
        fk, prev = tuple(c["family_key"]), tuple(c.get("prev_family") or ())
        fk = merged.get(fk, fk)
        size[fk] += 1
        if prev and merged.get(prev, prev) != fk:
            via[fk][merged.get(prev, prev)] += 1
    parent = {}
    for fk, counts in via.items():
        top, n = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if n * 2 > size[fk] and (size[top], top) > (size[fk], fk) and _rank(top) <= _rank(fk):  # bigger: no cycles
            parent[fk] = top
    def root(fk):
        return root(parent[fk]) if fk in parent else fk
    return {fk: root(fk) for fk in parent}


def _family_letters(cfg: dict, recs: list[dict], merged: dict | None = None, parents: dict | None = None,
                    registry: dict | None = None) -> dict:
    """Clockwise display letters by circular-mean bearing of member cells from the base. Display only.

    Main corridors get their own letters; a branch gets its main corridor's letter plus one (2A -> 2AB).
    Main corridors past Z become A2, B2, so they can't be mistaken for branches.
    `registry` (family text -> letters) wins, so a corridor seen before keeps its letters.
    """
    merged, parents, registry = merged or {}, parents or {}, {} if registry is None else registry
    b = (cfg["base"]["lat"], cfg["base"]["lon"])
    vecs = defaultdict(lambda: [0.0, 0.0])
    for r in recs:
        fk = tuple(r["corridor"]["family_key"])
        fk = merged.get(fk, fk)
        br = math.radians(bearing_deg(b, (r["lat"], r["lon"])))
        vecs[fk][0] += math.sin(br)
        vecs[fk][1] += math.cos(br)
    order = sorted(vecs, key=lambda k: (k in parents, math.degrees(math.atan2(*vecs[k])) % 360, k))
    alphabet = "ABCDEFGHIJKMNOPQRSTUVWXYZ"  # no "L": reserved for local-road zones
    used, letters = set(registry.values()) | RESERVED_CODES, {}
    for fk in order:
        text = " | ".join(fk)
        prefix = letters[parents[fk]] if fk in parents else ""
        extra = (f"{a}{k}" for k in itertools.count(2) for a in alphabet)  # A2, B2, ... then A3, B3, ...
        labels = itertools.chain(alphabet, map("".join, itertools.product(alphabet, repeat=2)) if prefix else extra)
        code = registry.get(text) or next(prefix + s for s in labels if prefix + s not in used)
        registry[text] = letters[fk] = code
        used.add(code)
    return letters | {fk: letters[t] for fk, t in merged.items()}


def _zone(rec: dict, letters: dict) -> tuple[str | None, str | None]:
    """(zone_code, display corridor id) for a classified probe."""
    if rec.get("status") not in ("centroid_sampled", "mixed") or rec.get("band") is None:
        return None, None
    if rec["band"] == 0:
        return "0", "HUB"
    c = rec.get("corridor")
    if not c or c["status"] == "review_required":
        return None, None
    if c["status"] == "local":
        return f"{rec['band']}L", "L"
    letter = letters.get(tuple(c["family_key"]))
    return (f"{rec['band']}{letter}", letter) if letter else (None, None)


def fork_candidates(cells: dict) -> list[dict]:
    """Record (never promote) families whose trips leave the backbone onto 2+ different branches (spec §6.7).

    A branch is the longest-dwell highway after the backbone, or "stays local". The cross-branch travel test
    needs extra routing and is left for M2, so every record says so.
    """
    branches: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    for r in cells.values():
        c = r.get("corridor") or {}
        if r["status"] == "centroid_sampled" and c.get("status") == "supported":
            branches[tuple(c["family_key"])][" ; ".join(c.get("next_refs") or []) or "stays local"] += 1
    forks = []
    for fam, b in sorted(branches.items()):
        big = {k: n for k, n in sorted(b.items(), key=lambda kv: -kv[1]) if n >= FORK_MIN_BRANCH_CELLS}
        if len(big) >= 2:
            forks.append({"family": " | ".join(fam), "branches": big, "cross_branch_test": "not evaluated (M2)"})
    return forks


def postprocess(cfg: dict, cell_probes: list[dict], done: dict, hard: list[dict], registry: dict | None = None):
    res = cfg["grid"]["resolution"]
    cells = {}
    for p in cell_probes:
        cells[p["id"]] = done.get(p["id"]) or {**p, "status": "unknown", "reasons": ["not_evaluated_budget"]}

    # step 7: directed-edge validation among supported members of each family
    supported = {cid: r for cid, r in cells.items()
                 if r["status"] == "centroid_sampled" and (r.get("corridor") or {}).get("status") == "supported"}
    flags = validate_families({cid: Corridor("supported", tuple(r["corridor"]["family_key"]),
                                             directed_ways=[tuple(d) for d in r["corridor"]["directed_ways"]])
                               for cid, r in supported.items()})
    for cid, f in flags.items():
        cells[cid]["reasons"] += f

    merged = merge_small(supported, cfg.get("min_corridor_cells", 0))
    letters = _family_letters(cfg, list(supported.values()), merged, branch_parents(supported, merged), registry)
    for r in cells.values():
        r["zone_code"], r["display_corridor_id"] = _zone(r, letters)
        into = merged.get(tuple((r.get("corridor") or {}).get("family_key") or ()))
        r["merged_into"] = " | ".join(into) if into else None
        r["candidate_zones"] = [r["zone_code"]] if r["zone_code"] else []

    # hard cases: same classifier; a conflicting reviewed point makes its cell mixed (spec §6.3)
    hard_out = []
    for h in hard:
        rec = done.get(f"hc:{h['id']}")
        if rec is None:
            hard_out.append({"id": h["id"], "status": "not_evaluated"})
            continue
        rec = dict(rec)
        rec["zone_code"], _ = _zone(rec, letters)
        rec["cell"] = h3.latlng_to_cell(h["lat"], h["lon"], res)
        cell = cells.get(rec["cell"])
        if cell and cell["status"] == "centroid_sampled" and rec["zone_code"] and cell["zone_code"] \
                and rec["zone_code"] != cell["zone_code"]:
            cell["status"] = "mixed"
            cell["candidate_zones"] = sorted({cell["zone_code"], rec["zone_code"]})
            cell["reasons"].append(f"mixed_by:{h['id']}")
        hard_out.append(rec)

    # extent check: a covered cell touching the enumeration boundary needs review (expected: none)
    for cid, r in cells.items():
        if r.get("band") is not None and any(n not in cells for n in h3.grid_disk(cid, 1)):
            r["reasons"].append("extent_review_required")

    # display-only fallback: nearest supported corridor by H3 grid distance, ties by corridor id
    frontier = {cid for cid, r in cells.items() if r["status"] == "centroid_sampled" and r["display_corridor_id"]}
    display = {cid: cells[cid]["display_corridor_id"] for cid in frontier}
    for cid, r in cells.items():
        if r["status"] == "mixed":
            display[cid] = r["display_corridor_id"]
    seen = set(display)
    while frontier:
        nxt = defaultdict(set)
        for cid in frontier:
            for n in h3.grid_ring(cid, 1):
                if n in cells and n not in seen:
                    nxt[n].add(display[cid])
        for n, ids in nxt.items():
            display[n] = min(ids)
        seen |= set(nxt)
        frontier = set(nxt)
    for cid, r in cells.items():
        hatched = r["status"] in ("unknown", "mixed") or (r["status"] == "centroid_sampled" and not r["zone_code"])
        r["hatch_status"] = "hatched" if hatched else "none"
        r["display_corridor_id"] = display.get(cid) if hatched or r["zone_code"] else None
        r["display_basis"] = "nearest_supported_corridor" if hatched and r["display_corridor_id"] else None
        r["verification_required"] = r["status"] == "mixed" or None
    return cells, hard_out
