"""Bands and the v1 longest-dwell corridor classifier (spec v0.2 §5, §6.5.1)."""
import math
import re
from collections import Counter
from dataclasses import dataclass, field

FAMILY_KEY_VERSION = "fk-v1.0"
LOCAL = "local"
QUADRANTS = ("N", "E", "S", "W")  # half-open: N [315,45), E [45,135), S [135,225), W [225,315)
MIN_DISPLACEMENT_M = 500  # below this, a bearing-derived direction is negligible
EDGE_MIN_SHARERS = 3  # a directed way counts as shared when this many family members use it (self + 2 others)
EDGE_MIN_SHARE = 0.5  # a member is edge-confirmed when at least this share of its backbone ways is shared


@dataclass
class Segment:
    """One traversed edge of an outbound path, with cumulative offsets from the base."""
    way_id: int
    start_m: float
    end_m: float
    start_s: float
    end_s: float
    road_class: str
    use: str
    start_pt: tuple[float, float]  # (lat, lon)
    end_pt: tuple[float, float]
    heading: int = 0


@dataclass
class Corridor:
    status: str  # supported | local | review_required
    family_key: tuple | None
    refs: tuple[str, ...] = ()
    direction: str | None = None
    direction_method: str | None = None
    bearing: float | None = None
    dwell_s: float = 0.0
    tied: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    directed_ways: list = field(default_factory=list)
    next_refs: tuple = ()  # longest-dwell highway after the backbone: the branch a fork diagnostic groups by


# --- bands -----------------------------------------------------------------

def band_edges(hub: float, step: float, limit: float) -> list[float]:
    """Lower edge of bands 1..n; band 0 (Hub) is [0, hub). Shared with the viewer legend."""
    return [hub + k * step for k in range(math.ceil((limit - hub) / step))]


def band_index(m: float, hub: float, step: float, limit: float) -> int | None:
    """0 = Hub [0, hub); then half-open bands of `step`; the last one includes `limit`. None = outside."""
    if m > limit:
        return None
    return sum(1 for edge in band_edges(hub, step, limit) if m >= edge)


# --- refs --------------------------------------------------------------------

_REF_RE = re.compile(r"^(I|US|CA|SR)[\s\-]*(\d+[A-Z]?)(?:\s+(BUS|BYP|ALT))?$")


def normalize_ref(raw: str) -> str:
    """'I-280', 'I280', 'i 280' -> 'I 280'; 'SR 17' -> 'CA 17'. Unknown forms are kept, trimmed."""
    s = " ".join(raw.strip().upper().split())
    m = _REF_RE.match(s)
    if not m:
        return s
    sys_, num, suffix = m.groups()
    return " ".join(p for p in ("CA" if sys_ == "SR" else sys_, num, suffix) if p)


def _ref_sort_key(ref: str):
    order = {"I": 0, "US": 1, "CA": 2}
    sys_, _, num = ref.partition(" ")
    digits = re.match(r"\d+", num)
    return (order.get(sys_, 3), int(digits.group()) if digits else 0, ref)


def ref_set(refs) -> tuple[str, ...]:
    return tuple(sorted({normalize_ref(r) for r in refs if r.strip()}, key=_ref_sort_key))


# --- direction ----------------------------------------------------------------

