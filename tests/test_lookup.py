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


def _cells_run(root, rid, name=None, coverage=None):
    import json
    d = root / "runs" / rid
    d.mkdir(parents=True)
    cell = {"zone_code": "2AB", "hatch_status": "none", "status": "centroid_sampled", "h3": "8828308281fffff",
            "display_corridor_id": "AB", "family_key": "CA 67 | E"}
    feats = [{"id": "c1", "properties": cell},
             {"id": "c2", "properties": {**cell, "zone_code": None, "status": "outside_coverage"}},
             {"id": "base", "properties": {}, "geometry": {"type": "Point", "coordinates": [-121.97, 37.32]}}]
    (d / "cells.geojson").write_text(json.dumps({"features": feats}))
    (d / "run_meta.json").write_text(json.dumps({"config": "configs/x.yaml", **({"coverage": coverage} if coverage else {})}))
    if name:
        (d / "name.txt").write_text(name)


def test_locations_keep_the_newest_run_per_shop_and_zones_outline_solid_cells(tmp_path, monkeypatch):
    import json, os
    from zonegen import serve
    monkeypatch.chdir(tmp_path)
    _cells_run(tmp_path, "old", "Stevens Creek")
    _cells_run(tmp_path, "new", "Stevens Creek", {"limit_miles": 40, "hub_miles": 5, "band_step_miles": 10, "metric": "distance"})
    os.utime(tmp_path / "runs" / "old" / "cells.geojson", (1, 1))
    os.utime(tmp_path / "runs" / "old", (1, 1))
    code, locs = serve.locations()
    assert code == 200 and len(locs) == 1 and locs[0]["run"] == "new"
    assert sorted((v["run"], v["limit_miles"]) for v in locs[0]["variants"]) == [("new", 40.0), ("old", 50.0)]
    serve._zones.cache_clear()
    code, body = serve.zones("new")
    fc = json.loads(body)
    assert code == 200 and fc["base"] == [-121.97, 37.32]
    assert [f["properties"] for f in fc["features"]] == [{"zone": "2AB", "band": 2, "cells": 1, "corridor": "AB", "road": "CA-67 east"}]  # out-of-area cell left out
    assert [f["properties"]["zone"] for f in fc["labels"]["features"]] == ["2AB"]
    assert fc["corridors"] == [{"id": "AB", "road": "CA-67 east", "cells": 1}]
    assert serve.zones("../etc")[0] == 404


def test_admin_runs_reject_bad_settings():
    from zonegen import serve
    ok = {"where": "37.32, -121.97", "limit_miles": 50, "hub_miles": 5, "band_step_miles": 10,
          "min_corridor_cells": 30, "highways": ["I"]}
    assert serve.start_run({**ok, "highways": []})[0] == 400
    assert serve.start_run({**ok, "highways": ["XX"]})[0] == 400
    assert serve.start_run({**ok, "where": "Main St"})[0] == 400
    assert serve.start_run({**ok, "hub_miles": 50})[0] == 400
    assert serve.start_run({**ok, "limit_miles": 500})[0] == 400
    assert serve.start_run({k: v for k, v in ok.items() if k != "limit_miles"})[0] == 400
    assert serve.start_run({**ok, "from_run": "../etc"})[0] == 404


def test_remaking_a_run_keeps_its_base_and_name(tmp_path, monkeypatch):
    import yaml
    from zonegen import serve
    monkeypatch.chdir(tmp_path)
    _cells_run(tmp_path, "src", "Stevens Creek")
    started = {}
    monkeypatch.setattr(serve, "_job", lambda jid, path, name: started.update(path=path, name=name))
    monkeypatch.setattr(serve, "in_boundary", lambda *a: True)
    monkeypatch.setattr(serve, "load_config", lambda p: {"data": {"snapshot": "snap.json"}})
    (tmp_path / "data" / "valhalla_tiles").mkdir(parents=True)
    (tmp_path / "snap.json").write_text("{}")
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "x.yaml").write_text(yaml.safe_dump(
        {"base": {"lat": 37.3, "lon": -121.9}, "coverage": {"limit_miles": 50, "hub_miles": 5, "band_step_miles": 10},
         "grid": {}, "label": "x"}))
    serve.JOBS.clear()
    code, job = serve.start_run({"from_run": "src", "limit_miles": 40, "hub_miles": 5, "band_step_miles": 10,
                                 "min_corridor_cells": 0, "highways": ["US", "I"]})
    serve.JOBS.clear()
    assert code == 202 and job["name"] == "Stevens Creek" and started["name"] == "Stevens Creek"
    assert job["kind"] == "remake"  # the New location dialog lists only "new" jobs
    cfg = yaml.safe_load(started["path"].read_text())
    assert cfg["base"] == {"lat": 37.3, "lon": -121.9} and cfg["coverage"]["limit_miles"] == 40
    assert cfg["highway_types"] == ["I", "US"] and cfg["min_corridor_cells"] == 0


def test_static_never_serves_outside_the_build(tmp_path, monkeypatch):
    from zonegen import serve
    (tmp_path / "index.html").write_text("page")
    (tmp_path / "app.js").write_text("js")
    monkeypatch.setattr(serve, "WEB", tmp_path)
    assert serve.static("/app.js")[1] == b"js"
    assert serve.static("/../../etc/passwd")[1] == b"page"
    assert serve.static("/admin")[1] == b"page"


def test_each_sizeable_piece_of_a_zone_gets_a_label(monkeypatch):
    import h3
    from zonegen import serve
    a = h3.latlng_to_cell(37.3, -121.9, 8)
    big, far = h3.grid_disk(a, 1), h3.grid_disk(h3.latlng_to_cell(37.6, -121.5, 8), 1)  # two 7-cell patches
    assert sorted(map(len, serve._pieces([*big, *far]))) == [7, 7]
    lone = h3.latlng_to_cell(37.0, -122.2, 8)
    assert sorted(map(len, serve._pieces([*big, lone]))) == [1, 7]
    cells = [{"zone_code": "2C", "hatch_status": "none", "status": "centroid_sampled", "h3": c}
             for c in [*big, *far, lone]]
    monkeypatch.setattr(serve, "MIN_LABEL_CELLS", 7)
    import json
    fc = {"features": [*({"id": c["h3"], "properties": c} for c in cells),
                       {"id": "base", "properties": {}, "geometry": {"coordinates": [-121.9, 37.3]}}]}
    monkeypatch.setattr(serve.Path, "read_text", lambda self: json.dumps(fc))
    monkeypatch.setattr(serve, "_settings", lambda d: {})
    serve._zones.cache_clear()
    out = json.loads(serve._zones("x"))
    serve._zones.cache_clear()
    assert sorted(f["properties"]["cells"] for f in out["labels"]["features"]) == [7, 7]  # lone cell: no label


def test_idle_connection_does_not_block_others(tmp_path, monkeypatch):
    """A connection that opens and sends nothing (browser preconnect, scanner) must not hang the page for everyone."""
    import socket
    import threading
    import urllib.request
    from zonegen import serve
    monkeypatch.chdir(tmp_path)
    srv = serve.server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        idle = socket.create_connection(("127.0.0.1", port))
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/jobs", timeout=5) as r:
            assert r.status == 200
        idle.close()
    finally:
        srv.shutdown()
