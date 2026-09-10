# Lab notes — what was tried, what works, what doesn't

Running log, newest section first. Counts are `notes in map / HUD total`.
Ground truth = the video itself: HUD totals for counts, frame overlays (`pipeline/mapcheck.py v2.geo 45 121`)
for placement, and the color flip of a bar's left end for timing. NOT ground truth: `extract.py`'s playhead
trace (`ph_xs`) and `timingcheck.py` (both are fooled by background verticals on v2/v4).

## 2026-09-07 — manual labeling tool + speed

### Where the time really went (measured on v2, 720p60, 14 982 frames)
- Scan loop per frame: decode 1.5 ms, resize 0.01, HSV 0.35, playhead mask/colsum in numpy ~5 ms
  (`hsv[:,:,1]>=120` on a strided channel = 1.1 ms, the circular hue distance 2.6 ms, `.mean()` 1.1 ms).
  Static detection 17 ms but only every 30th frame. => the Python/numpy mask math, not decoding, dominated.
- `geotime.build`: 188 s, of which ~150 s were **4036 random seeks** (`Frames.get`, ~60 ms each) for the
  before/after/stability colour tests. The playhead-invisible pages' `flip_time` binary searches are the rest.
- GPU: `cv2.VideoCapture(..., [CAP_PROP_HW_ACCELERATION, VIDEO_ACCELERATION_ANY])` works (D3D11/NVDEC) but is
  SLOWER: 6.4 ms/frame vs 3.8 ms software on the 1080p60 file — the GPU→CPU frame copy costs more than the
  decode saves. Torch/CUDA is available (RTX 3060 6 GB) but nothing here is arithmetic-bound. Not pursued.

### What was done (outputs verified identical to the previous code)
- `sat_mask()` with `cv2.inRange` + a hue LUT (`cv2.LUT` on `extractChannel`) + `cv2.reduce` column sums:
  ~0.5 ms instead of ~5 ms. `playhead_runs` output identical on 1920 sampled frames × 2 hue modes.
- `scan()` split into frame ranges processed by a spawn Pool (default `min(6, cpus//2)` workers, chunk edges
  on multiples of the sample step so the static-sample frame set is unchanged). v2: old ≈100 s → 43 s
  sequential → 28 s with 6 workers; ph / washed / samples byte-identical to the cached `geo_v2.pkl`.
  (Only 1.5× from 6 workers: the decoder already uses several threads; disk/decoder contention.)
- `build()`: all frame requests of the verification stage are planned first, then ONE sequential pass
  (`measure_sequential`, `cap.grab()` for frames nobody needs) computes the colour fractions: 146 s → 7 s.
  v2 build 188 s → 50 s with an identical note set (453/453). The remaining ~40 s are `refine_page_by_flips`
  seeks (binary searches, can't be planned) and the extra end-of-page detections.
- Tried: extra candidate frames at the sweep's own x=1150/1190 times (T0 + x/R) in addition to t_end−0.1/−0.3.
  v2 453→454 (7 new, 6 lost), v4 359→360 (13 new, 12 lost) — churn, no gain. Reverted.

### Discovery while building the tool (matters for family B)
- A page's `t_end` (= next page's `vis_a` = playhead reaching the first bar column x_lo) is ~0.35–0.85 s AFTER
  the next page is drawn (the next sweep starts at its own T0 < t_end). So "t_end − 0.10" is often already
  the NEXT page (pale bars, playhead at x≈50). Harmless in geotime (those samples fail the flip test) but the
  tool must show a page at `T0 + max(1150, last x1 + 6) / R` (`labelapi.Song.t_show`). With that, static
  detection on the shown frame agrees with the maps: v2 459 vs 453, v4 327 vs 359 (pages 13/21 dark), v1
  687 vs 605 (pages 38–40 = the sun-flare graphic: +25/+28/+25 false detections).
- Sunset/explosion pages need the strict swatches for static detection too (page 6 of v2: 7 → 14 bars found,
  18 mapped). `labelapi.detect` switches automatically when the saturated fraction of the lane > 0.5.

### The tool (`app/label.html`, `pipeline/labelapi.py`, served by `serve.py` at /app/label.html)
- Edits GEOMETRY per page on a still frame; times are recomputed from the page's (R, T0) on save, midi from
  `pitch_anchor.midi_base + k`. A dry-run save of the untouched v2 map reproduces it (44/453 notes differ by
  1 ms because the JSON stores R rounded to 2 decimals).
