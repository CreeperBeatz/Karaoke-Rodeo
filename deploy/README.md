# Deploying karaoke.rodeo on the Raspberry Pi 4

## 0. Before the Pi: DNS + mail (5 minutes)

1. **Cloudflare**: add the `karaoke.rodeo` zone, point the registrar's nameservers at Cloudflare.
2. **Resend**: Domains → add `karaoke.rodeo` → copy the DKIM (`resend._domainkey` TXT), SPF (`send` MX + TXT) and DMARC
   records into Cloudflare DNS → wait for "Verified". Create an API key (Sending access) → `RESEND_API_KEY` in `.env`.
   Sender: `no-reply@karaoke.rodeo` (`MAIL_FROM` in `.env`).

## 1. Pi OS + app

Raspberry Pi OS **64-bit** (Lite is fine), on an SSD or a fast SD card — the videos are ~50 MB each at 720p and the
pipeline decodes them several times. Then:

```bash
git clone <this repo> ~/karaoke && cd ~/karaoke        # or rsync the folder (without data/ and *.mp4)
bash deploy/install.sh                                   # apt + venv + systemd units (karaoke-web, karaoke-worker)
nano .env                                                # RESEND_API_KEY, ADMIN_EMAILS=you@…, BASE_URL=https://karaoke.rodeo
sudo systemctl restart karaoke-web karaoke-worker
```

Bring the existing songs over: copy `data/` from the dev machine (`data/songs/*/video.mp4`, `data/maps`, `data/cache`)
to `/srv/karaoke/data`, or copy just `output/song_map_v*.json` + the five mp4s and run
`.venv/bin/python tools/import_poc.py --publish`. The DB (`app.db`) can be copied too if you want to keep dev accounts.

## 2. Cloudflare Tunnel (no port forwarding)

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o cf.deb && sudo dpkg -i cf.deb
cloudflared tunnel login                     # opens a browser URL; pick the karaoke.rodeo zone
cloudflared tunnel create karaoke
cloudflared tunnel route dns karaoke karaoke.rodeo
sudo mkdir -p /etc/cloudflared && sudo tee /etc/cloudflared/config.yml >/dev/null <<EOF
tunnel: karaoke
credentials-file: /home/$USER/.cloudflared/$(ls ~/.cloudflared/*.json | xargs -n1 basename | head -1)
ingress:
  - hostname: karaoke.rodeo
    service: http://127.0.0.1:8765
    originRequest: { noTLSVerify: true, connectTimeout: 30s }
  - service: http_status:404
EOF
sudo cloudflared service install && sudo systemctl enable --now cloudflared
```

Cloudflare terminates TLS; uvicorn runs with `proxy_headers` so `cf-connecting-ip` / `x-forwarded-for` feed the
login rate limiter. The media route streams mp4s with Range requests through the tunnel; the free plan's 100 MB
per-request limit is not hit because browsers request ranges.

Optional: Cloudflare Zero Trust → Access application on `karaoke.rodeo/admin*` for a second factor on the admin pages.

## 3. Day-to-day

| task | how |
|---|---|
| add a song | `/admin` → paste the YouTube URL → wait for ★ラベリングできます (30–60 min on the Pi) → ラベラー → 公開 |
| watch the worker | `journalctl -u karaoke-worker -f`, or the ログ button in `/admin` |
| update the app | `git pull && .venv/bin/pip install -r requirements.txt && sudo systemctl restart karaoke-web karaoke-worker` |
| backup | `/srv/karaoke/data/app.db` (sqlite, `sqlite3 app.db ".backup b.db"`), `data/maps`, `data/avatars` |
| processing too slow / OOM | set `KARAOKE_WORKERS=2` in `.env`; the worker restarts stuck-as-running jobs on boot |
