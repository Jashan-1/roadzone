"""Zone lookup endpoint: GET /zone?run=<run id>&q=<'lat, lon' or street address>.

shortcut: no login and localhost only, add auth before exposing it beyond this machine.
Served one request at a time on purpose: the router's worker state is per process, not per thread.
"""
import json
import re
import time
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import lookup

RUN_ID = re.compile(r"^[\w-]+$")  # no dots or slashes: the id becomes a path under runs/
MAX_QUERY = 300


@lru_cache(maxsize=32)
def _run(rid: str) -> tuple[str, dict]:
    d = Path("runs") / rid
    cells = [f["properties"] for f in json.loads((d / "cells.geojson").read_text())["features"] if f["id"] != "base"]
    return json.loads((d / "run_meta.json").read_text())["config"], lookup.zone_letters(cells)


def zone_for(rid: str, q: str) -> tuple[int, dict]:
    """(HTTP status, JSON body) for one lookup."""
    if not RUN_ID.match(rid) or not (Path("runs") / rid / "cells.geojson").exists():
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
    return 200, {**result, "lat": point["lat"], "lon": point["lon"], "source": point["source"]}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        args = {k: v[0] for k, v in parse_qs(url.query).items()}
        code, body = zone_for(args.get("run", ""), args.get("q", "")) if url.path == "/zone" else (404, {"error": "not found"})
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(port: int):
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