- CV assists: static-bar suggestions (red dashed) = detected bars without a mapped note; add-at-cursor snaps
  to the detected bar (lattice filter off for that lookup); split/merge; flip strip (5 crops at t_start ±0.2 s);
  detected playhead ticks vs predicted line; refit R,T0 from the playhead (27 pts, 0.3 px residual on v2 p6)
  or from bar flips (RANSAC, 16/18 inliers on v2 p6); T0 ±1 frame nudges; HUD counter crop + map cumulative.

## 2026-09-06 (night 2) — geometry-first rebuild: `pipeline/geotime.py`

### The model (confirmed)
- Within a page the playhead sweeps linearly: `t = T0_page + x / R_page`. Bars never move within a page.
- Family A (v1 マリーゴールド, v3 夜に駆ける, v5 白日): R is constant for the whole video AND pages tile time
  with a constant period `P = 1200px / R` (v1 4.53 s, v3 3.70 s, v5 5.16 s). Missing pages can be filled and
  extrapolated to the song's start/end by period. Verified: per-page R varies < 0.3 %.
- Family B (v2 残酷な天使, v4 残響散歌): R varies per page (v2: 184 / 331 / 555 px/s), no tiling. Every page
  must be observed (playhead or bar flips).
- Geometric timing beats the tracked v1 map: true flip frames land within 1 frame of `T0 + x0/R`, while the
  "perfect by ear" v1 map was 0.1–0.25 s late on several notes. So the old v1/v5 maps are not a gold standard
  for timing; they are a good reference for *which* bars exist.

### Playhead detection that works (`playhead_runs`)
- Narrow (≤ 14 px) near-full-height (≥ 72 % of lane rows) saturated column, ISOLATED (columns ±8 px not
  saturated), and HUE-SPECIFIC in a 2nd pass (hue0 = mode of 1st-pass hues: v1 101, v2 7–9, v3 107, v4 100).
- Without the hue restriction the saturated blue sky of v2 (S≈160 everywhere) swallowed the orange line →
  whole pages "invisible" (v2 found 32 pages; with hue: 36 = HUD ページ total).
- Still invisible when the sky has the playhead's own hue (v2 sunset 184–191 s, explosions 46–55 s). Fix that
  worked: `refine_page_by_flips` — binary-search the flip time of every bar seen in that window and Theil-Sen
  fit 1 or 2 lines through (t_flip, x0). Found the hidden page boundary at 186.74 s (HUD page 24→25) and for
  v3 split 143.08 / 146.78 = exactly one period apart (sanity check passed).
- Page "visible" start is `T0 + x_lo / R` where x_lo = 5th percentile of bar x0 − 12 (bars start at x≈40 in
  family A, ≈80 in family B). Using T0 or the first detection time as the page boundary misassigns edge bars.

### Candidate bars
- Static detection (`pageshots.detect_bars_static`) every 0.5 s + two frames just before each page flip
  (t_end − 0.10 / − 0.30: all bars of the page are colored then; this recovers the right-edge bars that the
  0.5 s sampling never sees colored) + old-map notes where no static cluster overlaps.
