#!/usr/bin/env bash
# One-off repair for a Pi whose app directory was copied rather than cloned: attach it to the GitHub repo so
# deploy/update.sh (and the CI runner) can fetch + reset, install deno for yt-dlp, deploy the current main, and
# requeue a song that failed. Safe to re-run. Runs as dani, no sudo needed beyond the sudoers rule for the restarts.
#
#   From your PC (in the LAN):  ssh dani@192.168.1.30 'bash -s' < deploy/pi-attach-git.sh
#   Or on the Pi:               bash ~/Karaoke-Rodeo/deploy/pi-attach-git.sh
set -euo pipefail
APP_DIR="${KARAOKE_APP_DIR:-$HOME/Karaoke-Rodeo}"
REPO="${KARAOKE_REPO:-https://github.com/CreeperBeatz/Karaoke-Rodeo.git}"
REQUEUE="${1:-BkoguS4_5Y8}"          # song id to requeue after the deploy ("" to skip)
cd "$APP_DIR"

echo "== attach to git =="
if [ ! -d .git ]; then
  git init -q
  git remote add origin "$REPO"
else
  git remote set-url origin "$REPO"
fi
git fetch -q origin main
# tracked files become exactly origin/main; data/, .env and .venv are untracked/ignored and stay as they are
git reset -q --hard origin/main
git branch -q -M main 2>/dev/null || true
git branch -q --set-upstream-to=origin/main main 2>/dev/null || true
echo "at $(git rev-parse --short HEAD): $(git log -1 --format=%s)"

echo "== deno (JS runtime for yt-dlp) =="
if [ ! -x "$HOME/.deno/bin/deno" ] && ! command -v deno >/dev/null; then
  curl -fsSL https://deno.land/install.sh | DENO_INSTALL="$HOME/.deno" sh -s -- -y >/dev/null
fi
"$HOME/.deno/bin/deno" --version 2>/dev/null | head -1 || deno --version | head -1

echo "== deploy =="
bash deploy/update.sh

if [ -n "$REQUEUE" ]; then
  echo "== requeue $REQUEUE from the download stage =="
  .venv/bin/python - "$REQUEUE" <<'PY'
import sys, sqlite3, os
sys.path.insert(0, os.getcwd())
from server import config
from server.db import now
sid = sys.argv[1]
c = sqlite3.connect(config.DB_PATH, isolation_level=None)
if c.execute("SELECT 1 FROM songs WHERE id=?", (sid,)).fetchone() is None:
    print("no such song", sid); sys.exit(0)
if c.execute("SELECT 1 FROM jobs WHERE song_id=? AND status IN ('queued','running')", (sid,)).fetchone():
    print("already queued/running"); sys.exit(0)
c.execute("INSERT INTO jobs(song_id,kind,status,created_at) VALUES(?,?,?,?)", (sid, "ingest", "queued", now()))
c.execute("UPDATE songs SET status='processing' WHERE id=?", (sid,))
print("queued ingest job for", sid)
PY
fi

echo "== done =="
systemctl --no-pager is-active karaoke-web karaoke-worker
