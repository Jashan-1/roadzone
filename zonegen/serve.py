"""Dealer page backend and zone lookup, on one port.

GET  /zone?run=<run id>&q=<'lat, lon' or street address>   one address -> zone
GET  /api/locations                                         newest run per shop name
GET  /api/zones?run=<run id>                                zone outlines for the map
GET  /api/jobs, POST /api/runs                              admin: make zones (needs ROADZONE_ADMIN_PASSWORD)
anything else                                               the built page in web/dist

shortcut: no login on the dealer endpoints and localhost only, add auth before exposing it beyond this machine.
Served one request at a time on purpose: the router's worker state is per process, not per thread.
Zone-making jobs run as subprocesses, so they never touch this process's router.
"""
import hmac
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import h3
import yaml

from . import lookup
from .pipeline import in_boundary, load_boundary, load_config, write_custom_config

RUN_ID = re.compile(r"^[\w-]+$")  # no dots or slashes: the id becomes a path under runs/
MAX_QUERY = 300
MAX_BODY = 4096
TEMPLATE = Path("configs/stevens_creek.yaml")
WEB = Path(__file__).resolve().parent.parent / "web" / "dist"
HIGHWAYS = ("I", "US", "CA")
DEFAULT_COVERAGE = {"limit_miles": 50.0, "hub_miles": 5.0, "band_step_miles": 10.0}
JOBS: dict[str, dict] = {}  # shortcut: in memory, lost on restart; move to disk if admins need history


def _known(rid: str) -> bool:
    return bool(RUN_ID.match(rid)) and (Path("runs") / rid / "cells.geojson").exists()


@lru_cache(maxsize=32)
def _run(rid: str) -> tuple[str, dict]:
    d = Path("runs") / rid
    cells = [f["properties"] for f in json.loads((d / "cells.geojson").read_text())["features"] if f["id"] != "base"]
    return json.loads((d / "run_meta.json").read_text())["config"], lookup.zone_letters(cells)


def zone_for(rid: str, q: str) -> tuple[int, dict]:
    """(HTTP status, JSON body) for one lookup."""
    if not _known(rid):
        return 404, {"error": "unknown run"}
    if not q.strip() or len(q) > MAX_QUERY:
        return 400, {"error": f"q must be 'lat, lon' or an address under {MAX_QUERY} characters"}
    point = lookup.resolve(q)
    if point is None:
        return 422, {"error": "could not find that location"}
    if point["source"] != "coordinates":
        time.sleep(1)  # Nominatim's public usage policy: at most 1 request per second
    try:
        cfg_path, letters = _run(rid)
        result = lookup.classify(cfg_path, point["lat"], point["lon"], letters)
    except Exception as e:  # routing data missing or a broken run: report it, keep serving
        return 500, {"error": f"lookup failed: {e}"}
    return 200, {**result, "lat": point["lat"], "lon": point["lon"], "source": point["source"],
                 "label": point.get("label", q.strip())}


def _coverage(d: Path) -> dict:
    """Coverage frozen into the run; older runs fall back to their config file."""
    try:
        meta = json.loads((d / "run_meta.json").read_text())
        if "coverage" not in meta:
            meta = yaml.safe_load(Path(meta["config"]).read_text())
        return {k: float(meta["coverage"][k]) for k in DEFAULT_COVERAGE}
    except (OSError, KeyError, ValueError, TypeError):
        return dict(DEFAULT_COVERAGE)


def locations() -> tuple[int, list]:
    """One entry per shop name, newest run wins, in the order the shops were first made."""
    runs = sorted((p for p in Path("runs").glob("*") if (p / "cells.geojson").exists()),
                  key=lambda p: p.stat().st_mtime)
    shops: dict[str, dict] = {}
    for p in runs:
        name = (p / "name.txt").read_text().strip() if (p / "name.txt").exists() else p.name
        shops[name] = {"run": p.name, "name": name, **_coverage(p)}
    return 200, list(shops.values())


@lru_cache(maxsize=8)
def _zones(rid: str) -> str:
    fc = json.loads((Path("runs") / rid / "cells.geojson").read_text())
    base = next(f for f in fc["features"] if f["id"] == "base")["geometry"]["coordinates"]
    cells = [f["properties"] for f in fc["features"] if f["id"] != "base"]
    feats = []
    for code, members in lookup.solid_zones(cells).items():
        band = re.match(r"\d+", code)
        feats.append({"type": "Feature", "geometry": h3.cells_to_geo(members),
                      "properties": {"zone": code, "band": int(band.group()) if band else None}})
    return json.dumps({"type": "FeatureCollection", "features": feats, "base": base,
                       "coverage": _coverage(Path("runs") / rid)})


def zones(rid: str) -> tuple[int, dict | str]:
    if not _known(rid):
        return 404, {"error": "unknown run"}
    return 200, _zones(rid)


@lru_cache(maxsize=1)
def _boundary():
    return load_boundary(load_config(TEMPLATE)["data"].get("boundary"))


