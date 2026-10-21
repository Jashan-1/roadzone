"""uv run python -m zonegen {build-tiles,run} configs/stevens_creek.yaml"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import osmium
import valhalla

from .pipeline import load_config, run


def build_tiles(cfg_path: Path):
    cfg = load_config(cfg_path)
    d = cfg["data"]
    pbf, tiles = Path(d["pbf"]), Path(d["valhalla_config"]).parent / "valhalla_tiles"
    tiles.mkdir(parents=True, exist_ok=True)
    vcfg = valhalla.get_config(tile_extract="", tile_dir=tiles)
    vcfg["mjolnir"]["admin"] = str((tiles.parent / "admins.sqlite").resolve())
    vcfg["mjolnir"]["concurrency"] = os.cpu_count()
    if d.get("default_speeds"):  # OpenStreetMapSpeeds typical speeds by region, density and road class
        vcfg["mjolnir"]["default_speeds_config"] = str(Path(d["default_speeds"]).resolve())
    Path(d["valhalla_config"]).write_text(json.dumps(vcfg, indent=2))
    for tool in ("valhalla_build_admins", "valhalla_build_tiles"):
        subprocess.run([sys.executable, "-m", "valhalla", tool, "-c", d["valhalla_config"], str(pbf)], check=True)
    # written only after the tiles exist, so snapshot.json always describes the graph actually built
    sha = hashlib.sha256()
    with pbf.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
    snap_path = Path(d["snapshot"])
    snap = {"pbf": pbf.name, "sha256": sha.hexdigest()}
    snap["osm_timestamp"] = osmium.io.Reader(str(pbf), osmium.osm.osm_entity_bits.NOTHING).header() \
        .get("osmosis_replication_timestamp")
    snap["router"] = "pyvalhalla " + valhalla.__version__
    if d.get("default_speeds"):
        speeds = Path(d["default_speeds"])
        snap["default_speeds"] = {"file": speeds.name, "source": d.get("default_speeds_source"),
                                  "sha256": hashlib.sha256(speeds.read_bytes()).hexdigest()}
    snap_path.write_text(json.dumps(snap, indent=2))
    print(json.dumps(snap, indent=2))


def main():
    ap = argparse.ArgumentParser(prog="zonegen")
    ap.add_argument("command", choices=["build-tiles", "run"])
    ap.add_argument("config", type=Path)
    ap.add_argument("--fresh", action="store_true", help="discard the probe ledger and start over")
    ap.add_argument("--max-probes", type=int, help="smoke test: evaluate only the nearest N cells")
    a = ap.parse_args()
    if a.command == "build-tiles":
        build_tiles(a.config)
    else:
        print(run(a.config, fresh=a.fresh, max_probes=a.max_probes))


if __name__ == "__main__":
    main()