- Cluster on (row ±4, x0 ±6, x1 ±8). Clustering on x0 only merged partial-wipe variants and touching pills.
- Washed-out frames (saturated fraction > 0.5, e.g. v2's orange sky): re-detect with strict swatches
  (S floor ≈ swatch S − 40): bars are S≈250 vs sky S≈150–165.

### Verification (per candidate, at the computed time)
- before = colored fraction of the bar's left 24 px at t_start − 0.2 s (clamped to ≥ page start + 0.03),
  after = at t_start + 0.2 s (clamped to ≤ t_end + 0.1 and page end). Need before ≤ 0.3, after ≥ 0.4.
- First bar of a page has no pale frame (page appears with the playhead already on it): accept if seen ≥ 3.
- Seen-once static candidates are allowed only with a crisp flip (before ≤ 0.15, after ≥ 0.6). These are
  almost all real right-edge bars (v1: 75/75 matched the reference map).
- Stability: the region must still be colored at t_end + 0.5 s (bars stay colored until the page flips;
  moving colored background — v4 koi fish — does not).
- Washed frame: redo the flip test with the strict saturation floor (`colored_frac_strict`).

### Dedupe / monophony
- Same page, same row, x-overlap: prefer the NARROWER variant if it was seen ≥ 3 times (touching pills that
  merged in some frames), else the most-seen.
- Do NOT run `monophony.enforce_monophony` on geometric notes: its "last note wins" splitting duplicated a
  long bar around an inner one (same bar twice at 113.81 and 114.58). Bars are x-disjoint within a page, so
  plain t_end trimming to the next t_start is all that's needed.

### Tried and rejected tonight
- **"Recurring static spot" junk filter** (same row/x0/x1 flipping in ≥ 3 consecutive pages ⇒ background
  graphic): would have deleted 102 REAL v1 notes. Bars sit on a beat grid, so the same (x0, x1, pitch)
  recurs page after page in any song. Reverted.
- **Washed rule "trust geometry if seen ≥ 2/4"** (accept without a pale frame in washed frames): leaked ~45
  junk notes from v1's sun-flare graphic (a static bluish ring, seen every page). Replaced by the strict-
  saturation flip test.
- **`seen ≥ 2` hard gate for static candidates**: lost the right-edge bars (v1 601 → 575-ish). Replaced by
  the crisp-flip exception.
- **x0 < x_lo + 8 gate**: rejected every FIRST bar of v3's pages (bars at x=40, x_lo=29, jitter to 36).
  Now `x0 < x_lo` only.
- **Page boundary = first playhead detection (t_a) or T0**: both misassign bars at page edges; use vis_a.
- **Merging same-line sweep segments only across ≤ 3 s holes**: v2's page 1 (4–10 s) split into a degenerate
  page. Now ≤ 8 s if the line predicts the next segment's x within 20 px; degenerate pages dropped.

### Results (all five promoted to `output/song_map_v*.json` on 2026-09-06; previous maps kept as `*.pre_geo.json`)
| song | HUD | best geotime count | notes |
|---|---|---|---|
| v1 | 598 | **605** (final code) | 19 extra = 11 real first-of-page bars the old map lacked + 5 merged touching pills + 3 timing-shifted matches; 10 missing = 5 in the sun flare (189–194 s) + merged pills |
| v2 | 503 | **453** (final code) | all 36 HUD pages found (hidden page at 186.75 s recovered by RANSAC flip fit). Deficits left: 46–55 s explosion page (bars invisible to color detection), 190 s and 230 s sunset pages (~6 each). Promoted. |
| v3 | 774 | **756** (final code) | overlays at 40/90/144/200 s all correct incl. first-of-page bars (an earlier 'missing first bar' reading was a JPEG artefact; zoom crop confirmed). Gap = touching pills + seen-once rejects |
| v4 | 379 | **359** (final code) | every 10 s bin ≥ the HUD counter events (which themselves total 333, a lower bound); koi junk gone (stability check). Promoted. |

| v5 | 786 | **784** | 23 'misses' vs the old map are mostly old-map junk (tiny 4–26 px pieces at 145–150 s); pitch anchor unchanged (D♭ major). Promoted. |

### Flip-line fitting
- Theil-Sen on all flips, and time-split into two halves, both failed once junk flips (sunset page had 27 flips, 11 real) were present. RANSAC over point pairs (line through 2 flips, count inliers within 0.08 s, ≥ 4 inliers, then refit on inliers, repeat for a 2nd line) recovered the two hidden pages at 183.00 / 186.75 s.

### Still open
- v2 explosion pages (whole lane orange): static detection and the flip test both drown. Strict saturation
  helps only partly.
- Touching pills merged by the 3×3 CLOSE in `detect_bars_static` (v1 109.5 s: 62–320 is really 3 bars).
- After promotion: run `anchor_audio.py` (midi from k), then listen in the app; update README/NEXT_STEPS.

## 2026-09-06 (night 1) — see NEXT_STEPS.md (retime/addstatic era)
Superseded: retime + addstatic reached v2 69 %, v3 81 %, v4 70 % on the trace-based metric and the counts
drifted (v4 456/379) because the trace is junk in places → wrong t_end → monophony fragments. The trace-based
metric itself was penalising correct notes (v2 33–36 s: notes right, trace wrong).

## 2026-09-05 — extraction era (extract.py, playhead_build, counter instruments)
See README.md and the memory notes: HUD-count matching was a misleading acceptance test; page segmentation
from detected flips was a dead end; audio anchoring for absolute pitch works (verified against on-screen
最高音/最低音 labels).
