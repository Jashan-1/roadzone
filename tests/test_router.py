"""Status precedence in router.evaluate, with Valhalla replaced by canned answers (no tiles needed)."""
import h3
import pytest

from zonegen import router

MI = 1609.344
CFG = {
    "snap": {"decision_cap_m": 100, "shadow_cap_m": 500, "search_filter": {"exclude_ramp": True},
             "track_retry_min_road_class": "residential"},
    "routing": {"costing": "auto", "costing_options": {}},
    "base": {"lat": 37.0, "lon": -122.0},
    "coverage_m": {"metric": "distance", "limit": 50 * MI, "hub": 5 * MI, "step": 10 * MI},
    "time_view_s": {"limit": 3600, "hub": 900, "step": 900},
    "backbone_classes": ["motorway", "trunk", "primary"],
    "grid": {"resolution": 8},
}
_CELL = h3.latlng_to_cell(37.1, -122.1, 8)
PROBE = {"id": _CELL, "kind": "cell", "lat": h3.cell_to_latlng(_CELL)[0], "lon": h3.cell_to_latlng(_CELL)[1]}
IN_CELL, OUT_OF_CELL = 0.0018, 0.0060  # ~200 m (inside the cell) and ~670 m (past any res-8 cell edge)


@pytest.fixture
def fake(monkeypatch):
    """fake(snap_offset_deg, route_miles: float | error_code: int) -> captured requests."""
    def setup(offset, route, use="road", retry_use=None):
        sent = []

        def call(action, req):
            router._W["calls"] = router._W.get("calls", 0) + 1
            sent.append((action, req))
            if action == "locate":
                if retry_use and "min_road_class" in req["locations"][0]["search_filter"]:
                    use_now = retry_use
                else:
                    use_now = use
                return [{"edges": [{"correlated_lat": PROBE["lat"] + offset, "correlated_lon": PROBE["lon"],
                                    "edge": {"classification": {"use": use_now}},
                                    "way_id": 1}]}], None
            if isinstance(route, int):
                return None, route
            return {"trip": {"summary": {"length": route * MI / 1000, "time": route * 60},
                             "legs": [{"shape": ""}]}}, None

        router._W.update(cfg=CFG, refs={"way_refs": {}, "way_roles": {}})
        monkeypatch.setattr(router, "_call", call)
        return sent
    return setup


def test_far_snap_beyond_limit_is_unknown_not_outside(fake):
    fake(OUT_OF_CELL, 60.0)
    rec = router.evaluate(PROBE)
    assert rec["status"] == "unknown" and "snap_far" in rec["reasons"]


def test_far_snap_without_path_is_unknown_not_unreachable(fake):
    fake(OUT_OF_CELL, 442)
    rec = router.evaluate(PROBE)
    assert rec["status"] == "unknown" and "snap_far" in rec["reasons"]


def test_no_path_is_unreachable(fake):
    fake(0.0001, 442)
    assert router.evaluate(PROBE)["status"] == "unreachable"


def test_near_snap_beyond_limit_is_outside(fake):
    fake(0.0001, 60.0)
    assert router.evaluate(PROBE)["status"] == "outside_coverage"


def test_hub_cell_is_sampled(fake):
    fake(0.0001, 2.0)
    rec = router.evaluate(PROBE)
    assert rec["status"] == "centroid_sampled" and rec["band"] == 0


def test_routes_use_the_snap_search_filter(fake):
    sent = fake(0.0001, 2.0)
    router.evaluate(PROBE)
    routes = [req for action, req in sent if action == "route"]
    assert routes and all(loc.get("search_filter") == CFG["snap"]["search_filter"]
                          for req in routes for loc in req["locations"])


def test_far_snap_inside_its_cell_is_accepted(fake):
    fake(IN_CELL, 2.0)
    rec = router.evaluate(PROBE)
    assert rec["status"] == "centroid_sampled" and "snap_in_cell" in rec["reasons"]


