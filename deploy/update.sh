#!/usr/bin/env bash
# Pull the latest main and restart services. Called by the CI/CD workflow (self-hosted runner on the Pi)
# and safe to run by hand:  bash deploy/update.sh
set -euo pipefail
APP_DIR="${KARAOKE_APP_DIR:-/home/dani/Karaoke-Rodeo}"
cd "$APP_DIR"

echo "== fetch =="
git fetch --all --quiet
git reset --hard origin/main

echo "== deps =="
.venv/bin/pip install -q -r requirements.txt

echo "== restart services =="
sudo systemctl restart karaoke-web karaoke-worker

sleep 3
systemctl is-active karaoke-web karaoke-worker
echo "deployed $(git rev-parse --short HEAD) at $(date -Is)"
