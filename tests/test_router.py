"""Status precedence in router.evaluate, with Valhalla replaced by canned answers (no tiles needed)."""
import pytest

from zonegen import router

MI = 1609.344
CFG = {
    "snap": {"decision_cap_m": 100, "shadow_cap_m": 500, "search_filter": {"exclude_ramp": True}},
    "routing": {"costing": "auto", "costing_options": {}},
    "base": {"lat": 37.0, "lon": -122.0},
    "coverage_m": {"metric": "distance", "limit": 50 * MI, "hub": 5 * MI, "step": 10 * MI},
    "time_view_s": {"limit": 3600, "hub": 900, "step": 900},
    "backbone_classes": ["motorway", "trunk", "primary"],
}
PROBE = {"id": "c", "kind": "cell", "lat": 37.1, "lon": -122.1}


@pytest.fixture
def fake(monkeypatch):
    """fake(snap_offset_deg, route_miles: float | error_code: int) -> captured requests."""
    def setup(offset, route):
        sent = []

        def call(action, req):
            router._W["calls"] = router._W.get("calls", 0) + 1
            sent.append((action, req))
            if action == "locate":
                return [{"edges": [{"correlated_lat": PROBE["lat"] + offset, "correlated_lon": PROBE["lon"],
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
    fake(0.0027, 60.0)  # ~300 m snap, 60 road miles
    rec = router.evaluate(PROBE)
    assert rec["status"] == "unknown" and "snap_far" in rec["reasons"]


def test_far_snap_without_path_is_unknown_not_unreachable(fake):
    fake(0.0027, 442)
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
