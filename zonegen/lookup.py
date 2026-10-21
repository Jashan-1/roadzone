"""Address lookup for the viewer: resolve an input to a point, then classify it with a run's road rules.

Uses the same router.evaluate as the cells (address path: keeps its own driveway/track access). Not the M3 verified
lookup: no geocode-quality gating, no stored results.
"""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from . import router
from .pipeline import load_config
from .refs import load_ref_index

COORDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*$")
NOMINATIM = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=us&q="
MI = 1609.344
_REFS: dict = {}  # refs index per cache file: loading it takes a few seconds


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """'37.32, -121.97' (as copied from Google Maps) -> (lat, lon); anything else -> None."""
    m = COORDS.match(text)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def geocode(text: str) -> dict | None:
    """Free-text address via OpenStreetMap Nominatim (public service: about 1 request/second, sends the text out)."""
    req = urllib.request.Request(NOMINATIM + urllib.parse.quote(text), headers={"User-Agent": "roadzone-poc"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            hits = json.load(r)
    except OSError:
        return None
    if not hits:
        return None
    return {"lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]), "label": hits[0].get("display_name", text),
            "source": f"Nominatim ({hits[0].get('addresstype') or hits[0].get('type', '?')})"}


def resolve(text: str) -> dict | None:
    pt = parse_coordinates(text)
    if pt:
        return {"lat": pt[0], "lon": pt[1], "label": text.strip(), "source": "coordinates"}
    return geocode(text) if text.strip() else None


def zone_letters(cells: list[dict]) -> dict[str, str]:
    """family_key text -> display letter, as lettered in that run's map."""
    return {c["family_key"]: c["zone_code"].lstrip("0123456789") for c in cells
            if c.get("family_key") and c.get("zone_code") and c.get("corridor_status") == "supported"}


def _use_run_config(cfg_path: str) -> dict:
    cfg = load_config(Path(cfg_path))
    key = cfg["data"]["refs_cache"]
    if key not in _REFS:
        _REFS[key] = load_ref_index(Path(cfg["data"]["pbf"]), Path(key))
    if router._W.get("cfg_path") != cfg_path:
        router.init_worker(cfg, _REFS[key])
        router._W["cfg_path"] = cfg_path
    return cfg


def classify(cfg_path: str, lat: float, lon: float, letters: dict[str, str]) -> dict:
    """Zone, distances and review flags for one point under the run whose config is `cfg_path`."""
    _use_run_config(cfg_path)
    rec = router.evaluate({"id": "address", "kind": "address", "lat": lat, "lon": lon})
    return summarize(rec, letters)


def summarize(rec: dict, letters: dict[str, str]) -> dict:
    corridor, band = rec.get("corridor") or {}, rec.get("band")
    zone, review = None, bool(rec.get("review_required"))
    if rec["status"] == "centroid_sampled" and band is not None:
        if band == 0:
            zone = "0"
        elif corridor.get("status") == "local":
            zone = f"{band}L"
        elif corridor.get("status") == "supported":
            letter = letters.get(" | ".join(corridor["family_key"]))
            zone, review = (f"{band}{letter}", review) if letter else (f"{band}?", True)  # corridor not on this map
        else:
            review = True
    return {"status": rec["status"], "zone": zone, "band": band, "review": review,
            "miles": round(rec["m_dist"] / MI, 1) if rec.get("m_dist") else None,
            "minutes": round(rec["m_time"] / 60) if rec.get("m_time") else None,
            "corridor": " | ".join(corridor.get("family_key") or []) or corridor.get("status") or "-",
            "reasons": ", ".join(rec["reasons"]) or "-"}
