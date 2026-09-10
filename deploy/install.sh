#!/usr/bin/env bash
# karaoke.rodeo — Raspberry Pi 4 (Raspberry Pi OS 64-bit / Debian bookworm) install.
# Run as the user that will own the app (e.g. `pi`):   bash deploy/install.sh
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${KARAOKE_DATA:-/srv/karaoke/data}"
USER_NAME="$(id -un)"

echo "== apt packages (python, ffmpeg, OpenCV runtime libs) =="
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip ffmpeg libatlas-base-dev libopenblas0 libgl1 libglib2.0-0

echo "== python venv =="
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "== data dir $DATA_DIR =="
sudo mkdir -p "$DATA_DIR"
sudo chown -R "$USER_NAME":"$USER_NAME" "$DATA_DIR"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  sed -i "s#^BASE_URL=.*#BASE_URL=https://karaoke.rodeo#; s#^HOST=.*#HOST=127.0.0.1#" "$APP_DIR/.env"
  printf '\nKARAOKE_DATA=%s\nKARAOKE_WORKERS=3\n' "$DATA_DIR" >> "$APP_DIR/.env"
  echo ">> edit $APP_DIR/.env : RESEND_API_KEY, ADMIN_EMAILS"
fi

echo "== systemd units =="
for unit in karaoke-web karaoke-worker; do
  sed "s#__APP_DIR__#$APP_DIR#g; s#__USER__#$USER_NAME#g" "$APP_DIR/deploy/$unit.service" | sudo tee "/etc/systemd/system/$unit.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now karaoke-web karaoke-worker
sleep 2
systemctl --no-pager --lines=5 status karaoke-web karaoke-worker || true

cat <<EOF

Done.
  web:    http://127.0.0.1:8765/   (exposed through cloudflared, see deploy/README.md)
  logs:   journalctl -u karaoke-web -f      journalctl -u karaoke-worker -f
  import the PoC songs once the data is copied:  $APP_DIR/.venv/bin/python tools/import_poc.py --publish
EOF
