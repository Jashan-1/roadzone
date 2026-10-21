from zonegen.lookup import parse_coordinates, summarize, zone_letters

MI = 1609.344


def test_parse_coordinates_accepts_google_maps_copy_and_rejects_text():
    assert parse_coordinates("37.32305, -121.97") == (37.32305, -121.97)
    assert parse_coordinates(" 37.3 -121.9 ") == (37.3, -121.9)
    assert parse_coordinates("123 Main St, San Jose") is None
    assert parse_coordinates("137.3, -121.9") is None  # latitude out of range


def _rec(status="centroid_sampled", band=2, corridor=None, **kw):
    return {"status": status, "band": band, "corridor": corridor, "reasons": [], "m_dist": 16 * MI, "m_time": 1200, **kw}


def test_summarize_uses_the_runs_letter_and_flags_unknown_corridors():
    letters = zone_letters([{"family_key": "CA 17 | S", "zone_code": "2B", "corridor_status": "supported"}])
    on_map = summarize(_rec(corridor={"status": "supported", "family_key": ["CA 17", "S"]}), letters)
    assert on_map["zone"] == "2B" and not on_map["review"] and on_map["miles"] == 16.0
    off_map = summarize(_rec(corridor={"status": "supported", "family_key": ["CA 1", "S"]}), letters)
    assert off_map["zone"] == "2?" and off_map["review"]


def test_summarize_hub_local_review_and_outside():
    assert summarize(_rec(band=0), {})["zone"] == "0"
    assert summarize(_rec(corridor={"status": "local"}), {})["zone"] == "2L"
    assert summarize(_rec(corridor={"status": "review_required"}), {})["review"]
    out = summarize(_rec(status="outside_coverage", band=None), {})
    assert out["zone"] is None and not out["review"]
    track = summarize(_rec(band=0, review_required=True), {})
    assert track["zone"] == "0" and track["review"]  # track-access home keeps its zone but needs a check
