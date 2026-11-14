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


def band_colour(band: int, last: int) -> tuple[int, int, int]:
    """Green at the first band to red at the last; the Hub stays dark slate."""
    if band == 0:
        return 55, 65, 81
    r, g, b = colorsys.hsv_to_rgb(max(0, last - band) / max(1, last - 1) / 3, 0.75, 0.85)
    return round(r * 255), round(g * 255), round(b * 255)


GREY, PALE = (160, 160, 165), (235, 235, 238)
HIGHWAYS = {"Interstates — like I-280, I-880": "I", "US highways — like US-101": "US",
            "State highways — like CA-17, CA-85": "CA"}
NO_ZONE = {"outside_coverage": "Too far", "unreachable": "No road"}
MIN_LEGEND_CELLS = 10  # legend lists corridors at least this big; the map still shows every one
TIP_FIELDS = ("h3", "zone_code", "status", "m_dist_mi", "m_time_min", "family_key", "direction_method",
              "snap_dist_m", "reason_codes")

st.set_page_config(page_title="RoadZone", layout="wide")


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


def make_run(cfg: dict, name: str, wait_msg: str) -> None:
    """Write the config, run the pipeline, name the run and select it. Errors show in the sidebar."""
    b, c = cfg["base"], cfg["coverage"]
    # road miles >= crow-flies miles, so this extent provably contains every covered cell
    cfg["grid"]["extent_radius_km"] = round(c["limit_miles"] * 1.609344 + 2, 1)
    # budget scales with area: ~0.737 km² per res-8 cell
    cfg["request_budget"] = int(MAX_CALLS_PER_PROBE * math.pi * cfg["grid"]["extent_radius_km"] ** 2 / 0.737 * 1.1)
    path =Path("configs/custom") / (f"{b['lat']:.5f}_{b['lon']:.5f}_{c['limit_miles']:g}_{c['hub_miles']:g}_"
                                     f"{c['band_step_miles']:g}_{'-'.join(cfg['highway_types'])}_"
                                     f"{cfg['min_corridor_cells']}.yaml")
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    with st.spinner(wait_msg):
        proc = subprocess.run([sys.executable, "-m", "zonegen", "run", str(path)], capture_output=True, text=True)
    if proc.returncode:
        st.sidebar.error(proc.stderr[-1500:])
        return
    st.session_state["run"] = Path(proc.stdout.strip().splitlines()[-1]).name
    if name.strip():
        (Path("runs") / st.session_state["run"] / "name.txt").write_text(name.strip())
    load.clear()


view_box = st.sidebar.container()  # filled further down, but drawn first: picking a location is the main job
with st.sidebar.expander("➕ Make zones for a new location"), st.form("new_run", border=False):
    st.markdown("**1. Where is the shop?**")
    name = st.text_input("Shop name (optional)", placeholder="e.g. Santa Rosa dealership",
                         help="The name dealers will pick from the location list.")
    where = st.text_input("Shop location", value="37.32305, -121.97000",
                          help="In Google Maps, right-click the shop and click the numbers at the top to copy them. "
                               "Paste them here. All miles are counted from this point.")
    st.markdown("**2. How far do the vans go?** (miles by road)")
    limit = st.number_input("Furthest distance served", 5.0, 80.0, 50.0, 5.0,
                            help="Places further than this by road are not served.")
    hub = st.number_input("Close-in area (zone 0)", 1.0, 40.0, 5.0, 1.0,
                          help="Everything this close to the shop is one zone, zone 0.")
    step = st.number_input("Size of each ring", 1.0, 50.0, 10.0, 1.0,
                           help="After zone 0, each ring is this many miles wide. Rings are numbered 1, 2, 3…")
    st.markdown("**3. Which highways give zones their letters?**",
                help="Each ticked highway becomes a zone letter (A, B, C…). Places off those highways join the "
                     "nearest one on their route, or get L for local roads.")
    highways = [code for label, code in HIGHWAYS.items() if st.checkbox(label, value=code == "I")]
    min_cells = st.slider("Join very small zones into a neighbour", 0, 200, 30, 10,
                          help="Zones smaller than this many map tiles are joined to the zone next to them. "
                               "0 keeps every zone, however small.")
    go = st.form_submit_button("Make zones", type="primary", width="stretch")
