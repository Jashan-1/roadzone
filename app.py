"""RoadZone cell-map viewer: uv run streamlit run app.py"""
import json
from pathlib import Path

import pydeck as pdk
import streamlit as st

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


runs = sorted(p.name for p in Path("runs").iterdir() if (p / "cells.geojson").exists())
if not runs:
    st.error("No runs found. Run `uv run python -m zonegen run configs/stevens_creek.yaml` first.")
    st.stop()
run = st.sidebar.selectbox("Run", runs, index=len(runs) - 1)
meta, cells, base = load(run)

st.title("RoadZone: Stevens Creek")
st.warning("POC, pre-kickoff. Not a published plan. Base point is a placeholder, not the dealer's van entrance. "
           "Time bands are free-flow (no traffic)." if not meta.get("base_confirmed") else meta["notice"])

mode = st.sidebar.radio("Colour by", ["Zones", "Road-mile bands", "Free-flow minute bands"])
show_out = st.sidebar.checkbox("Show outside / unreachable cells", value=False)
show_unknown = st.sidebar.checkbox("Show unknown cells", value=True)

corridors = sorted({c["display_corridor_id"] for c in cells if c.get("display_corridor_id")})
ccol = {cid: (82, 82, 91) if cid == "HUB" else (194, 168, 120) if cid == "L" else PALETTE[i % len(PALETTE)]
        for i, cid in enumerate(corridors)}

rows = []
for c in cells:
    if c["status"] in ("outside_coverage", "unreachable") and not show_out:
        continue
    if c["status"] == "unknown" and not show_unknown:
        continue
    uncertain = c.get("hatch_status") == "hatched"
    if c["status"] in ("outside_coverage", "unreachable"):
        rgb = PALE
    elif mode == "Zones":
        rgb = ccol.get(c.get("display_corridor_id"), GREY)
    else:
        b = c.get("band") if mode == "Road-mile bands" else c.get("band_time")
        rgb = BANDS[b] if b is not None else GREY
    # pydeck can't hatch: uncertain cells are faint fills with a dark outline instead
    rows.append({**{k: ("" if v is None else v) for k, v in c.items()},
                 "fill": [*rgb, 60 if uncertain else 170], "line": [40, 40, 40, 200] if uncertain else [0, 0, 0, 0]})

layer = pdk.Layer("H3HexagonLayer", rows, get_hexagon="h3", get_fill_color="fill", get_line_color="line",
                  line_width_min_pixels=1, extruded=False, pickable=True, auto_highlight=True)
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
    st.caption("Faint, outlined cells = unknown / mixed / needs review (display colour only, not an assignment).")
with right:
    st.subheader("Cell counts")
    counts = {}
    for c in cells:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    st.table({"status": list(counts), "cells": list(counts.values())})

with st.expander("Failure report"):
    st.markdown((Path("runs") / run / "failure_report.md").read_text())