def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return math.degrees(math.atan2(y, x)) % 360


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def quadrant(b: float) -> str:
    return QUADRANTS[int(((b + 45) % 360) // 90)]


# --- classifier -----------------------------------------------------------------

def is_backbone(seg: Segment, eligible_classes: set[str]) -> bool:
    return seg.road_class in eligible_classes and seg.use not in ("ramp", "turn_channel")


def classify_corridor(segments: list[Segment], hub_limit: float, metric: str,
                      eligible_classes: set[str], way_refs: dict, way_roles: dict) -> Corridor:
    """Steps 1-6 of §6.5.1. `way_refs[way_id]` -> raw refs; `way_roles[way_id]` -> {ref: role}."""
    # 1. Hub clip on the configured metric; a crossing segment contributes its post-Hub share.
    post = []
    for seg in segments:
        a, b = (seg.start_m, seg.end_m) if metric == "distance" else (seg.start_s, seg.end_s)
        if b <= hub_limit:
            continue
        frac = 1.0 if a >= hub_limit or b == a else (b - hub_limit) / (b - a)
        post.append((seg, (seg.end_s - seg.start_s) * frac))

    # 2-4. Runs of consecutive eligible segments with the same normalized ref set; dwell in seconds.
    runs, cur = [], None
    for i, (seg, dwell) in enumerate(post):
        eligible = is_backbone(seg, eligible_classes)
        key = ref_set(way_refs.get(seg.way_id, ())) if eligible else None
        if key is not None and cur is not None and cur["refs"] == key and cur["last"] == i - 1:
            cur["segs"].append(seg)
            cur["dwell"] += dwell
            cur["last"] = i
        elif key is not None:
            cur = {"refs": key, "segs": [seg], "dwell": dwell, "first": i, "last": i}
            runs.append(cur)
        else:
            cur = None

    if not runs:
        return Corridor(status=LOCAL, family_key=(LOCAL,))

    # 6. Deterministic tie-break: longest dwell, then ref-set order, then route-segment order.
    runs.sort(key=lambda r: (-r["dwell"], [_ref_sort_key(x) for x in r["refs"]], r["first"]))
    best = runs[0]
    c = Corridor(status="supported", family_key=None, refs=best["refs"], dwell_s=round(best["dwell"], 1),
                 directed_ways=[(s.way_id, quadrant(s.heading)) for s in best["segs"]])
    c.tied = [list(r["refs"]) for r in runs[1:] if abs(r["dwell"] - best["dwell"]) < 1e-6]
    # rejoining the backbone's own highway after a ramp is a continuation, not a branch
    downstream = sorted((r for r in runs if r["first"] > best["last"] and r["refs"] != best["refs"]),
                        key=lambda r: (-r["dwell"], r["first"]))
    c.next_refs = downstream[0]["refs"] if downstream else ()
    if c.tied:
        c.reasons.append("tie")
    if not best["refs"]:
        c.status = "review_required"
        c.reasons.append("ref_missing")

    # 5. Direction: signed relation role of the primary ref, else the run's entry-to-exit bearing.
    if best["refs"]:
        primary = best["refs"][0]
        roles = {way_roles.get(s.way_id, {}).get(primary) for s in best["segs"]} - {None, ""}
        roles = {r[0].upper() for r in roles if r.lower() in ("north", "south", "east", "west")}
        if len(roles) == 1:
            c.direction, c.direction_method = roles.pop(), "relation_role"
        elif len(roles) > 1:
            c.status, c.direction_method = "review_required", "relation_role"
            c.reasons.append("direction_conflict")
    start, end = best["segs"][0].start_pt, best["segs"][-1].end_pt
    c.bearing = round(bearing_deg(start, end), 1)
    if c.direction is None and "direction_conflict" not in c.reasons:
        if haversine_m(start, end) < MIN_DISPLACEMENT_M:
            c.status = "review_required"
            c.reasons.append("direction_negligible")
        else:
            c.direction, c.direction_method = quadrant(c.bearing), "bearing_quadrant"
    c.family_key = (*c.refs, c.direction) if c.status != "review_required" else None
    return c


def validate_families(corridors: dict) -> dict:
    """Step 7: flag members whose backbone mostly runs on ways the rest of the family doesn't use.

    A member is confirmed when at least EDGE_MIN_SHARE of its directed backbone ways are used by at least
    EDGE_MIN_SHARERS family members. `corridors` maps cell id -> Corridor; returns cell id -> added reason codes.
    Lack of overlap is a review flag, never a regroup.
    """
    by_family: dict[tuple, list] = {}
    for cid, c in corridors.items():
        if c.status == "supported":
            by_family.setdefault(c.family_key, []).append(cid)
    flags = {}
    for members in by_family.values():
        counts = Counter(dw for cid in members for dw in set(corridors[cid].directed_ways))
        for cid in members:
            ways = set(corridors[cid].directed_ways)
            if not ways or sum(counts[dw] >= EDGE_MIN_SHARERS for dw in ways) / len(ways) < EDGE_MIN_SHARE:
                flags[cid] = ["edge_unconfirmed"]
    return flags
