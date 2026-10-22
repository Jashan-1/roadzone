"""RoadZone cell-map viewer: uv run streamlit run app.py"""
import colorsys
import html
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

import h3
import pydeck as pdk
import streamlit as st
import yaml
from collections import Counter, defaultdict

from zonegen import lookup
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
    where = st.text_input("Base location (lat, lon)", value="37.32305, -121.97000",
                          help="Paste coordinates as copied from Google Maps.")
    limit = st.number_input("Max coverage (road miles)", 5.0, 80.0, 50.0, 5.0)
    hub = st.number_input("Hub size (road miles)", 1.0, 40.0, 5.0, 1.0)
    step = st.number_input("Band size (road miles)", 1.0, 50.0, 10.0, 1.0)
    go = st.form_submit_button("Generate zones")
if go and not (Path("data/valhalla_tiles").exists() and
               Path(load_config(Path("configs/stevens_creek.yaml"))["data"]["pbf"]).exists()):
    st.sidebar.error("Map data is still downloading or building. Try again when it finishes.")
elif go:
    lat, lon = lookup.parse_coordinates(where) or (None, None)
    if lat is None:
        st.sidebar.error(f"Couldn't read '{where}'. Use 'latitude, longitude', e.g. 33.76908, -117.85139.")
    elif not in_boundary(boundary(), lat, lon):
        st.sidebar.error(f"{lat:.5f}, {lon:.5f} is outside the loaded map data (California).")
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


def _zone_key(code: str) -> tuple:
    m = re.match(r"(\d+)(.*)", code)
    return (int(m.group(1)), m.group(2)) if m else (999, code)


def _solid_zones(cells: list[dict]) -> dict[str, list[str]]:
    """zone code -> its confidently zoned cells (faint / unknown cells never count as zone area)."""
    zones = defaultdict(list)
    for c in cells:
        if c.get("zone_code") and c.get("hatch_status") != "hatched" and c["status"] == "centroid_sampled":
            zones[c["zone_code"]].append(c["h3"])
    return zones


@st.cache_data
def zone_codes(run: str) -> list[str]:
    return sorted(_solid_zones(load(run)[1]), key=_zone_key)


@st.cache_data
def zone_shapes(run: str) -> tuple[dict, list[dict]]:
    """Merged outline per zone (GeoJSON) and one label point per zone, on its member cell nearest the zone's middle."""
    feats, labels = [], []
    for code, members in _solid_zones(load(run)[1]).items():
        feats.append({"type": "Feature", "properties": {"zone": code}, "geometry": h3.cells_to_geo(members)})
        pts = [h3.cell_to_latlng(m) for m in members]
        mid = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        lat, lon = min(pts, key=lambda p: (p[0] - mid[0]) ** 2 + (p[1] - mid[1]) ** 2)
        labels.append({"pos": [lon, lat], "zone": code, "cells": len(members)})
    return {"type": "FeatureCollection", "features": feats}, labels


run = st.sidebar.selectbox("Show run", runs, index=runs.index(default) if default in runs else len(runs) - 1,
                           format_func=run_label)
compare = st.sidebar.multiselect("Compare with branches", [r for r in runs if r != run], format_func=run_label,
                                 max_selections=2, help="Other dealership locations (runs) shown side by side")
ZONES, CORRIDORS = "Zones (band + corridor)", "Corridors (highway)"
mode = st.sidebar.radio("Colour by", [ZONES, CORRIDORS, "Road-mile bands", "Free-flow minute bands"],
                        help="A zone is a band plus a corridor: 1A and 2A are on the same highway, one band apart. Zones shade each highway darker per band.")
by_corridor = mode in (ZONES, CORRIDORS)
opacity = st.sidebar.slider("Zone opacity", 10, 100, 70, 5, format="%d%%",
                            help="Lower it to see the streets and place names under the zones.") / 100
focus = None
if mode == ZONES:
    focus = st.sidebar.selectbox("Highlight a zone", ["All zones", *zone_codes(run)],
                                 help="Dims every other zone so one zone's shape is easy to see.")
    focus = None if focus == "All zones" else focus
