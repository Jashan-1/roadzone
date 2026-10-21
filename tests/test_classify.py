from zonegen.classify import (LOCAL, Corridor, Segment, band_index, classify_corridor, normalize_ref,
                              quadrant, ref_set, validate_families)

MI = 1609.344
HUB, STEP, LIMIT = 5 * MI, 10 * MI, 50 * MI
ELIGIBLE = {"motorway", "trunk", "primary"}


def test_band_edges_half_open():
    assert band_index(0, HUB, STEP, LIMIT) == 0
    assert band_index(HUB - 0.01, HUB, STEP, LIMIT) == 0
    assert band_index(HUB, HUB, STEP, LIMIT) == 1  # exactly on a boundary -> outer band
    assert band_index(HUB + STEP, HUB, STEP, LIMIT) == 2
    assert band_index(HUB + STEP - 0.01, HUB, STEP, LIMIT) == 1
    assert band_index(LIMIT, HUB, STEP, LIMIT) == 5  # final interval includes the limit
    assert band_index(LIMIT + 0.01, HUB, STEP, LIMIT) is None


def test_band_last_interval_when_step_divides_evenly():
    assert band_index(45 * MI, HUB, STEP, 45 * MI) == 4


def test_normalize_ref():
    assert normalize_ref("I-280") == normalize_ref("i280") == "I 280"
    assert normalize_ref("SR 17") == "CA 17"
    assert ref_set(["US 101", "I 280", "CA 85", "I-280"]) == ("I 280", "US 101", "CA 85")


def _seg(way, km0, km1, lat0, lat1, cls="motorway", use="road", lon=-122.0):
    # 1 km per minute so time and distance stay proportional in fixtures
    return Segment(way, km0 * 1000, km1 * 1000, km0 * 60, km1 * 60, cls, use, (lat0, lon), (lat1, lon), heading=0)


REFS = {1: ["I 280"], 2: ["I 280"], 3: ["US 101"], 4: ["US 101"], 5: ["US 101"], 9: []}


def test_local_when_no_post_hub_backbone():
    segs = [_seg(1, 0, 5, 37.0, 37.04), _seg(7, 5, 12, 37.04, 37.1, cls="residential")]
    c = classify_corridor(segs, HUB, "distance", ELIGIBLE, REFS, {})
    assert c.status == LOCAL


def test_hub_clip_and_longest_dwell():
    # I-280 for 0-10 km (only 10 - 8.05 km counts after the Hub), then US-101 for 10-20 km
    segs = [_seg(1, 0, 10, 37.0, 37.09), _seg(3, 10, 15, 37.09, 37.14), _seg(4, 15, 20, 37.14, 37.18)]
    c = classify_corridor(segs, HUB, "distance", ELIGIBLE, REFS, {})
    assert c.refs == ("US 101",) and c.direction == "N" and c.direction_method == "bearing_quadrant"
    assert c.dwell_s == 600.0


def test_ramp_breaks_run_and_relation_role_wins():
    segs = [_seg(3, 9, 12, 37.0, 37.03), _seg(8, 12, 13, 37.03, 37.04, use="ramp"), _seg(4, 13, 20, 37.04, 37.1)]
    roles = {4: {"US 101": "south"}}
    c = classify_corridor(segs, HUB, "distance", ELIGIBLE, REFS, roles)
    assert c.dwell_s == 420.0 and c.direction == "S" and c.direction_method == "relation_role"


def test_missing_ref_and_negligible_displacement_need_review():
    c = classify_corridor([_seg(9, 9, 20, 37.0, 37.1)], HUB, "distance", ELIGIBLE, REFS, {})
    assert c.status == "review_required" and "ref_missing" in c.reasons
    loop = [_seg(3, 9, 20, 37.0, 37.001)]
    c = classify_corridor(loop, HUB, "distance", ELIGIBLE, REFS, {})
    assert c.status == "review_required" and "direction_negligible" in c.reasons


def test_tie_is_deterministic():
    segs = [_seg(1, 10, 15, 37.0, 37.05), _seg(8, 15, 16, 37.05, 37.06, use="ramp"), _seg(3, 16, 21, 37.06, 37.1)]
    c = classify_corridor(segs, HUB, "distance", ELIGIBLE, REFS, {})
    assert c.refs == ("I 280",) and c.tied == [["US 101"]] and "tie" in c.reasons


def test_quadrants_half_open():
    assert [quadrant(b) for b in (0, 44.9, 45, 135, 225, 315, 359)] == ["N", "N", "E", "S", "W", "N", "N"]


def test_edge_validation_needs_most_ways_shared_by_the_family():
    fam = ("I 280", "N")
    core = [(1, "N"), (2, "N")]
    members = {k: Corridor("supported", fam, directed_ways=core) for k in "abc"}
    members["d"] = Corridor("supported", fam, directed_ways=[(1, "N"), (7, "N"), (8, "N")])  # 1/3 shared
    members["e"] = Corridor("supported", fam, directed_ways=[(1, "S")])  # opposite direction
    assert validate_families(members) == {"d": ["edge_unconfirmed"], "e": ["edge_unconfirmed"]}


def test_next_refs_is_the_branch_after_the_backbone():
    segs = [_seg(1, 9, 25, 37.0, 37.15), _seg(8, 25, 26, 37.15, 37.16, use="ramp"), _seg(3, 26, 30, 37.16, 37.2)]
    c = classify_corridor(segs, HUB, "distance", ELIGIBLE, REFS, {})
    assert c.refs == ("I 280",) and c.next_refs == ("US 101",)


def test_rejoining_the_backbone_is_not_a_branch():
    segs = [_seg(1, 9, 25, 37.0, 37.15), _seg(8, 25, 26, 37.15, 37.16, use="ramp"), _seg(2, 26, 30, 37.16, 37.2)]
    c = classify_corridor(segs, HUB, "distance", ELIGIBLE, REFS, {})
    assert c.refs == ("I 280",) and c.next_refs == ()
