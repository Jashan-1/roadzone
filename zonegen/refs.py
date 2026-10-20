"""way_id -> normalized highway refs, from route relations in the same pinned PBF (spec §4, §6.5.1 step 3)."""
import hashlib
import json
from pathlib import Path

import osmium

from .classify import normalize_ref

NETWORK_PREFIX = {"US:I": "I", "US:US": "US", "US:CA": "CA"}


def build_ref_index(pbf: Path) -> dict:
    """Relation refs (with member role as signed direction) win; a way's own `ref` tag is the fallback."""
    rel_refs: dict[int, set] = {}
    roles: dict[int, dict] = {}
    tag_refs: dict[int, list] = {}
    fp = osmium.FileProcessor(str(pbf), osmium.osm.WAY | osmium.osm.RELATION).with_filter(osmium.filter.KeyFilter("ref"))
    for obj in fp:
        if obj.is_relation():
            prefix = NETWORK_PREFIX.get(obj.tags.get("network", ""))
            if obj.tags.get("type") != "route" or obj.tags.get("route") != "road" or not prefix:
                continue
            ref = normalize_ref(f"{prefix} {obj.tags['ref']}")
            rel_direction = obj.tags.get("direction", "")  # one relation per direction is common in CA
            for m in obj.members:
                if m.type == "w":
                    rel_refs.setdefault(m.ref, set()).add(ref)
                    role = m.role or rel_direction
                    if role:
                        prev = roles.setdefault(m.ref, {}).get(ref)
                        # a two-way way in both directional relations has no single signed direction
                        roles[m.ref][ref] = role if prev in (None, role) else ""
        elif obj.is_way() and "highway" in obj.tags:
            tag_refs[obj.id] = [normalize_ref(r) for r in obj.tags["ref"].split(";")]
    way_refs = {wid: sorted(refs) for wid, refs in rel_refs.items()}
    for wid, refs in tag_refs.items():
        way_refs.setdefault(wid, refs)
    return {
        "way_refs": way_refs,
        "way_roles": roles,
        "counts": {"relation_ways": len(rel_refs), "tag_only_ways": len(way_refs) - len(rel_refs)},
    }


def load_ref_index(pbf: Path, cache: Path) -> dict:
    # the cache is only valid for the code that built it (ref normalization lives in classify.py)
    src = b"".join(Path(__file__).with_name(f).read_bytes() for f in ("refs.py", "classify.py"))
    cache = cache.with_name(f"{cache.stem}-{hashlib.sha256(src).hexdigest()[:8]}{cache.suffix}")
    if not cache.exists():
        cache.write_text(json.dumps(build_ref_index(pbf)))
    raw = json.loads(cache.read_text())
    return {
        "way_refs": {int(k): v for k, v in raw["way_refs"].items()},
        "way_roles": {int(k): v for k, v in raw["way_roles"].items()},
        "counts": raw["counts"],
    }
