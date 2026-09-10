# karaoke.rodeo（カラオケ.ロデオ）

Home karaoke scoring for カラオケ@DIVA practice videos. A CV pipeline turns a video into a "song map" (every pitch bar
with midi + start/end), the web app plays the video, listens to the mic and scores you karaoke-machine style, and keeps
history, stats, leaderboards and a QR party mode. Runs on a Raspberry Pi 4. Spec/decisions: `SPEC.md`. Pi deployment:
`deploy/README.md`.

```
server/      FastAPI app: magic-link login (Resend), SQLite, songs/media, plays, stats, leaderboards, party, admin, label API
worker.py    job runner: yt-dlp download (720p) -> extract -> geotime -> anchor -> lyrics -> "ready for labeling"
pipeline/    the extraction pipeline (see below) — portable via pipeline/paths.py (KARAOKE_DATA)
web/         front end (vanilla JS modules): index, play, stats, leaderboard, profile, party (phone), admin, label
tools/       import_poc.py — imports the five PoC songs
deploy/      install.sh, systemd units, Cloudflare Tunnel + Resend notes
data/        runtime state (gitignored): app.db, songs/<id>/video.mp4, maps/, cache/, avatars/
app/, serve.py, output/   the original PoC (kept for reference; the app reads data/, not output/)
```

## Run locally

```bash
pip install -r requirements.txt          # + ffmpeg on PATH (or the imageio-ffmpeg wheel is used)
cp .env.example .env                     # set ADMIN_EMAILS=you@…; leave RESEND_API_KEY empty for DEV_MODE
python tools/import_poc.py --publish     # once: copies output/*.json + the mp4s into data/ and registers them
python -m server                         # http://127.0.0.1:8765  (DEV_MODE prints the login link and shows it in the UI)
python worker.py                         # in a second terminal: processes queued songs
```

Log in at `/login` (in DEV_MODE the link appears on the page), sing at `/`, stats at `/stats`, ranking at
`/leaderboard` (総合 / 曲別 with a song search), admin (add YouTube URL, job queue, publish) at `/admin`, labeling tool at `/label#<song>/<page>`.

### How a play is scored (unchanged from the PoC)

Live pitch (NSDF autocorrelation, `web/static/pitch.js`) is folded to the nearest octave of the target note; per note the
time-weighted credit (`|Δ| ≤ 0.75 semitone` full, linear to 0 at 1.6) accumulates; score = 100·(hit/dur)^0.7 over
attempted notes; PERFECT/GREAT/GOOD/MISS at 0.82/0.55/0.28. Each play stores per-note `[rating, accuracy, cents]`, which
feeds the stats: score trend per song, pitch accuracy by note (sharp/flat tendency), weak sections (pages), practice
calendar and streaks. Leaderboards rank registered users by per-song best and by the average of bests (総合).

### Party mode

Party mode is a mode, not a button on every screen: it is started from the **home page** (パーティーを始める) and from
then on a strip under the header — on every page — shows the code, the seats and who has the mic, with QR・あいことば
and パーティー終了. With no party running there is no party UI anywhere.

Phones open `/p/<code>` and are offered exactly two ways in: **アカウントで参加** (type an email, the magic link is
requested inline and comes straight back to the party page) or **ゲストで参加** (nickname only). Someone already logged
in is seated with no prompt. The host taps a seat to hand over the mic; guests press 次うたいたい to queue.

Every seat gets its own colour (fixed palette, in join order), shown on the strip, on the phones, and — while that
person sings — as the colour of the live pitch line on the play page. Plays are attributed to the selected member; a
guest who later logs in on the same phone claims their seat and its plays.

## Adding songs (admin)

Paste a カラオケ@DIVA URL in `/admin`. The worker downloads at ≤720p, runs the pipeline (30–60 min on a Pi 4, ~5 min on
a desktop), and the song appears as **ラベリング待ち** with a link to the labeling tool; fix what the automatic pass
missed, then **公開**. Re-processing from a given stage, cancelling, editing titles and deleting are in the same table.

## Phase 1 — extraction pipeline (`pipeline/`)

Input: an mp4 from the channel. Output: `data/maps/song_map_<id>.json`. Run per song (the worker does exactly this):

```
cd pipeline
python -X utf8 extract.py <id>        # pass-1 tracking: colours, lattice, HUD (cached data/cache/raw_<id>.pkl)
python -X utf8 geotime.py <id>        # geometry-first notes + timing
python -X utf8 anchor_audio.py <id>   # absolute pitch anchor (audio spectral vote)
python -X utf8 lyrics.py <id>         # lyric line regions + wipe timing
```

`<id>` is a folder in `data/songs/<id>/video.mp4` (the YouTube id), or v1..v5 for the PoC files in the repo root.

How it works:

1. **extract.py** — pitch bars turn from a pale "upcoming" state to their legend colour exactly when the playhead passes.
   Coloured bar-shaped components (colours auto-sampled from the 音程 / 最高音 / 最低音 legend swatches) are tracked; a
   note's geometry is its final coloured extent. Junk is rejected by wipe-growth, hit-rate, height, a per-page sweep gate,
   a fitted semitone lattice and one-pitch consistency for the highest/lowest bars. Both skin families (音数/区間 flat
   bars and ノート/ページ rounded bars) at 720p/1080p, 30/60 fps; everything is normalised to 1280×720.
2. **geotime.py** — the playhead is detected as a narrow, isolated, full-height line of its own hue; one straight sweep
   is fitted per page; every bar is timed from its x position (`t = T0 + x/R`) and verified by its pale→coloured flip.
3. **anchor_audio.py** — the guide melody anchors the lattice in absolute pitch (spectral energy over octave/offset
   hypotheses), verified against the on-screen 最高音/最低音 labels.
4. **lyrics.py** — lyric line bounding boxes, show/hide times, pink wipe front.

Validation ground truth: the videos' own HUD counters (音数 598 / 区間 67 …). See `LAB_NOTES.md` (what was tried) and
`NEXT_STEPS.md` (remaining recall gaps).

| id | song | notes / HUD | pitch anchor |
|----|------|-------------|--------------|
| v1 | マリーゴールド | 608 / 598 | D major |
| v5 | 白日 | 793 / 786 | D♭ major |
| v3 | 夜に駆ける | 809 / 774 | E♭-centred |
| v4 | 残響散歌 | 377 / 379 | F#/B-centred |
| v2 | 残酷な天使のテーゼ | 502 / 503 | F-centred |

## Manual labeling tool (`/label`, `pipeline/labelapi.py`)

Page-by-page editor on a still frame in which every bar of the page is coloured. Bars never move within a page and the
playhead sweeps linearly, so editing a bar's x-extent *is* editing its timing; the server recomputes times, midi and
note names on save (first save keeps `*.pre_label.json`, every save a `*.bak.json`). Red dashed boxes are CV
suggestions (`A` accept, `Shift+A` all), double-click adds a bar snapped to the detected one, `S`/`M` split/merge,
`Del` removes, `Ctrl+S` saves. Admin only.