show_out = st.sidebar.checkbox("Show outside / unreachable cells", value=False)
show_unknown = st.sidebar.checkbox("Show unknown cells (near a road)", value=True)
show_noroad = st.sidebar.checkbox("Show no-road / track-only / no-map-data cells", value=False)
meta, cells, base = load(run)
st.session_state.setdefault("addresses", [])
st.session_state.setdefault("view_nonce", 0)

st.title("RoadZone cell map")
st.warning(meta.get("notice", "") + ("" if meta.get("base_confirmed") else
                                     " Base point is a placeholder, not the dealer's van entrance."))


def shade(rgb: tuple[int, int, int], band: int | None) -> tuple[int, int, int]:
    """Same hue, darker for each band further out (band 1 unchanged): 1A, 2A, 3A read as one highway."""
    f = max(0.4, 1 - 0.2 * ((band or 1) - 1))
    return tuple(int(x * f) for x in rgb)


def corridor_colours(cells: list[dict]) -> tuple[list[str], dict]:
    corridors = sorted({c["display_corridor_id"] for c in cells if c.get("display_corridor_id")})
    return corridors, {cid: (82, 82, 91) if cid == "HUB" else (194, 168, 120) if cid == "L" else corridor_colour(i)
                       for i, cid in enumerate(corridors)}


def map_layers(cells: list[dict], run: str) -> list:
    """Cell fill, isolated-patch outlines and address pins for one run, using the sidebar's colour and filters."""
    _, ccol = corridor_colours(cells)
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
        elif noroad:
            rgb = GREY  # ocean / roadless land: a corridor colour there reads as a coverage claim (decision 20)
        elif by_corridor:
            rgb = ccol.get(c.get("display_corridor_id"), GREY)
            if mode == ZONES and c.get("display_corridor_id") not in ("HUB", None):
                rgb = shade(rgb, c.get("band"))
        else:
            b = c.get("band") if mode == "Road-mile bands" else c.get("band_time")
            rgb = BANDS[b % len(BANDS)] if b is not None else GREY
        # pydeck can't hatch: uncertain cells are drawn faint instead
        row = {k: ("" if c.get(k) is None else c[k]) for k in TIP_FIELDS}  # only what the map needs: big runs stay fast
        dim = focus and c.get("zone_code") != focus
        row["fill"] = [*rgb, int((28 if dim else 70 if uncertain else 255) * opacity)]
        row["patch"] = "isolated patch" if by_corridor and not dim and c["h3"] in solid and isolated(c["h3"]) else ""
        rows.append(row)
    zone_layers = []
    if mode == ZONES:
        outlines, labels = zone_shapes(run)
        if focus:
            outlines = {**outlines, "features": [f for f in outlines["features"] if f["properties"]["zone"] == focus]}
            labels = [lb for lb in labels if lb["zone"] == focus]
        else:
            labels = [lb for lb in labels if lb["cells"] >= MIN_LEGEND_CELLS]  # tiny zones: tooltip only, no clutter
        zone_layers = [
            # soft light-grey zone edges, so the bold black isolated-patch rings stand out against them
            pdk.Layer("GeoJsonLayer", outlines, stroked=True, filled=False,
                      get_line_color=[40, 40, 40, 220] if focus else [190, 190, 195, 200],
                      line_width_min_pixels=3 if focus else 1),
            pdk.Layer("TextLayer", labels, get_position="pos", get_text="zone", get_size=15 if focus else 12,
                      get_color=[20, 20, 20], background=True, get_background_color=[255, 255, 255, 210],
                      font_weight=700, billboard=True),
        ]
    pins = [{**{k: "" for k in TIP_FIELDS}, "pos": [a["lon"], a["lat"]], "zone_code": "📍", "status": a["label"][:60],
             "patch": ""} for a in st.session_state["addresses"]]
    return [
        pdk.Layer("H3HexagonLayer", rows, get_hexagon="h3", get_fill_color="fill", stroked=False,
                  extruded=False, pickable=True, auto_highlight=True),
        # outlines in their own layer, only for isolated patches: stroking every cell leaves seams across the map
        pdk.Layer("H3HexagonLayer", [r for r in rows if r["patch"]], get_hexagon="h3", filled=False,
                  stroked=True, get_line_color=[0, 0, 0, 255], line_width_min_pixels=3, extruded=False),
        *zone_layers,
        pdk.Layer("ScatterplotLayer", pins, get_position="pos", get_fill_color=[220, 20, 60], get_line_color=[255, 255, 255],
                  stroked=True, line_width_min_pixels=2, radius_min_pixels=7, pickable=True),
    ]