def _admin_ok(auth: str) -> tuple[int, dict] | None:
    """None when the caller is an admin, else the error response."""
    pw = os.environ.get("ROADZONE_ADMIN_PASSWORD")
    if not pw:
        return 403, {"error": "Admin is turned off. Set ROADZONE_ADMIN_PASSWORD on the server."}
    if not hmac.compare_digest(auth.encode(), f"Bearer {pw}".encode()):
        return 401, {"error": "Wrong admin password."}
    return None


def _number(body: dict, key: str, lo: float, hi: float) -> float:
    v = float(body[key])
    if not lo <= v <= hi:
        raise ValueError(f"{key} must be between {lo:g} and {hi:g}")
    return v


def _job(jid: str, path: Path, name: str):
    proc = subprocess.run([sys.executable, "-m", "zonegen", "run", str(path)], capture_output=True, text=True)
    if proc.returncode:
        JOBS[jid].update(state="failed", error=proc.stderr[-800:] or "zone making failed")
        return
    rid = Path(proc.stdout.strip().splitlines()[-1]).name
    if name:
        (Path("runs") / rid / "name.txt").write_text(name)
    JOBS[jid].update(state="done", run=rid)


def start_run(body: dict, auth: str) -> tuple[int, dict]:
    if err := _admin_ok(auth):
        return err
    if any(j["state"] == "running" for j in JOBS.values()):
        return 409, {"error": "Zones are already being made. Wait for that to finish."}
    try:
        name = str(body.get("name", "")).strip()[:80]
        point = lookup.parse_coordinates(str(body.get("where", "")))
        if point is None:
            raise ValueError("Shop location must be 'latitude, longitude', e.g. 37.32305, -121.97000")
        limit, hub = _number(body, "limit_miles", 5, 80), _number(body, "hub_miles", 1, 40)
        step, merge = _number(body, "band_step_miles", 1, 50), int(_number(body, "min_corridor_cells", 0, 200))
        highways = [h for h in HIGHWAYS if h in (body.get("highways") or [])]
    except (KeyError, TypeError, ValueError) as e:
        return 400, {"error": str(e)}
    if not highways:
        return 400, {"error": "Pick at least one highway type."}
    if hub >= limit:
        return 400, {"error": "The Hub must be smaller than the furthest distance."}
    cfg = yaml.safe_load(TEMPLATE.read_text())
    if not (Path("data/valhalla_tiles").exists() and Path(load_config(TEMPLATE)["data"]["snapshot"]).exists()):
        return 503, {"error": "Map data is still downloading or building. Try again when it finishes."}
    if not in_boundary(_boundary(), *point):
        return 400, {"error": f"{point[0]:.5f}, {point[1]:.5f} is outside the loaded map data (California)."}
    cfg.update(label="custom", hard_cases=None, highway_types=highways, min_corridor_cells=merge)
    cfg["base"] = {"lat": point[0], "lon": point[1], "confirmed": False}
    cfg["coverage"].update(limit_miles=limit, hub_miles=hub, band_step_miles=step)
    path = write_custom_config(cfg)
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"job": jid, "name": name or f"{point[0]:.4f}, {point[1]:.4f}", "state": "running",
                 "started": time.time()}
    threading.Thread(target=_job, args=(jid, path, name), daemon=True).start()
    return 202, JOBS[jid]


def jobs(auth: str) -> tuple[int, dict | list]:
    if err := _admin_ok(auth):
        return err
    return 200, sorted(JOBS.values(), key=lambda j: -j["started"])


def static(path: str) -> tuple[int, bytes, str]:
    """A file from web/dist; unknown paths get index.html so the page owns its own routes."""
    index = WEB / "index.html"
    if not index.exists():
        return 404, b"Frontend not built. Run: cd web && npm install && npm run build", "text/plain"
    f = (WEB / path.lstrip("/")).resolve()
    if not f.is_relative_to(WEB.resolve()) or not f.is_file():
        f = index
    return 200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body, ctype: str = "application/json"):
        data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        args = {k: v[0] for k, v in parse_qs(url.query).items()}
        auth = self.headers.get("Authorization", "")
        routes = {"/zone": lambda: zone_for(args.get("run", ""), args.get("q", "")),
                  "/api/locations": locations,
                  "/api/zones": lambda: zones(args.get("run", "")),
                  "/api/jobs": lambda: jobs(auth)}
        if url.path in routes:
            self._send(*routes[url.path]())
        elif url.path.startswith("/api/"):
            self._send(404, {"error": "not found"})
        else:
            self._send(*static(url.path))

    def do_POST(self):
        if urlparse(self.path).path != "/api/runs":
            return self._send(404, {"error": "not found"})
        size = int(self.headers.get("Content-Length") or 0)
        if not 0 < size <= MAX_BODY:
            return self._send(400, {"error": "bad request body"})
        try:
            body = json.loads(self.rfile.read(size))
        except ValueError:
            return self._send(400, {"error": "body must be JSON"})
        if not isinstance(body, dict):
            return self._send(400, {"error": "body must be a JSON object"})
        self._send(*start_run(body, self.headers.get("Authorization", "")))


def serve(port: int):
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
