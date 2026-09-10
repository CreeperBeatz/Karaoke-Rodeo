#!/usr/bin/env bash
# One-shot finalize of the karaoke.rodeo Pi: systemd services, Cloudflare Tunnel, and the CI/CD runner.
# Run as the app user (dani), NOT with sudo — it calls sudo itself where needed (you'll be asked for your
# password once). Tokens are passed as environment variables so they never sit in the shell history / argv.
#
#   cd ~/Karaoke-Rodeo
#   # everything at once:
#   CF_TUNNEL_TOKEN=eyJ... GH_RUNNER_TOKEN=ABC... bash deploy/pi-setup.sh
#   # or in stages — services only, then the tunnel, then the runner:
#   bash deploy/pi-setup.sh
#   CF_TUNNEL_TOKEN=eyJ... bash deploy/pi-setup.sh
#   GH_RUNNER_TOKEN=ABC... bash deploy/pi-setup.sh
#
# Get the tokens from:
#   CF_TUNNEL_TOKEN  Cloudflare Zero Trust -> Networks -> Tunnels -> (create/select) -> the connector token
#   GH_RUNNER_TOKEN  https://github.com/CreeperBeatz/Karaoke-Rodeo/settings/actions/runners/new  (the --token value)
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"
REPO_URL="${REPO_URL:-https://github.com/CreeperBeatz/Karaoke-Rodeo}"
ARCH="$(dpkg --print-architecture)"   # arm64 on a 64-bit Pi
cd "$APP_DIR"

# Tokens may be passed as env vars OR pre-placed as files (~/.cftoken, ~/.ghrunner) so they never sit in argv.
CF_TUNNEL_TOKEN="${CF_TUNNEL_TOKEN:-$( [ -f "$HOME/.cftoken" ] && cat "$HOME/.cftoken" || true )}"
GH_RUNNER_TOKEN="${GH_RUNNER_TOKEN:-$( [ -f "$HOME/.ghrunner" ] && cat "$HOME/.ghrunner" || true )}"

echo "== 0/5  stop any interim (nohup) processes so systemd can take over the port/tunnel =="
for pat in 'python -m server' 'worker.py' 'cloudflared tunnel run'; do
  for pid in $(pgrep -f "$pat" || true); do kill "$pid" 2>/dev/null || true; done
done
sleep 2

echo "== 1/5  systemd services =="
for u in karaoke-web karaoke-worker; do
  sed "s#__APP_DIR__#$APP_DIR#g; s#__USER__#$USER_NAME#g" "deploy/$u.service" | sudo tee "/etc/systemd/system/$u.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now karaoke-web karaoke-worker

echo "== 2/5  passwordless restart for CI (narrow sudoers rule) =="
echo "$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl restart karaoke-web karaoke-worker, /usr/bin/systemctl restart karaoke-web, /usr/bin/systemctl restart karaoke-worker" \
  | sudo tee /etc/sudoers.d/karaoke-ci >/dev/null
sudo chmod 440 /etc/sudoers.d/karaoke-ci
sudo visudo -cf /etc/sudoers.d/karaoke-ci

echo "== 3/5  production .env values (keep your RESEND key) =="
sed -i 's#^BASE_URL=.*#BASE_URL=https://karaoke.rodeo#; s#^HOST=.*#HOST=127.0.0.1#; s#^DEV_MODE=.*#DEV_MODE=0#' .env
grep -q '^RESEND_API_KEY=.\+' .env || echo "  !! RESEND_API_KEY is empty in .env — magic-link emails will NOT send until you set it."
sudo systemctl restart karaoke-web karaoke-worker

echo "== 4/5  Cloudflare Tunnel (systemd service) =="
if [ -n "$CF_TUNNEL_TOKEN" ]; then
  if ! command -v cloudflared >/dev/null; then
    if [ -x "$HOME/cloudflared" ]; then           # reuse the standalone binary if it's already here
      sudo install -m 0755 "$HOME/cloudflared" /usr/local/bin/cloudflared
    else
      tmp=$(mktemp); curl -fsSL -o "$tmp" "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
      sudo dpkg -i "$tmp"; rm -f "$tmp"
    fi
  fi
  sudo cloudflared service install "$CF_TUNNEL_TOKEN"   # installs + enables + starts the cloudflared systemd unit
  echo "  cloudflared service installed. Ensure the tunnel's Public Hostname is karaoke.rodeo ->"
  echo "  Service type HTTP, URL 127.0.0.1:8765 (NOT https)."
else
  echo "  skipped (no CF token in env or ~/.cftoken)."
fi

echo "== 5/5  GitHub Actions self-hosted runner =="
if [ -n "$GH_RUNNER_TOKEN" ]; then
  mkdir -p "$HOME/actions-runner" && cd "$HOME/actions-runner"
  if [ ! -f ./config.sh ]; then
    RUNNER_VER=$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | grep -oP '"tag_name": "v\K[^"]+')
    curl -fsSL -o runner.tgz "https://github.com/actions/runner/releases/download/v${RUNNER_VER}/actions-runner-linux-${ARCH}-${RUNNER_VER}.tar.gz"
    tar xzf runner.tgz && rm runner.tgz
  fi
  ./config.sh --url "$REPO_URL" --token "$GH_RUNNER_TOKEN" --labels karaoke --name pi --unattended --replace
  sudo ./svc.sh install "$USER_NAME"
  sudo ./svc.sh start
  cd "$APP_DIR"
else
  echo "  skipped (no GH_RUNNER_TOKEN). Re-run with it set to enable CI/CD."
fi

echo
echo "== done =="
systemctl is-active karaoke-web karaoke-worker cloudflared 2>/dev/null || true
echo "web:    journalctl -u karaoke-web -f"
echo "worker: journalctl -u karaoke-worker -f"
