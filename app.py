"""RoadZone cell-map viewer: uv run streamlit run app.py"""
import json
import math
import subprocess
import sys
from pathlib import Path

import pydeck as pdk
import streamlit as st
import yaml

from zonegen.pipeline import load_config

PALETTE = [(31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40), (148, 103, 189), (140, 86, 75),
           (227, 119, 194), (23, 190, 207), (188, 189, 34), (57, 59, 121), (99, 121, 57), (140, 109, 49),
           (132, 60, 57), (123, 65, 115), (49, 130, 189), (127, 127, 127)]
BANDS = [(8, 48, 107), (33, 113, 181), (66, 146, 198), (107, 174, 214), (158, 202, 225), (198, 219, 239)]
GREY, PALE = (160, 160, 165), (235, 235, 238)

st.set_page_config(page_title="RoadZone Cell Map", layout="wide")


@st.cache_data
def load(run: str):
    fc = json.loads((Path("runs") / run / "cells.geojson").read_text())
    cells = [f["properties"] for f in fc["features"] if f["id"] != "base"]
    base = next(f for f in fc["features"] if f["id"] == "base")
    return fc["properties"], cells, base["geometry"]["coordinates"]


@st.cache_data
def extract_bounds():
    """Lat/lon box of the pinned OSM extract; routing only works inside it."""
    import osmium
    pbf = load_config(Path("configs/stevens_creek.yaml"))["data"]["pbf"]
    box = osmium.io.Reader(pbf, osmium.osm.osm_entity_bits.NOTHING).header().box()
    return box.bottom_left.lat, box.bottom_left.lon, box.top_right.lat, box.top_right.lon


with st.sidebar.form("new_run"):
    st.subheader("New run")
    name = st.text_input("Run name", placeholder="e.g. Santa Rosa dealership")
    lat = st.number_input("Base latitude", value=37.32305, format="%.5f")
    lon = st.number_input("Base longitude", value=-121.97000, format="%.5f")
    limit = st.number_input("Max coverage (road miles)", 5.0, 80.0, 50.0, 5.0)
    hub = st.number_input("Hub size (road miles)", 1.0, 40.0, 5.0, 1.0)
    step = st.number_input("Band size (road miles)", 1.0, 50.0, 10.0, 1.0)
    go = st.form_submit_button("Generate zones")
if go and not (Path("data/valhalla_tiles").exists() and
               Path(load_config(Path("configs/stevens_creek.yaml"))["data"]["pbf"]).exists()):
    st.sidebar.error("Map data is still downloading or building. Try again when it finishes.")
elif go:
    s, w, n, e = extract_bounds()
    if not (s <= lat <= n and w <= lon <= e):
        st.sidebar.error(f"Outside the loaded map data (lat {s:.1f}–{n:.1f}, lon {w:.1f}–{e:.1f}).")
    elif hub >= limit:
        st.sidebar.error("Hub must be smaller than the max coverage.")
    else:
        cfg = yaml.safe_load(Path("configs/stevens_creek.yaml").read_text())
        cfg.update(label="custom", hard_cases=None)
        cfg["base"] = {"lat": lat, "lon": lon, "confirmed": False}
        cfg["coverage"].update(limit_miles=limit, hub_miles=hub, band_step_miles=step)
        # road miles >= crow-flies miles, so this extent provably contains every covered cell
        cfg["grid"]["extent_radius_km"] = round(limit * 1.609344 + 2, 1)
        # budget scales with area: ~0.737 km² per res-8 cell, at most 5 router calls per cell
        cfg["request_budget"] = int(5 * math.pi * cfg["grid"]["extent_radius_km"] ** 2 / 0.737 * 1.1)
        path = Path("configs/custom") / f"{lat:.5f}_{lon:.5f}_{limit:g}_{hub:g}_{step:g}.yaml"
        path.parent.mkdir(exist_ok=True)
        path.write_text(yaml.safe_dump(cfg, sort_keys=False))
        with st.spinner(f"Routing every cell out and back (~{limit / 50 * limit / 50 * 2.5:.0f} min)…"):
            proc = subprocess.run([sys.executable, "-m", "zonegen", "run", str(path)], capture_output=True, text=True)
        if proc.returncode:
            st.sidebar.error(proc.stderr[-1500:])
        else:
            st.session_state["run"] = Path(proc.stdout.strip().splitlines()[-1]).name
            if name.strip():
                (Path("runs") / st.session_state["run"] / "name.txt").write_text(name.strip())
            load.clear()

runs = sorted((p for p in Path("runs").iterdir() if (p / "cells.geojson").exists()), key=lambda p: p.stat().st_mtime)
runs = [p.name for p in runs]
if not runs:
    st.error("No runs found. Run `uv run python -m zonegen run configs/stevens_creek.yaml` first.")
    st.stop()
default = st.session_state.get("run", runs[-1])


