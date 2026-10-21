"""Run the pipeline at fixed California test bases (40 mi, hub 5, bands 10) and name each run.

Usage (from the repo root): uv run python -m scripts.sweep   -> prints one run directory per site
"""
import math
import subprocess
import sys
from pathlib import Path

import yaml

from zonegen.pipeline import MAX_CALLS_PER_PROBE

SITES = {
    "LA downtown (dense freeway grid)": (34.0407, -118.2468),
    "San Diego (coast + border)": (32.7157, -117.1611),
    "Fresno (flat valley grid)": (36.7378, -119.7871),
    "Sacramento (river + freeway hub)": (38.5816, -121.4944),
    "Redding (rural, few highways)": (40.5865, -122.3917),
    "South Lake Tahoe (mountains + NV border)": (38.9399, -119.9772),
    "San Francisco (peninsula + bridges)": (37.7749, -122.4194),
}
LIMIT, HUB, STEP = 40, 5, 10

base = yaml.safe_load(Path("configs/stevens_creek.yaml").read_text())
for name, (lat, lon) in SITES.items():
    cfg = {**base, "label": "custom", "hard_cases": None, "base": {"lat": lat, "lon": lon, "confirmed": False}}
    cfg["coverage"] = {**base["coverage"], "limit_miles": LIMIT, "hub_miles": HUB, "band_step_miles": STEP}
    cfg["grid"] = {**base["grid"], "extent_radius_km": round(LIMIT * 1.609344 + 2, 1)}
    cfg["request_budget"] = int(MAX_CALLS_PER_PROBE * math.pi * cfg["grid"]["extent_radius_km"] ** 2 / 0.737 * 1.1)
    path = Path("configs/custom") / f"{lat:.5f}_{lon:.5f}_{LIMIT}_{HUB}_{STEP}.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    out = subprocess.run([sys.executable, "-m", "zonegen", "run", str(path)], capture_output=True, text=True)
    if out.returncode:
        print("FAIL", name, out.stderr[-800:], flush=True)
        continue
    run_dir = Path(out.stdout.strip().splitlines()[-1])
    (run_dir / "name.txt").write_text(f"Test: {name}")
    print("OK", name, run_dir, flush=True)
