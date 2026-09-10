# Reconcile a tracked song_map against STATIC page snapshots (all videos).
#
# Bars have fixed positions within a page (user-confirmed). At the end of a
# page every real bar is fully colored, so two snapshots ~0.9s apart give a
# canonical bar set: a bar must appear in BOTH with the same geometry —
# background junk (explosions, flares, moving art) does not hold still.
#
#   * page boundaries: ページ digit transitions (B-layout: v2/v4) or 音数
#     jump times (A-layout: v1/v3) — scanned into counter/page event files.
#   * map notes CONFIRMED by a static bar are kept (geometry unioned).
#   * confirmed static bars MISSING from the map are added.
#   * map notes with no static support are dropped as junk.
#   * timing: per-page Theil-Sen sweep fit (t_start vs x0) from confirmed
#     matches; every note is retimed t = b + s*x from geometry.
#
# Usage: python static_reconcile.py v2
import json
import os
import sys
import time
from statistics import median

import cv2
import numpy as np

from extract import VIDEOS, Profile, W, H, find_legend_swatches, hue_dist
from pageshots import detect_bars_static
from monophony import enforce_monophony
from static_extract import scan_page_flips

SCRATCH = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\1813b478-5196-4d97-b594-ec02a435b54a\scratchpad"
# how page boundaries are read per video: "page" = ページ digits scan,
# "counter" = 音数 jump times already saved in counter_events_<which>.json
FLIP_SOURCE = {"v1": "counter", "v2": "page", "v3": "counter", "v4": "page"}
# snapshot offsets back from each boundary (seconds)
SNAPS = {"page": (0.35, 1.25), "counter": (-0.02, 0.9)}