if go and not highways:
    st.sidebar.error("Tick at least one highway type in step 3.")
# snapshot.json is written only after the tiles finish building; the raw .pbf isn't needed once refs are cached
elif go and not (Path("data/valhalla_tiles").exists() and
               Path(load_config(Path("configs/stevens_creek.yaml"))["data"]["snapshot"]).exists()):
    st.sidebar.error("Map data is still downloading or building. Try again when it finishes.")
elif go:
    lat, lon = lookup.parse_coordinates(where) or (None, None)
    if lat is None:
        st.sidebar.error(f"Couldn't read '{where}'. Use 'latitude, longitude', e.g. 33.76908, -117.85139.")
    elif not in_boundary(boundary(), lat, lon):
        st.sidebar.error(f"{lat:.5f}, {lon:.5f} is outside the loaded map data (California).")
    elif hub >= limit:
        st.sidebar.error("Zone 0 must be smaller than the furthest distance.")
    else:
        cfg = yaml.safe_load(Path("configs/stevens_creek.yaml").read_text())
        cfg.update(label="custom", hard_cases=None)
        cfg["base"] = {"lat": lat, "lon": lon, "confirmed": False}
        cfg["coverage"].update(limit_miles=limit, hub_miles=hub, band_step_miles=step)
        cfg.update(highway_types=highways, min_corridor_cells=min_cells)
        make_run(cfg, name, f"Making zones for a new location (about {max(1, round(limit / 50 * limit / 50 * 2.5))} min)…")

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


def run_name(rid: str) -> str:
    f = Path("runs") / rid / "name.txt"
    return f.read_text().strip() if f.exists() else rid


def run_settings(rid: str) -> str:
    cfg = run_cfg(rid)
    if not cfg:
        return ""
    c = cfg["coverage"]
    types = "+".join(cfg.get("highway_types") or [])
    return f"up to {c['limit_miles']:g} mi · zone 0 = {c['hub_miles']:g} mi · rings of {c['band_step_miles']:g} mi" + \
        (f" · {types}" if types else "")


HW_NAMES = {code: label.split(" —")[0] for label, code in HIGHWAYS.items()}


def run_label(rid: str) -> str:
    """Shop name alone; settings, then the run id, are added only as needed to tell same-named runs apart."""
    name = run_name(rid)
    if sum(run_name(r) == name for r in runs) == 1:
        return name
    full = f"{name} ({run_settings(rid)})"
    twins = sum(f"{run_name(r)} ({run_settings(r)})" == full for r in runs) > 1
    return f"{full} · {rid}" if twins else full


def band_labels(limit: float, hub: float, step: float, unit: str) -> list[str]:
    """Legend text from the same band edges the classifier uses."""
    edges = [0, *band_edges(hub, step, limit), limit]
    return [f"{a:g}–{b:g} {unit}" + (" (Hub)" if i == 0 else "") for i, (a, b) in enumerate(zip(edges, edges[1:]))]


def mode_bands(rid: str) -> list[str]:
    """Legend labels for the band view picked in the sidebar: index is the band number."""
    cfg = run_cfg(rid) or {"coverage": {"limit_miles": 50, "hub_miles": 5, "band_step_miles": 10},
                           "time_view": {"limit_minutes": 60, "hub_minutes": 15, "band_step_minutes": 15}}
    c, t = cfg["coverage"], cfg["time_view"]
    return (band_labels(c["limit_miles"], c["hub_miles"], c["band_step_miles"], "mi") if mode == "Road-mile bands"
            else band_labels(t["limit_minutes"], t["hub_minutes"], t["band_step_minutes"], "min"))


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


ZONES, CORRIDORS = "Zones (band + corridor)", "Corridors (highway)"
MODE_NAMES = {ZONES: "Zones (like 2A)", CORRIDORS: "Highways only", "Road-mile bands": "Distance rings (miles)",
              "Free-flow minute bands": "Drive-time rings (no traffic)"}