def run_label(rid: str) -> str:
    """Friendly name (runs/<id>/name.txt) plus the coverage settings, falling back to the run ID."""
    f = Path("runs") / rid / "name.txt"
    name = f.read_text().strip() if f.exists() else rid
    try:
        cfg_file = json.loads((Path("runs") / rid / "run_meta.json").read_text())["config"]
        c = yaml.safe_load(Path(cfg_file).read_text())["coverage"]
        return f"{name} · {c['limit_miles']:g} mi, hub {c['hub_miles']:g}, bands {c['band_step_miles']:g}"
    except (OSError, KeyError, ValueError):
        return name


run = st.sidebar.selectbox("Show run", runs, index=runs.index(default) if default in runs else len(runs) - 1,
                           format_func=run_label)
meta, cells, base = load(run)

st.title("RoadZone cell map")
st.warning("POC, pre-kickoff. Not a published plan. Base point is a placeholder, not the dealer's van entrance. "
           "Time bands are free-flow (no traffic)." if not meta.get("base_confirmed") else meta["notice"])

mode = st.sidebar.radio("Colour by", ["Zones", "Road-mile bands", "Free-flow minute bands"])
show_out = st.sidebar.checkbox("Show outside / unreachable cells", value=False)
show_unknown = st.sidebar.checkbox("Show unknown cells (near a road)", value=True)
show_noroad = st.sidebar.checkbox("Show no-road cells (water, wilderness)", value=False)

corridors = sorted({c["display_corridor_id"] for c in cells if c.get("display_corridor_id")})
ccol = {cid: (82, 82, 91) if cid == "HUB" else (194, 168, 120) if cid == "L" else PALETTE[i % len(PALETTE)]
        for i, cid in enumerate(corridors)}

rows = []
for c in cells:
    if c["status"] in ("outside_coverage", "unreachable") and not show_out:
        continue
    noroad = "snap_failed" in (c.get("reason_codes") or "")
    if c["status"] == "unknown" and not (show_noroad if noroad else show_unknown):
        continue
    uncertain = c.get("hatch_status") == "hatched"
    if c["status"] in ("outside_coverage", "unreachable"):
        rgb = PALE
    elif mode == "Zones":
        rgb = ccol.get(c.get("display_corridor_id"), GREY)
    else:
        b = c.get("band") if mode == "Road-mile bands" else c.get("band_time")
        rgb = BANDS[b] if b is not None else GREY
    # pydeck can't hatch: uncertain cells are drawn faint instead (outlines turn the map black when zoomed out)
    rows.append({**{k: ("" if v is None else v) for k, v in c.items()}, "fill": [*rgb, 50 if uncertain else 180]})

layer = pdk.Layer("H3HexagonLayer", rows, get_hexagon="h3", get_fill_color="fill", stroked=False,
                  extruded=False, pickable=True, auto_highlight=True)
base_layer = pdk.Layer("ScatterplotLayer", [{"pos": base}], get_position="pos", get_radius=400,
                       get_fill_color=[0, 0, 0], pickable=False)
tooltip = {"html": "<b>{zone_code}</b> {status}<br/>{m_dist_mi} mi · {m_time_min} free-flow min<br/>"
                   "corridor: {family_key} ({direction_method})<br/>snap: {snap_dist_m} m<br/>reasons: {reason_codes}"}
st.pydeck_chart(pdk.Deck(layers=[layer, base_layer], tooltip=tooltip, map_style="light",
                         initial_view_state=pdk.ViewState(latitude=base[1], longitude=base[0], zoom=8.5)),
                height=650)

left, right = st.columns(2)
with left:
    st.subheader("Legend")
    if mode == "Zones":
        fams = {}
        for c in cells:
            if c.get("display_corridor_id") and c.get("family_key") and c.get("hatch_status") != "hatched":
                fams.setdefault(c["display_corridor_id"], c["family_key"])
        for cid in corridors:
            label = "Hub (zone 0)" if cid == "HUB" else "Local roads" if cid == "L" else f"{cid}: {fams.get(cid, '')}"
            st.markdown(f"<span style='color:rgb{ccol[cid]}'>■</span> {label}", unsafe_allow_html=True)
    else:
        labels = (["0–5 mi Hub", "5–15", "15–25", "25–35", "35–45", "45–50 mi"] if mode == "Road-mile bands"
                  else ["0–15 min Hub", "15–30", "30–45", "45–60 min"])
        for i, l in enumerate(labels):
            st.markdown(f"<span style='color:rgb{BANDS[i]}'>■</span> Band {i}: {l}", unsafe_allow_html=True)
    st.caption("Faint cells = unknown / mixed / needs review (display colour only, not an assignment).")
with right:
    st.subheader("Cell counts")
    counts = {}
    for c in cells:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    st.table({"status": list(counts), "cells": list(counts.values())})

with st.expander("Failure report"):
    st.markdown((Path("runs") / run / "failure_report.md").read_text())
