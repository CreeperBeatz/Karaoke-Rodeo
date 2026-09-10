# Karaoke PoC — status & next steps (updated 2026-09-07)

## New: manual labeling tool (2026-09-07)

```
python serve.py            # then open http://127.0.0.1:8765/app/label.html   (#v2/6 = song v2, page 6)
```
Page-by-page editor on a still frame with every bar coloured. Fix the remaining recall gaps by hand with CV
help, instead of another automatic gate:
1. pick the song, press **scan pages**: red `+n` = statically detected bars with no mapped note (likely misses;
   v1 pages 38–40 are the sun flare = ignore), yellow `−n` = mapped notes the detector doesn't see (check them).
2. on a page: red dashed boxes are suggestions — click (or `A`) to accept, `Shift+A` accepts all; double-click
   an unmarked bar to add it (snaps to the detected bar); drag edges/bodies; `S` splits a merged pill at the
   cursor, `M` merges; `Del` removes junk (e.g. green boxes with no bar under them).
3. timing check: scrub or **▶ play** the page — the magenta line is the map's playhead prediction, cyan ticks
   the detected playhead; green = started, yellow = upcoming. **flip strip** shows a bar's left end at
   t_start ±0.2 s. If a whole page is off, **refit ← playhead** / **refit ← flips** propose new (R, T0);
   T0 ±1f nudges.
4. **save** (Ctrl+S) rewrites `output/song_map_<id>.json` (first save keeps `*.pre_label.json`, every save a
   `*.bak.json`); times/midi/names are recomputed from geometry + `pitch_anchor.midi_base`. Method becomes
   `geotime+manual`. No re-anchoring needed unless you add bars far outside the previous pitch range.
Start with v2 (46–55 s explosion page = pages 7–8, the sunset pages ~24–26, 31) and v3's merged pills.

Pipeline speed (see LAB_NOTES): `geotime.py v2` scan 28 s (6 workers) + build 50 s, outputs identical.
GPU decode was measured slower than CPU; nothing here is arithmetic-bound — no CUDA work planned.


All five song maps were rebuilt with the geometry-first pipeline `pipeline/geotime.py` and promoted to
`output/song_map_v*.json` (the previous maps are kept as `output/song_map_v*.pre_geo.json`; the app only serves
`song_map_<id>.json`). Pitch was re-anchored with `anchor_audio.py`; lyrics survived in the JSON.
Full record of what was tried and why: `LAB_NOTES.md`.

## Where each song stands

| song | notes / HUD total | pages | what to expect in the app |
|---|---|---|---|
| v1 マリーゴールド | 605 / 598 | 57 | same bars as before plus the first bar of ~11 pages that were missing; timing now from the sweep line (verified to 1 frame against the actual color flips) |
| v5 白日 | 784 / 786 | 51 | as before, minus ~15 junk slivers the old map had at 145–150 s |
| v3 夜に駆ける | 756 / 774 | 73 | should now be in sync everywhere (was "misplaced" at 76 %); ~18 bars missing, mostly touching pills merged into one |
| v4 残響散歌 | 359 / 379 | 24 | should be in sync (was "bad"); every 10 s bin has ≥ the HUD-counter events; koi-fish junk removed |
| v2 残酷な天使のテーゼ | 453 / 503 | 36 | should be in sync (was "many missed" on the wrong page); ~50 bars still missing, concentrated in the 46–55 s explosion page and the sunset pages around 190 s and 230 s |

## Please check by ear (5 min)

```
python serve.py      # http://127.0.0.1:8765/
```
Listen to v2 around 30–45 s and 180–195 s (the two places that were wrong before) and to v3/v4 anywhere.
If something is still off, note the song + time; `python -X utf8 pipeline/mapcheck.py v2 45 121` renders the
frame with the map overlaid (green = started, yellow = upcoming).

## How to rebuild a song (all offline once the video is scanned)

```
cd pipeline
python -X utf8 geotime.py v2            # scan (2 passes, ~3–8 min) + build; caches SC/geo_v2.pkl
python -X utf8 geotime.py v2 build .geo # rebuild only, to output/song_map_v2.geo.json (dry run)
python -X utf8 anchor_audio.py v2       # midi from k (after promoting the map)
```
`SC` (the scratchpad with `raw_*.pkl`, `geo_*.pkl`, `audio_*.f32`) is hard-coded in `retime.py`.

## Remaining recall gaps and the ideas not yet tried

1. **v2 explosion page (46–55 s, ~20 bars)**: whole lane is bar-coloured. The bars have a dark outline and the
   pale ones are dark grey pills — detect bars by their OUTLINE (dark ring around a saturated core) instead of
   by colour there. Nothing tried yet.
2. **Touching pills merged (v3 ~15, v1 ~5)**: `pageshots.detect_bars_static` does a 3×3 CLOSE which bridges the
   2–4 px gap between adjacent bars on the same row. Try: no CLOSE (or 2×1), or split at columns whose height
   dips, before the waist split. Also let old-map notes compete with a wider static cluster when they are
   narrower and inside it.
3. **Sunset pages v2 (~12 bars)**: playhead has the sky's hue; bars are found statically but their flips are
   only trusted with the strict saturation test. Lowering the strict floor (S ≥ s0 − 60) is the first knob.
4. `geotime.py` has no unit tests; `LAB_NOTES.md` lists every gate and its effect — change one at a time.

## Dead ends (don't retry) — details in LAB_NOTES.md
- Anything derived from `extract.py`'s `ph_xs` playhead trace (retime, addstatic, playhead_build,
  timingcheck): background verticals fool it on v2/v4.
- HUD note-count matching as the acceptance test.
- "Recurring static spot" junk filter (bars legitimately recur on the beat grid page after page).
- Accepting bars in washed-out frames without a pale→coloured flip test.
