# karaoke.rodeo — app spec (2026-09-07)

Real app built on the PoC (`pipeline/`, `app/`). Decisions taken with dani on 2026-09-07:

| topic | decision |
|---|---|
| playback | serve the downloaded mp4 from the Pi (720p), **login-gated** (`/media/<song>`); never public |
| hosting | Raspberry Pi 4 (4 GB) behind a Cloudflare Tunnel, domain karaoke.rodeo. Deploy later; develop on Windows now |
| auth | magic link by email, from `no-reply@karaoke.rodeo` via Resend. Session cookie, 90 days |
| audience | solo practice at home (primary). Party mode: host screen shows a QR, players scan to join as themselves or as a **guest** (nickname only, zero friction) |
| party mode | an **app-level mode**, not a play-page feature (dani, 2026-09-07): started only from the home page, then a strip under the header carries it (code, seats, who has the mic, QR, end) on every page; off = no party UI anywhere. Each seat gets a colour from a fixed palette in join order, and the live pitch line on the play page is drawn in the current singer's colour |
| joining a party | the phone page offers exactly two ways in: **アカウントで参加** (email → magic link requested inline, no navigation, the link returns to the party page and seats them) or **ゲストで参加** (nickname only). A visitor already logged in is seated with no prompt at all |
| language | Japanese only, English as hover tooltips. A full EN i18n layer was considered on 2026-09-07 and **dropped** |
| stack | FastAPI + SQLite (WAL) + vanilla JS ES modules, no bundler. One Python runtime for web + pipeline |
| ranking | two views, built to survive a 100+ song catalogue: **総合** (average of per-song bests) and **曲別**, where the song is found through a search box over the catalogue rather than one tab per song |
| stats | per-song best + history, score trend per song, pitch accuracy by note (sharp/flat), weak sections (pages) per song, practice streaks + calendar, per-song and overall leaderboards |
| ingestion | **admin only**: paste a カラオケ@DIVA YouTube URL → queued job → download → extract → geotime → anchor → lyrics → status `labeling` in the admin dashboard → label in the built-in tool → publish |

## Processing on the Pi: yes, as a background queue

The pipeline is decode + OpenCV morphology, nothing arithmetic-bound (GPU measured useless on the desktop).
Desktop timings: geotime scan 28 s (6 workers) + build 50 s; extract pass 1 a few minutes. A Pi 4 is ~6–8× slower
per core with 4 cores, so expect **30–60 min per song**, which is fine for "paste URL, get told when it's ready".
Rules: one job at a time, `nice 10`, `KARAOKE_WORKERS=3`, download at ≤720p (the pipeline normalizes to 720p
anyway and 720p was its primary target). The worker is a separate process (`worker.py`) sharing the SQLite DB,
so it can be stopped/restarted without touching the web server. Labeling on the Pi is cheap (single-frame seeks).

## Layout

```
server/            FastAPI package (config, db, auth, mail, routers, jobs)
worker.py          job runner (download + pipeline stages as subprocesses)
pipeline/          PoC extraction code, made portable via pipeline/paths.py (env KARAOKE_DATA)
web/               static front end: index (catalog), play, stats, leaderboard, profile, party, admin, label, login
data/              runtime state (gitignored): app.db, songs/<id>/video.mp4, maps/song_map_<id>.json, cache/, avatars/
deploy/            Pi install script, systemd units, cloudflared + Resend DNS notes
tools/import_poc.py  imports the 5 PoC songs (output/*.json + local mp4s) into data/
```

## Data model (SQLite)

users, login_tokens, sessions, songs (status: processing | labeling | published | failed | hidden), jobs (stage,
status, progress, log), plays (score, counts, max_combo, per-note results JSON), parties, party_members
(user or guest). Global leaderboard ranks registered users only; guests appear in their party's board.

## Security notes

Tokens stored hashed (sha256). Magic link 15 min, single use, 5/h per email, 20/h per IP. Cookies HttpOnly,
SameSite=Lax, Secure when BASE_URL is https. Avatars re-encoded server side (Pillow → 256 px WebP), 4 MB limit.
Media and maps require a session. Admin = emails in `ADMIN_EMAILS`.
