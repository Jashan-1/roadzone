#!/usr/bin/env bash
# One-time setup on an Ubuntu 24.04 server (x86 or ARM), run from the unzipped roadzone folder:
#   ./deploy/setup.sh
# Installs deps, points Valhalla at this folder, adds 2 GB swap, and runs the app on port 8501 as a service.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/0.5.11/install.sh | sh; }
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
"$UV" sync --frozen --no-dev
# valhalla.json was written on the build machine with absolute paths
python3 - "$PWD" <<'PY'
import json, sys; p = "data/valhalla.json"; root = sys.argv[1]
c = json.load(open(p)); m = c["mjolnir"]
m["tile_dir"], m["admin"] = f"{root}/data/valhalla_tiles", f"{root}/data/admins.sqlite"
json.dump(c, open(p, "w"), indent=2)
PY
if ! swapon --show | grep -q .; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi
sudo tee /etc/systemd/system/roadzone.service >/dev/null <<UNIT
[Unit]
Description=RoadZone viewer
After=network-online.target
[Service]
User=$USER
WorkingDirectory=$PWD
ExecStart=$PWD/.venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now roadzone
sleep 5 && curl -fsS -o /dev/null http://localhost:8501 && echo "RoadZone is up: http://<this server's public IP>:8501"
