"""RoadZone cell-map viewer: uv run streamlit run app.py"""
import colorsys
import html
import json
import math
import subprocess
import sys
from pathlib import Path

import h3
import pydeck as pdk
import streamlit as st
import yaml
from collections import Counter

from zonegen.classify import band_edges
from zonegen.pipeline import MAX_CALLS_PER_PROBE, in_boundary, load_boundary, load_config

def corridor_colour(i: int) -> tuple[int, int, int]:
    """i-th of an unlimited set of distinct colours: golden-angle hue steps, alternating lightness."""
    r, g, b = colorsys.hls_to_rgb((i * 0.618034) % 1, 0.42 if i % 2 else 0.58, 0.7)
    return round(r * 255), round(g * 255), round(b * 255)
# distinct hues (not shades of one colour) so neighbouring bands are easy to tell apart; Hub is dark slate
BANDS = [(55, 65, 81), (230, 57, 70), (247, 140, 38), (240, 200, 30), (60, 170, 80), (0, 160, 170),
         (70, 110, 220), (150, 80, 200), (230, 100, 180), (140, 100, 60), (130, 140, 40), (120, 120, 120)]
GREY, PALE = (160, 160, 165), (235, 235, 238)
MIN_LEGEND_CELLS = 10  # legend lists corridors at least this big; the map still shows every one
TIP_FIELDS = ("h3", "zone_code", "status", "m_dist_mi", "m_time_min", "family_key", "direction_method",
              "snap_dist_m", "reason_codes")

st.set_page_config(page_title="RoadZone Cell Map", layout="wide")


@st.cache_data
def load(run: str):
    fc = json.loads((Path("runs") / run / "cells.geojson").read_text())
    cells = [f["properties"] for f in fc["features"] if f["id"] != "base"]
    base = next(f for f in fc["features"] if f["id"] == "base")
    return fc["properties"], cells, base["geometry"]["coordinates"]


@st.cache_resource
def boundary():
    """The pinned extract's polygon; routing only works inside it."""
    return load_boundary(load_config(Path("configs/stevens_creek.yaml"))["data"].get("boundary"))


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
    if not in_boundary(boundary(), lat, lon):
        st.sidebar.error("Outside the loaded map data (California).")
    elif hub >= limit:
        st.sidebar.error("Hub must be smaller than the max coverage.")
    else:
        cfg = yaml.safe_load(Path("configs/stevens_creek.yaml").read_text())
        cfg.update(label="custom", hard_cases=None)
        cfg["base"] = {"lat": lat, "lon": lon, "confirmed": False}
        cfg["coverage"].update(limit_miles=limit, hub_miles=hub, band_step_miles=step)
        # road miles >= crow-flies miles, so this extent provably contains every covered cell
        cfg["grid"]["extent_radius_km"] = round(limit * 1.609344 + 2, 1)
        # budget scales with area: ~0.737 km² per res-8 cell
        cfg["request_budget"] = int(MAX_CALLS_PER_PROBE * math.pi * cfg["grid"]["extent_radius_km"] ** 2 / 0.737 * 1.1)
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


def run_cfg(rid: str) -> dict | None:
    """Coverage settings frozen into the run; older runs fall back to their (possibly edited) config file."""
    try:
        meta = json.loads((Path("runs") / rid / "run_meta.json").read_text())
        if "coverage" in meta:
            return meta
        return yaml.safe_load(Path(meta["config"]).read_text())
    except (OSError, KeyError, ValueError):
        return None


def run_label(rid: str) -> str:
    """Friendly name (runs/<id>/name.txt) plus the coverage settings, falling back to the run ID."""
    f = Path("runs") / rid / "name.txt"
    name = f.read_text().strip() if f.exists() else rid
    cfg = run_cfg(rid)
    if not cfg:
        return name
    c = cfg["coverage"]
    return f"{name} · {c['limit_miles']:g} mi, hub {c['hub_miles']:g}, bands {c['band_step_miles']:g}"


def band_labels(limit: float, hub: float, step: float, unit: str) -> list[str]:
    """Legend text from the same band edges the classifier uses."""
    edges = [0, *band_edges(hub, step, limit), limit]
    return [f"{a:g}–{b:g} {unit}" + (" (Hub)" if i == 0 else "") for i, (a, b) in enumerate(zip(edges, edges[1:]))]


run = st.sidebar.selectbox("Show run", runs, index=runs.index(default) if default in runs else len(runs) - 1,
                           format_func=run_label)
meta, cells, base = load(run)

st.title("RoadZone cell map")
st.warning(meta.get("notice", "") + ("" if meta.get("base_confirmed") else
                                     " Base point is a placeholder, not the dealer's van entrance."))

mode = st.sidebar.radio("Colour by", ["Zones", "Road-mile bands", "Free-flow minute bands"])
show_out = st.sidebar.checkbox("Show outside / unreachable cells", value=False)
show_unknown = st.sidebar.checkbox("Show unknown cells (near a road)", value=True)
show_noroad = st.sidebar.checkbox("Show no-road / track-only / no-map-data cells", value=False)

corridors = sorted({c["display_corridor_id"] for c in cells if c.get("display_corridor_id")})
ccol = {cid: (82, 82, 91) if cid == "HUB" else (194, 168, 120) if cid == "L" else corridor_colour(i)
        for i, cid in enumerate(corridors)}
