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


def _served_run(root, rid="run-1"):
    import json
    d = root / "runs" / rid
    d.mkdir(parents=True)
    feats = [{"id": "c1", "properties": {"family_key": "CA 92 | E", "zone_code": "3AF", "corridor_status": "supported"}},
             {"id": "base", "properties": {}}]
    (d / "cells.geojson").write_text(json.dumps({"features": feats}))
    (d / "run_meta.json").write_text(json.dumps({"config": "configs/x.yaml"}))
    return rid


def test_zone_endpoint_answers_and_rejects_bad_input(tmp_path, monkeypatch):
    from zonegen import lookup, serve
    monkeypatch.chdir(tmp_path)
    rid = _served_run(tmp_path)
    seen = {}
    def classify(cfg, lat, lon, letters):
        seen.update(cfg=cfg, letters=letters)
        return {"zone": "3AF"}
    monkeypatch.setattr(lookup, "classify", classify)
    code, body = serve.zone_for(rid, "37.32, -121.97")
    assert code == 200 and body["zone"] == "3AF" and body["lat"] == 37.32
    assert seen == {"cfg": "configs/x.yaml", "letters": {"CA 92 | E": "AF"}}  # merged corridor keeps resolving
    assert serve.zone_for("../../etc", "37.32, -121.97")[0] == 404
    assert serve.zone_for("nope", "37.32, -121.97")[0] == 404
    assert serve.zone_for(rid, "   ")[0] == 400
    assert serve.zone_for(rid, "x" * 301)[0] == 400
    monkeypatch.setattr(lookup, "resolve", lambda q: None)
    assert serve.zone_for(rid, "nowhere")[0] == 422