def deck(cells: list[dict], base: list[float], run: str, zoom: float = 8.5) -> pdk.Deck:
    base_layer = pdk.Layer("ScatterplotLayer", [{"pos": base}], get_position="pos", get_radius=400,
                           get_fill_color=[0, 0, 0], pickable=False)
    # plain-text tooltip: corridor names come from editable OSM tags and must not be rendered as HTML
    tooltip = {"text": "{zone_code} {status} {patch}\n{m_dist_mi} mi · {m_time_min} free-flow min\n"
                       "corridor: {family_key} ({direction_method})\nsnap: {snap_dist_m} m\nreasons: {reason_codes}"}
    return pdk.Deck(layers=[*map_layers(cells, run), base_layer], tooltip=tooltip, map_style="light",
                    initial_view_state=pdk.ViewState(latitude=base[1], longitude=base[0], zoom=zoom))


def counts(cells: list[dict]) -> Counter:
    return Counter(c["status"] for c in cells)


tab_map, tab_addr, tab_cmp, tab_report = st.tabs(["Map", "Addresses", "Compare branches", "Failure report"])

with tab_map:
    if st.button("⌖ Re-center on base", help="Jump back to the dealership after panning or zooming away"):
        st.session_state["view_nonce"] += 1
    # Streamlit keeps a panned view across reruns; a new container key per click remounts the map at the base
    with st.container(key=f"map{st.session_state['view_nonce']}"):
        st.pydeck_chart(deck(cells, base, run), height=650)
    corridors, ccol = corridor_colours(cells)
    left, right = st.columns(2)
    with left:
        st.subheader("Legend")
        if by_corridor:
            fams, bands = {}, defaultdict(set)
            for c in cells:
                if c.get("display_corridor_id") and c.get("family_key") and c.get("hatch_status") != "hatched":
                    fams.setdefault(c["display_corridor_id"], c["family_key"])
                if c.get("zone_code") and c.get("band"):
                    bands[c["display_corridor_id"]].add(c["band"])
            size = Counter(c.get("display_corridor_id") for c in cells if c.get("hatch_status") != "hatched")
            small = [cid for cid in corridors if cid not in ("HUB", "L") and size[cid] < MIN_LEGEND_CELLS]
            for cid in corridors:
                if cid in small:
                    continue  # display only: tiny corridors keep their letter on the map and in the tooltip
                label = "Hub (zone 0)" if cid == "HUB" else "Local roads" if cid == "L" else f"{cid}: {fams.get(cid, '')}"
                if mode == ZONES and cid != "HUB":
                    sw = " ".join(f"<span style='color:rgb{shade(ccol[cid], b)}'>■</span>{b}{cid}"
                                  for b in sorted(bands[cid]))
                    st.markdown(f"{sw} · {html.escape(label)}", unsafe_allow_html=True)
                else:
                    st.markdown(f"<span style='color:rgb{ccol[cid]}'>■</span> {html.escape(label)}",
                                unsafe_allow_html=True)
            if small:
                st.caption(f"+ {len(small)} small corridors (under {MIN_LEGEND_CELLS} cells each): "
                           + ", ".join(f"{cid} ({fams.get(cid, '?')})" for cid in small))
        else:
            cfg = run_cfg(run) or {"coverage": {"limit_miles": 50, "hub_miles": 5, "band_step_miles": 10},
                                   "time_view": {"limit_minutes": 60, "hub_minutes": 15, "band_step_minutes": 15}}
            c, t = cfg["coverage"], cfg["time_view"]
            labels = (band_labels(c["limit_miles"], c["hub_miles"], c["band_step_miles"], "mi") if mode == "Road-mile bands"
                      else band_labels(t["limit_minutes"], t["hub_minutes"], t["band_step_minutes"], "min"))
            for i, lab in enumerate(labels):
                st.markdown(f"<span style='color:rgb{BANDS[i % len(BANDS)]}'>■</span> Band {i}: {lab}",
                            unsafe_allow_html=True)
        st.caption("Faint cells = unknown / mixed / needs review (display colour only, not an assignment). "
                   "Red pins = checked addresses.")
        if by_corridor:
            st.caption("Outlined cells = isolated patch: reached by a different corridor than most of their neighbours. "
                       "A real result shown as an exception, not merged away.")
    with right:
        st.subheader("Cell counts")
        n = counts(cells)
        st.table({"status": list(n), "cells": list(n.values())})