with view_box:
    st.subheader("📍 Pick your location")
    # one entry per shop name; each name's runs keyed by (highway mix, limit, hub, ring, merge), newest wins
    def run_key(r: str) -> tuple:
        cfg = run_cfg(r) or {}
        c = cfg.get("coverage") or {"limit_miles": 50, "hub_miles": 5, "band_step_miles": 10}
        return (frozenset(cfg.get("highway_types") or []), float(c["limit_miles"]), float(c["hub_miles"]),
                float(c["band_step_miles"]), int(cfg.get("min_corridor_cells", 0)))

    shops = defaultdict(dict)
    for r in runs:
        shops[run_name(r)][run_key(r)] = r
    if default not in runs:
        default = runs[-1]
    names = list(shops)
    shop = st.selectbox("Location", names, index=names.index(run_name(default)), label_visibility="collapsed")
    variants = shops[shop]
    start = next((k for k, r in variants.items() if r == default), list(variants)[-1])
    st.markdown("**Highways that give zones their letters**",
                help="Tick the highway types to use. The map shows the zones made with exactly that mix.")
    ticked = frozenset(code for label, code in HIGHWAYS.items()
                       if st.checkbox(label, value=code in start[0], key=f"hw_{shop}_{code}"))
    st.markdown("**How far do the vans go?** (miles by road)",
                help="Change any number and the zones are remade. Small changes take a few seconds; "
                     "a bigger furthest distance takes a few minutes, because new roads must be driven.")
    want = (ticked,
            st.number_input("Furthest distance served", 5.0, 80.0, start[1], 5.0, key=f"lim_{shop}",
                            help="Places further than this by road are not served."),
            st.number_input("Close-in area (zone 0)", 1.0, 40.0, start[2], 1.0, key=f"hub_{shop}",
                            help="Everything this close to the shop is one zone, zone 0."),
            st.number_input("Size of each ring", 1.0, 50.0, start[3], 1.0, key=f"step_{shop}",
                            help="After zone 0, each ring is this many miles wide. Rings are numbered 1, 2, 3…"),
            st.slider("Join very small zones into a neighbour", 0, 200, start[4], 10, key=f"merge_{shop}",
                      help="Zones smaller than this many map tiles are joined to the zone next to them. "
                           "0 keeps every zone, however small."))
    empty = want not in variants
    run = variants.get(want, variants[start])  # empty: keep the page and base point, draw no zones
    if empty and want[2] >= want[1]:
        st.info("Zone 0 must be smaller than the furthest distance.")
    elif empty and ticked:
        # same shop, new settings: routes are cached per base, so usually only the labelling is redone
        try:
            cfg = yaml.safe_load(Path(json.loads((Path("runs") / run / "run_meta.json").read_text())["config"])
                                 .read_text())
        except (OSError, KeyError, ValueError):
            cfg = None
        if cfg:
            cfg.update(label="custom", hard_cases=None, min_corridor_cells=want[4],
                       highway_types=[c for c in HIGHWAYS.values() if c in ticked])
            cfg["coverage"].update(limit_miles=want[1], hub_miles=want[2], band_step_miles=want[3])
            far = want[1] > start[1]
            make_run(cfg, shop, "Driving the new, further roads (a few minutes)…" if far else "Making zones…")
            if st.session_state.get("run") not in runs:
                st.rerun()  # the new run is now on disk: redraw with it selected
        else:
            st.warning("Couldn't make zones for this mix: this location's settings file is missing.")
    elif empty:
        st.info("Tick at least one highway type to see zones.")
    else:
        st.caption(run_settings(run))
    mode = st.radio("What the colours show", list(MODE_NAMES), format_func=MODE_NAMES.get,
                    help="**Zones:** number = how far (ring), letter = which highway. 2A = ring 2 on highway A.  \n"
                         "**Highways only:** one colour per highway.  \n"
                         "**Distance rings:** green is close, red is far.  \n"
                         "**Drive-time rings:** same idea in minutes, with no traffic.")
    by_corridor = mode in (ZONES, CORRIDORS)
    focus = None
    if mode == ZONES:
        focus = st.selectbox("Look at one zone", ["All zones", *([] if empty else zone_codes(run))],
                             help="Pick a zone to fade out all the others.")
        focus = None if focus == "All zones" else focus
    opacity = st.slider("Colour strength", 10, 100, 70, 5, format="%d%%",
                        help="Lower it to see the streets and town names under the colours.") / 100
    with st.expander("More options"):
        compare = st.multiselect("Compare with other locations", [r for r in runs if r != run],
                                 format_func=run_label, max_selections=2,
                                 help="Shows up to two other locations side by side in the 'Compare branches' tab.")
        show_unknown = st.checkbox("Show unsure tiles", value=True,
                                   help="Faint tiles where the answer wasn't clear. A person should check them.")
        show_noroad = st.checkbox("Show tiles with no road", value=False,
                                  help="Grey tiles with no usable road: water, parks, farm tracks, or no map data.")
        show_out = st.checkbox("Show tiles too far away", value=False,
                               help="Pale tiles past the furthest distance, or that no road reaches.")
