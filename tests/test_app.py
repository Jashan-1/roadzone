"""Streamlit viewer tests on two tiny fixture runs (no map data or routing needed)."""
import json
from pathlib import Path

import h3
import pytest
from streamlit.testing.v1 import AppTest

from zonegen import lookup

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _run(root: Path, rid: str, base: tuple[float, float], name: str):
    d = root / "runs" / rid
    d.mkdir(parents=True)
    hub = h3.latlng_to_cell(*base, 8)
    feats = [{"type": "Feature", "id": c, "geometry": None, "properties": {
        "h3": c, "status": "centroid_sampled", "zone_code": zone, "band": band, "band_time": band,
        "display_corridor_id": disp, "hatch_status": "none", "family_key": fam,
        "corridor_status": "supported" if fam else None, "m_dist_mi": 3.0, "m_time_min": 5.0}}
        for c, zone, band, disp, fam in [(hub, "0", 0, "HUB", None)]
        + [(n, "1A", 1, "A", "I 280 | N") for n in sorted(h3.grid_ring(hub, 1))]]
    feats.append({"type": "Feature", "id": "base", "geometry": {"type": "Point", "coordinates": [base[1], base[0]]},
                  "properties": {"kind": "base"}})
    (d / "cells.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats,
                                                 "properties": {"notice": "TEST", "base_confirmed": False}}))
    (d / "run_meta.json").write_text(json.dumps({"config": f"configs/{rid}.yaml", "forks": [],
                                                "coverage": {"limit_miles": 50, "hub_miles": 5, "band_step_miles": 10},
                                                "time_view": {"limit_minutes": 60, "hub_minutes": 15, "band_step_minutes": 15}}))
    (d / "failure_report.md").write_text(f"# report {rid}")
    (d / "name.txt").write_text(name)


@pytest.fixture
def app(tmp_path, monkeypatch):
    _run(tmp_path, "run-a", (37.32, -121.97), "Branch A")
    _run(tmp_path, "run-b", (37.40, -122.10), "Branch B")
    monkeypatch.chdir(tmp_path)
    return AppTest.from_file(APP, default_timeout=60)


def _button(at, label):
    return next(b for b in at.button if label in b.label)


def test_renders_every_tab_without_errors(app):
    at = app.run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Map", "Addresses", "Compare branches", "Failure report"]


def test_recenter_button_resets_the_view(app):
    at = app.run()
    _button(at, "Re-center").click().run()
    assert at.session_state["view_nonce"] == 1 and not at.exception


def test_compare_lists_each_selected_branch(app):
    at = app.run()
    at.sidebar.multiselect[0].set_value([at.sidebar.multiselect[0].options[0]]).run()
    summary = at.table[-1].value  # the compare tab's table renders last
    assert len(summary) == 2 and not at.exception


def test_addresses_get_a_zone_per_branch_and_a_best_branch(app, monkeypatch):
    miles = {"configs/run-a.yaml": 12.0, "configs/run-b.yaml": 30.0}
    monkeypatch.setattr(lookup, "classify", lambda cfg, lat, lon, letters: {
        "status": "centroid_sampled", "zone": "1A", "miles": miles[cfg], "minutes": 20, "review": False,
        "corridor": "I 280 | N", "reasons": "-"})
    at = app.run()
    at.sidebar.multiselect[0].set_value([at.sidebar.multiselect[0].options[0]]).run()
    at.text_area[0].set_value("37.3300, -121.9600").run()
    _button(at, "Check").click().run()
    assert not at.exception
    results = at.session_state["addresses"][0]["results"]
    assert {r["miles"] for r in results.values()} == {12.0, 30.0}
    best = [row for t in at.table for row in t.value.to_dict("records") if str(row.get("branch", "")).startswith("⭐")]
    assert len(best) == 1 and best[0]["road miles"] == "12.0"


def test_unparseable_line_reports_an_error(app, monkeypatch):
    monkeypatch.setattr(lookup, "resolve", lambda text: None)
    at = app.run()
    at.text_area[0].set_value("nowhere at all").run()
    _button(at, "Check").click().run()
    assert any("Couldn't find" in e.value for e in at.error) and at.session_state["addresses"] == []