def test_far_snap_for_an_address_is_never_accepted(fake):
    fake(IN_CELL, 2.0)
    rec = router.evaluate({**PROBE, "id": "hc:x", "kind": "hard_case"})
    assert rec["status"] == "unknown" and "snap_far" in rec["reasons"]


def test_snap_onto_a_track_is_unknown_and_not_routed(fake):
    sent = fake(0.0001, 2.0, use="track")
    rec = router.evaluate(PROBE)
    assert rec["status"] == "unknown" and "snap_track" in rec["reasons"]
    assert not [a for a, _ in sent if a == "route"]


def test_track_snap_retries_for_a_real_road(fake):
    sent = fake(0.0001, 2.0, use="track", retry_use="road")
    rec = router.evaluate(PROBE)
    assert rec["status"] == "centroid_sampled" and [a for a, _ in sent].count("locate") == 2
    assert "snapped_past_track" in rec["reasons"] and rec["snap"]["skipped_track_dist_m"] is not None


def test_address_on_a_track_is_routed_and_flagged_for_review(fake):
    sent = fake(0.0001, 2.0, use="track", retry_use="road")
    rec = router.evaluate({**PROBE, "id": "hc:x", "kind": "hard_case"})
    assert rec["status"] == "centroid_sampled" and rec["band"] == 0
    assert rec["review_required"] and "access_via_track" in rec["reasons"]
    assert [a for a, _ in sent].count("locate") == 1  # the address keeps its own access, no second look


def _seg(i, cls, refs_way, m0, m1, use="road"):
    return router.Segment(refs_way, m0, m1, m0 / 30, m1 / 30, cls, use, (37 + m0 / 1e5, -122.0), (37 + m1 / 1e5, -122.0), 0)


def test_cached_road_list_gives_the_same_corridor_for_any_hub():
    from zonegen.classify import classify_corridor
    # local streets, freeway A, a ramp, freeway B, local streets again
    segs = [_seg(0, "residential", 9, 0, 3000), _seg(1, "motorway", 1, 3000, 12000),
            _seg(2, "motorway", 1, 12000, 20000), _seg(3, "motorway", 3, 20000, 20400, use="ramp"),
            _seg(4, "secondary", 9, 20400, 21000), _seg(5, "motorway", 2, 21000, 40000),
            _seg(6, "residential", 9, 40000, 41000)]
    refs = {1: ["I 280"], 2: ["US 101"], 3: ["I 280"]}
    eligible = {"motorway", "trunk", "primary"}
    cached = router.expand(router.compact(segs, eligible))
    assert len(cached) < len(segs)
    for hub in (0, 2000, 8000, 15000, 25000, 39000, 45000):
        a = classify_corridor(segs, hub, "distance", eligible, refs, {})
        b = classify_corridor(cached, hub, "distance", eligible, refs, {})
        assert (a.status, a.family_key, a.next_refs, a.directed_ways) == (b.status, b.family_key, b.next_refs,
                                                                           b.directed_ways), hub


def test_cached_measure_relabels_without_routing_and_knows_when_it_cannot(fake):
    sent = fake(0.0001, 20.0)
    raw = router.measure(PROBE)
    n = len(sent)
    small_hub = {**CFG["coverage_m"], "hub": 1 * MI}
    router._W["cfg"] = {**CFG, "coverage_m": small_hub}
    assert router.reusable(raw, small_hub)
    assert router.decide(PROBE, raw)["band"] == 2 and len(sent) == n  # 20 mi with hub 1, step 10: relabelled, no calls
    router._W["cfg"] = CFG
    untraced = {k: v for k, v in raw.items() if k not in ("trace_reasons", "segs")}  # as if past an old 10-mile limit
    assert not router.reusable(untraced, CFG["coverage_m"])  # a 50-mile run must route it again


def test_plain_text_no_path_error_counts_as_no_path(monkeypatch):
    class Actor:
        def route(self, req):
            raise router.valhalla.ValhallaError("No path could be found for input")
    monkeypatch.setitem(router._W, "actor", Actor())
    assert router._call("route", {}) == (None, 442)