meta, cells, base = load(run)
if empty:
    cells = []
st.session_state.setdefault("addresses", [])
st.session_state.setdefault("view_nonce", 0)

st.title("RoadZone")


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

    last_band = None if by_corridor else len(mode_bands(run)) - 1
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
            rgb = band_colour(b, last_band) if b is not None else GREY
        # pydeck can't hatch: uncertain cells are drawn faint instead
        row = {k: ("" if c.get(k) is None else c[k]) for k in TIP_FIELDS}  # only what the map needs: big runs stay fast
        dim = focus and c.get("zone_code") != focus
        row["fill"] = [*rgb, int((28 if dim else 70 if uncertain else 255) * opacity)]
        row["patch"] = "isolated patch" if by_corridor and not dim and c["h3"] in solid and isolated(c["h3"]) else ""
        rows.append(row)
    zone_layers = []
    if mode == ZONES and cells:
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
    tooltip = {"text": "Zone {zone_code}\n{m_dist_mi} road miles · {m_time_min} min with no traffic\n"
                       "Highway: {family_key}\n{patch}"}
    return pdk.Deck(layers=[*map_layers(cells, run), base_layer], tooltip=tooltip, map_style="light",
                    initial_view_state=pdk.ViewState(latitude=base[1], longitude=base[0], zoom=zoom))


DIRS = {"N": "north", "S": "south", "E": "east", "W": "west"}


def road_name(key) -> str:
    """'I 15 | N' -> 'I-15 north': the legend is read by dealers, not engineers."""
    parts = [p.strip() for p in str(key).split("|")]
    road = re.sub(r"^(I|US|CA|SR) (\S+)", r"\1-\2", parts[0])
    return " ".join([road, *(DIRS.get(p, p) for p in parts[1:])]).strip()


tab_map, tab_addr, tab_cmp = st.tabs(["Map", "Check an address", "Compare locations"])

with tab_map:
    if st.button("⌖ Back to the shop", help="Move the map back to the shop after you've dragged or zoomed it."):
        st.session_state["view_nonce"] += 1
    # Streamlit keeps a panned view across reruns; a new container key per click remounts the map at the base
    with st.container(key=f"map{st.session_state['view_nonce']}"):
        st.pydeck_chart(deck(cells, base, run), height=520)
    # legend scrolls in its own box so the map stays on screen while reading it
    with st.container(height=320):
        corridors, ccol = corridor_colours(cells)
        st.subheader("Legend")
        if by_corridor:
            fams, bands = {}, defaultdict(set)
            for c in cells:
                if c.get("display_corridor_id") and c.get("family_key") and c.get("hatch_status") != "hatched":
                    fams.setdefault(c["display_corridor_id"], c.get("merged_into") or c["family_key"])
                if c.get("zone_code") and c.get("band"):
                    bands[c["display_corridor_id"]].add(c["band"])
            size = Counter(c.get("display_corridor_id") for c in cells if c.get("hatch_status") != "hatched")
            small = [cid for cid in corridors if cid not in ("HUB", "L") and size[cid] < MIN_LEGEND_CELLS]
            for cid in corridors:
                if cid in small:
                    continue  # display only: tiny corridors keep their letter on the map and in the tooltip
                label = "Hub (zone 0)" if cid == "HUB" else "Local roads" if cid == "L" else f"{cid}: {road_name(fams.get(cid, ''))}"
                if mode == ZONES and cid != "HUB":
                    sw = " ".join(f"<span style='color:rgb{shade(ccol[cid], b)}'>■</span>{b}{cid}"
                                  for b in sorted(bands[cid]))
                    st.markdown(f"{sw} · {html.escape(label)}", unsafe_allow_html=True)
                else:
                    st.markdown(f"<span style='color:rgb{ccol[cid]}'>■</span> {html.escape(label)}",
                                unsafe_allow_html=True)
            if small:
                st.caption(f"Plus {len(small)} very small highway zones: "
                           + ", ".join(f"{cid} ({road_name(fams.get(cid, '?'))})" for cid in small))
        else:
            labels = mode_bands(run)
            for i, lab in enumerate(labels):
                st.markdown(f"<span style='color:rgb{band_colour(i, len(labels) - 1)}'>■</span> Ring {i}: {lab}",
                            unsafe_allow_html=True)
        st.caption("Faint tiles = not sure, a person should check them. Red pins = addresses you checked.")
        if by_corridor:
            st.caption("Black outline = a small spot reached by a different highway than the tiles around it.")