with tab_addr:
    st.subheader("Check addresses")
    st.caption("One per line: a street address, or coordinates copied from Google Maps (right-click, e.g. "
               "`37.3230, -121.9700`). Each one is routed out and back from every selected branch. "
               "Street addresses are looked up with OpenStreetMap Nominatim, an outside service, so the text "
               "leaves this machine; coordinates never do.")
    text = st.text_area("Addresses", placeholder="37.4419, -122.1430\n1 Infinite Loop, Cupertino, CA", height=120)
    go_check, go_clear = st.columns([1, 6])
    if go_clear.button("Clear"):
        st.session_state["addresses"] = []
    if go_check.button("Check", type="primary"):
        branches = [run, *compare]
        found = []
        with st.spinner(f"Routing {len(text.splitlines())} address(es) for {len(branches)} branch(es)…"):
            for line in filter(str.strip, text.splitlines()):
                point = lookup.resolve(line)
                if point is None:
                    st.error(f"Couldn't find: {line}")
                    continue
                if point["source"] != "coordinates":
                    time.sleep(1)  # Nominatim's public usage policy: at most 1 request per second
                point["results"] = {}
                for b in branches:
                    cfg_path = json.loads((Path("runs") / b / "run_meta.json").read_text())["config"]
                    try:
                        point["results"][b] = lookup.classify(cfg_path, point["lat"], point["lon"],
                                                              lookup.zone_letters(load(b)[1]))
                    except Exception as e:  # routing data missing or a broken run: show it, keep the others
                        point["results"][b] = {"status": f"error: {e}"}
                found.append(point)
        st.session_state["addresses"] = st.session_state["addresses"] + found
    for a in st.session_state["addresses"]:
        st.markdown(f"**{html.escape(a['label'])}**  \n`{a['lat']:.5f}, {a['lon']:.5f}` · {a['source']}")
        covered = {b: r for b, r in a["results"].items() if r.get("zone")}
        best = min(covered, key=lambda b: covered[b]["miles"]) if covered else None
        st.table([{"branch": ("⭐ " if b == best else "") + run_label(b), "zone": r.get("zone") or "-",
                   "road miles": f"{r['miles']:.1f}" if r.get("miles") is not None else "-",
                   "free-flow min": r.get("minutes") if r.get("minutes") is not None else "-", "status": r.get("status"),
                   "needs review": "yes" if r.get("review") else "", "corridor": r.get("corridor"),
                   "reasons": r.get("reasons")} for b, r in a["results"].items()])
    if st.session_state["addresses"]:
        st.caption("⭐ = branch with the fewest road miles among those that cover the address. Review flags mean a "
                   "person should confirm (track access, unnamed road, or a corridor not on that branch's map).")

with tab_cmp:
    branches = [run, *compare]
    if not compare:
        st.info("Pick one or two branches under **Compare with branches** in the sidebar.")
    summary = []
    for b in branches:
        m, cs, bs = load(b)
        meta_b = json.loads((Path("runs") / b / "run_meta.json").read_text()) if (Path("runs") / b / "run_meta.json").exists() else {}
        n = counts(cs)
        summary.append({"branch": run_label(b), "base": f"{bs[1]:.4f}, {bs[0]:.4f}",
                        "zoned cells": n["centroid_sampled"] + n["mixed"], "outside": n["outside_coverage"],
                        "unknown": n["unknown"], "corridors": len([x for x in corridor_colours(cs)[0] if x not in ("HUB", "L")]),
                        "fork candidates": len(meta_b.get("forks", []))})
    st.table(summary)
    cols = st.columns(len(branches))
    for col, b in zip(cols, branches):
        with col:
            st.caption(run_label(b))
            st.pydeck_chart(deck(load(b)[1], load(b)[2], b, zoom=7.8), height=420)

with tab_report:
    st.markdown((Path("runs") / run / "failure_report.md").read_text())