def run(which):
    sm_path = rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json"
    sm = json.load(open(sm_path, encoding="utf-8"))
    src = FLIP_SOURCE[which]
    if src == "page":
        fps_box = []
        flips = scan_page_flips(which, fps_box)
    else:
        flips = json.load(open(SCRATCH + f"/counter_events_{which}.json"))["events"]
    fps = sm["fps"]
    duration = sm["duration"]
    prof = Profile(sm["family"])
    a_l = sm["lattice"]["px_per_semitone"]
    ph0 = sm["lattice"]["phase"]

    cap = cv2.VideoCapture(VIDEOS[which])
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sw_samples = []
    for frac in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(nframes * frac))
        ok, fr = cap.read()
        if not ok:
            continue
        fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
        sw = find_legend_swatches(fr, prof)
        if len(sw) >= 3:
            hs = [s[0] for s in sw[:3]]
            if all(hue_dist(hs[i], hs[j]) >= 10 for i in range(3) for j in range(i+1, 3)):
                sw_samples.append(sw[:3])
    swatches = [tuple(float(np.median([s[p][i] for s in sw_samples])) for i in range(3))
                for p in range(3)]

    # canonical static bars per boundary interval. The all-colored window is
    # narrow (last note ends ~ at the boundary, then the page fades), so SEARCH
    # frames around each boundary for maximum bar coverage instead of trusting
    # fixed offsets.
    bounds = sorted(t for t in flips if 2.0 < t < duration - 0.5)
    ends = bounds + [duration - 0.3]
    starts = [0.0] + bounds
    t0 = time.time()
    pages = []  # (t_lo, t_hi, [bars])
    for lo, hi in zip(starts, ends):
        if hi - lo < 1.2:
            continue
        cands = []  # (count, t, bars)
        for dt in np.arange(-0.15, 1.65, 0.15):
            t = hi - dt
            if t <= lo + 0.3 or t >= duration:
                continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(t * fps)))
            ok, fr = cap.read()
            if not ok:
                continue
            fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
            bars = detect_bars_static(fr, prof, swatches, (a_l, ph0))
            cands.append((len(bars), t, bars))
        if not cands:
            continue
        cands.sort(key=lambda c: -c[0])
        best = cands[0]
        second = next((c for c in cands[1:] if abs(c[1] - best[1]) >= 0.3), None)
        if best[0] == 0 or second is None:
            continue
        confirmed = []
        rightmost = max(b for (a, b, cy, h, cls) in best[2])
        for (a, b, cy, h, cls) in best[2]:
            hit = any(abs(cy - cy2) < 4 and min(b, b2) - max(a, a2) >
                      0.6 * min(b - a, b2 - a2)
                      for (a2, b2, cy2, h2, cls2) in second[2])
            # the rightmost bar may still be wiping in the other frame
            if hit or b >= rightmost - 10:
                confirmed.append((a, b, cy, cls))
        pages.append((lo, hi, confirmed))
    cap.release()
    n_conf = sum(len(p[2]) for p in pages)
    print(f"{which}: {len(pages)} pages, {n_conf} confirmed static bars "
          f"({time.time()-t0:.0f}s)")
    if n_conf < 0.6 * len(sm["notes"]):
        print("ABORT: too few confirmed bars vs map — page timing unreliable; "
              "map left unchanged")
        return

    # reconcile page by page
    notes_in = sm["notes"]
    out_notes = []
    added = dropped = kept = 0
    for lo, hi, bars in pages:
        mnotes = [n for n in notes_in if lo - 0.3 <= n["t_start"] < hi - 0.05]
        # match map notes <-> bars
        matches = []  # (note, bar)
        used = set()
        for n in mnotes:
            best, bi = None, -1
            for i, (a, b, cy, cls) in enumerate(bars):
                if i in used or abs(n["cy"] - cy) >= 4.5:
                    continue
                ov = min(n["x1"], b) - max(n["x0"], a)
                if ov > 0.5 * min(n["x1"] - n["x0"], b - a) and \
                        (best is None or ov > best):
                    best, bi = ov, i
            if bi >= 0:
                used.add(bi)
                matches.append((n, bars[bi]))
        # sweep fit from matched notes (tracked t_start vs bar x0)
        pts = [(bar[0], n["t_start"]) for n, bar in matches]
        fit = None
        if len(pts) >= 3:
            slopes = [(tb - ta) / (xb - xa) for i, (xa, ta) in enumerate(pts)
                      for xb, tb in pts[i+1:] if abs(xb - xa) > 30]
            slopes = [s for s in slopes if 0.002 < s < 0.05]
            if len(slopes) >= 3:
                s = median(slopes)
                b0 = median(t - s * x for x, t in pts)
                if median(abs(t - (b0 + s * x)) for x, t in pts) <= 0.35:
                    fit = (s, b0)
        for i, (a, b, cy, cls) in enumerate(bars):
            m = next((n for n, bar in matches if bar[0] == a and bar[2] == cy), None)
            k = int(round((cy - ph0) / a_l))
            if fit:
                s, b0 = fit
                t0n, t1n = b0 + s * a, b0 + s * b
            elif m is not None:
                t0n, t1n = m["t_start"], m["t_end"]
            else:
                continue  # unmatched bar on an unfittable page: skip
            base = dict(m) if m is not None else {}
            base.update(t_start=round(t0n, 3), t_end=round(max(t1n, t0n + 0.05), 3),
                        k=-k, cy=round(float(cy), 1), x0=int(a), x1=int(b),
                        first_f=int(t0n * fps), last_f=int(t1n * fps))
            if m is None:
                base["cls"] = ["main", "high", "low"][cls]
                added += 1
            else:
                kept += 1
            out_notes.append(base)
        dropped += len(mnotes) - len(matches)
    print(f"kept {kept}, added {added}, dropped {dropped} junk")

    out_notes.sort(key=lambda n: n["t_start"])
    # extreme-class cleanup on the reconciled set
    from collections import Counter
    k_all = [n["k"] for n in out_notes]
    kmax, kmin = max(k_all), min(k_all)
    mid = (kmax + kmin) / 2
    hs2 = Counter(n["k"] for n in out_notes if n["cls"] == "high" and n["k"] >= mid)
    ls2 = Counter(n["k"] for n in out_notes if n["cls"] == "low" and n["k"] <= mid)
    khigh = hs2.most_common(1)[0][0] if hs2 else kmax
    klow = ls2.most_common(1)[0][0] if ls2 else kmin
    cleaned = []
    for n in out_notes:
        if n["cls"] in ("high", "low") and n["k"] not in (khigh, klow):
            continue
        n["cls"] = "high" if n["k"] == khigh else "low" if n["k"] == klow else "main"
        cleaned.append(n)
    notes = enforce_monophony(cleaned)
    print(f"class+monophony: {len(out_notes)} -> {len(notes)}")

    sm["notes"] = notes
    sm["n_notes"] = len(notes)
    sm["method"] = "tracked+static-reconciled"
    json.dump(sm, open(sm_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {sm_path}: {len(notes)} notes")


if __name__ == "__main__":
    run(sys.argv[1])