with tab_addr:
    st.subheader("Which zone is an address in?")
    st.caption("Type one address per line, or paste coordinates from Google Maps (e.g. `37.3230, -121.9700`). "
               "Typed addresses are looked up on OpenStreetMap, an outside website; coordinates stay here.")
    text = st.text_area("Addresses", placeholder="37.4419, -122.1430\n1 Infinite Loop, Cupertino, CA", height=120)
    go_check, go_clear = st.columns([1, 6])
    if go_clear.button("Clear"):
        st.session_state["addresses"] = []
    if go_check.button("Check", type="primary"):
        branches = [run, *compare]
        found = []
        with st.spinner("Checking…"):
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
        st.markdown(f"**{html.escape(a['label'])}**  \n`{a['lat']:.5f}, {a['lon']:.5f}`")
        covered = {b: r for b, r in a["results"].items() if r.get("zone")}
        best = min(covered, key=lambda b: covered[b]["miles"]) if covered else None
        st.table([{"location": ("⭐ " if b == best else "") + run_label(b),
                   "zone": r.get("zone") or NO_ZONE.get(r.get("status"), "Not sure"),
                   "road miles": f"{r['miles']:.1f}" if r.get("miles") is not None else "-",
                   "minutes (no traffic)": r.get("minutes") if r.get("minutes") is not None else "-",
                   "needs a check": "yes" if r.get("review") or not (r.get("zone") or r.get("status") in NO_ZONE) else ""}
                  for b, r in a["results"].items()])
    if st.session_state["addresses"]:
        st.caption("⭐ = the closest location by road. 'Needs a check' means a person should confirm it.")

with tab_cmp:
    branches = [run, *compare]
    if not compare:
        st.info("To compare, open **More options** in the sidebar and pick up to two other locations.")
    cols = st.columns(len(branches))
    for col, b in zip(cols, branches):
        with col:
            st.caption(run_label(b))
            st.pydeck_chart(deck(load(b)[1], load(b)[2], b, zoom=7.8), height=420)


st.divider()
st.subheader("How the zones are made")
st.markdown("""
1. **We cut the map into small hexagon tiles.** Each tile is about a quarter of a square mile.
2. **We drive to each tile on real roads.** The computer finds the road route from your shop to the tile
   and back again. We use the longer of the two trips.
3. **We count the miles.** This is road miles, not a straight line on the map. Traffic is not counted.
4. **The number is how far away it is.**
   - **0** is the hub, the area closest to your shop.
   - **1, 2, 3…** are rings that get further away. Each ring is the ring size you chose (for example 10 miles).
5. **The letter is the main highway the van uses to get there.**
   - Each highway gets its own letter, going clockwise around your shop: A, B, C…
   - **L** means only small local roads, no big highway.
   - Two letters, like **2AB**, means you go on highway A first, then turn onto road B.
   - Very small highway areas are joined into their neighbour so you don't get tiny zones.
6. **So "2A" means:** the second ring of distance, reached by highway A.

**What the colours mean**
- Each highway has its own colour. The colour gets **darker** the further away you go on that highway.
- **Dark grey** in the middle is the hub.
- **Light grey** means no road we can use (water, parks, or no map data). We don't serve it.
- **Very pale** tiles are too far away, or no road reaches them.
- **See-through (faint)** tiles are not sure. A person should check them.
- **Black outline** means a small spot reached by a different highway than the tiles around it.
- **Red pins** are addresses you checked.
""")