# isolated patch: a zoned cell whose zoned neighbours are mostly another corridor (display flag only)
solid = {c["h3"]: c["display_corridor_id"] for c in cells if c.get("zone_code") and c.get("hatch_status") != "hatched"}


def isolated(cid: str) -> bool:
    if solid[cid] in ("HUB", "L"):
        return False
    # Hub and local-road neighbours don't count: the Hub's edge is a boundary, not a patch
    nb = [solid[n] for n in h3.grid_ring(cid, 1) if n in solid and solid[n] not in ("HUB", "L")]
    return len(nb) >= 3 and sum(x != solid[cid] for x in nb) / len(nb) > 0.5

rows = []
for c in cells:
    if c["status"] in ("outside_coverage", "unreachable") and not show_out:
        continue
    noroad = any(r in (c.get("reason_codes") or "") for r in ("snap_failed", "snap_track", "data_unavailable"))
    if c["status"] == "unknown" and not (show_noroad if noroad else show_unknown):
        continue
    uncertain = c.get("hatch_status") == "hatched"
    if c["status"] in ("outside_coverage", "unreachable"):
        rgb = PALE
    elif mode == "Zones":
        rgb = ccol.get(c.get("display_corridor_id"), GREY)
    else:
        b = c.get("band") if mode == "Road-mile bands" else c.get("band_time")
        rgb = BANDS[b % len(BANDS)] if b is not None else GREY
    # pydeck can't hatch: uncertain cells are drawn faint instead (outlines turn the map black when zoomed out)
    row = {k: ("" if c.get(k) is None else c[k]) for k in TIP_FIELDS}  # only what the map needs: big runs stay fast
    row["fill"] = [*rgb, 50 if uncertain else 180]
    patch = mode == "Zones" and c["h3"] in solid and isolated(c["h3"])
    row["patch"] = "isolated patch" if patch else ""
    rows.append(row)

layer = pdk.Layer("H3HexagonLayer", rows, get_hexagon="h3", get_fill_color="fill", stroked=False,
                  extruded=False, pickable=True, auto_highlight=True)
# outlines in their own layer, only for isolated patches: stroking every cell leaves seams across the map
patch_layer = pdk.Layer("H3HexagonLayer", [r for r in rows if r["patch"]], get_hexagon="h3", filled=False,
                        stroked=True, get_line_color=[20, 20, 20, 230], line_width_min_pixels=1.5, extruded=False)
base_layer = pdk.Layer("ScatterplotLayer", [{"pos": base}], get_position="pos", get_radius=400,
                       get_fill_color=[0, 0, 0], pickable=False)
# plain-text tooltip: corridor names come from editable OSM tags and must not be rendered as HTML
tooltip = {"text": "{zone_code} {status} {patch}\n{m_dist_mi} mi · {m_time_min} free-flow min\n"
                   "corridor: {family_key} ({direction_method})\nsnap: {snap_dist_m} m\nreasons: {reason_codes}"}
st.pydeck_chart(pdk.Deck(layers=[layer, patch_layer, base_layer], tooltip=tooltip, map_style="light",
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
        size = Counter(c.get("display_corridor_id") for c in cells if c.get("hatch_status") != "hatched")
        small = [cid for cid in corridors if cid not in ("HUB", "L") and size[cid] < MIN_LEGEND_CELLS]
        for cid in corridors:
            if cid in small:
                continue  # display only: tiny corridors keep their letter on the map and in the tooltip
            label = "Hub (zone 0)" if cid == "HUB" else "Local roads" if cid == "L" else f"{cid}: {fams.get(cid, '')}"
            st.markdown(f"<span style='color:rgb{ccol[cid]}'>■</span> {html.escape(label)}", unsafe_allow_html=True)
        if small:
            st.caption(f"+ {len(small)} small corridors (under {MIN_LEGEND_CELLS} cells each): "
                       + ", ".join(f"{cid} ({fams.get(cid, '?')})" for cid in small))
    else:
        cfg = run_cfg(run) or {"coverage": {"limit_miles": 50, "hub_miles": 5, "band_step_miles": 10},
                               "time_view": {"limit_minutes": 60, "hub_minutes": 15, "band_step_minutes": 15}}
        c, t = cfg["coverage"], cfg["time_view"]
        labels = (band_labels(c["limit_miles"], c["hub_miles"], c["band_step_miles"], "mi") if mode == "Road-mile bands"
                  else band_labels(t["limit_minutes"], t["hub_minutes"], t["band_step_minutes"], "min"))
        for i, l in enumerate(labels):
            st.markdown(f"<span style='color:rgb{BANDS[i % len(BANDS)]}'>■</span> Band {i}: {l}",
                        unsafe_allow_html=True)
    st.caption("Faint cells = unknown / mixed / needs review (display colour only, not an assignment).")
    if mode == "Zones":
        st.caption("Outlined cells = isolated patch: reached by a different corridor than most of their neighbours. "
                   "A real result shown as an exception, not merged away.")
with right:
    st.subheader("Cell counts")
    counts = {}
    for c in cells:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    st.table({"status": list(counts), "cells": list(counts.values())})

with st.expander("Failure report"):
    st.markdown((Path("runs") / run / "failure_report.md").read_text())
