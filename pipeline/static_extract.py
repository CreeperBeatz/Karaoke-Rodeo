# Static page-snapshot extraction for B-layout videos (v2, v4).
#
# Bars have FIXED positions within a page and only change color as the
# playhead passes (user-confirmed). Tracking through 15k frames fights washes,
# fusions and background junk; instead:
#   1. TRUE page intervals from the ページ counter digits (state-hash scan).
#   2. Per page, statically detect bars in TWO frames near the page end
#      (all bars colored). A bar must appear in both with the same geometry —
#      explosions/flashes move or fade between frames 0.9s apart, bars don't.
#   3. Timing from geometry: t = anchor + s*x, s and anchor fitted per page
#      from the note-counter events (first/last event <-> first/last bar end).
#   4. Lattice/class/extreme handling as in the tracking pipeline, then the
#      geometry monophony cleanup.
#
# Usage: python static_extract.py v2
import json
import os
import sys
import time

import cv2
import numpy as np

from extract import VIDEOS, Profile, W, H, find_legend_swatches, hue_dist
from pageshots import detect_bars_static
from monophony import enforce_monophony
from meta import parse_title

SCRATCH = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\1813b478-5196-4d97-b594-ec02a435b54a\scratchpad"
PAGE_CROP = (290, 14, 346, 42)  # current-page digits only (1280x720 space)


def scan_page_flips(which, fps_out):
    """Stable-state scan of the ページ digits -> flip times (s)."""
    cap = cv2.VideoCapture(VIDEOS[which])
    fps = cap.get(cv2.CAP_PROP_FPS)
    vw, vh = cap.get(3), cap.get(4)
    sx, sy = vw / 1280.0, vh / 720.0
    x0, y0, x1, y1 = PAGE_CROP
    x0, x1, y0, y1 = int(x0 * sx), int(x1 * sx), int(y0 * sy), int(y1 * sy)
    prev_hash, run, run_start = None, 0, 0
    stable = []
    f = -1
    t0 = time.time()
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        f += 1
        g = cv2.cvtColor(fr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        m = cv2.resize((g > 180).astype(np.uint8), (24, 8), interpolation=cv2.INTER_AREA)
        hsh = (m > 0.5).tobytes()
        if hsh == prev_hash:
            run += 1
        else:
            prev_hash, run, run_start = hsh, 1, f
        if run == 3:
            if not stable:
                stable.append((run_start, hsh))
            elif stable[-1][1] != hsh:
                a = np.frombuffer(stable[-1][1], np.uint8)
                b = np.frombuffer(hsh, np.uint8)
                if int(np.sum(a != b)) >= 3:
                    stable.append((run_start, hsh))
    cap.release()
    flips = [s[0] / fps for s in stable[1:]]
    print(f"{which}: page scan {f+1} frames in {time.time()-t0:.0f}s -> "
          f"{len(stable)} page states ({len(flips)} transitions)")
    fps_out.append(fps)
    return flips


def run(which):
    ev = np.array(json.load(open(SCRATCH + f"/counter_events_{which}.json"))["events"])
    fps_box = []
    flips = scan_page_flips(which, fps_box)
    fps = fps_box[0]

    cap = cv2.VideoCapture(VIDEOS[which])
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = nframes / fps
    # legend swatches: median over probe frames with 3 distinct hues
    sw_samples = []
    prof = Profile("B")
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
    print("swatches:", [tuple(round(x, 1) for x in s) for s in swatches])

    # per page: detect bars in two snapshots, keep geometry-confirmed ones
    page_ends = flips + [duration - 0.2]
    page_starts = [0.0] + flips
    all_bars = []  # (page, x0, x1, cy, cls)
    for pg, (t0p, t1p) in enumerate(zip(page_starts, page_ends)):
        if t1p - t0p < 1.5:
            continue
        snaps = []
        for dt in (0.30, 1.20):
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int((t1p - dt) * fps)))
            ok, fr = cap.read()
            if not ok:
                continue
            fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
            snaps.append(detect_bars_static(fr, prof, swatches, None))
        if len(snaps) < 2:
            continue
        for (a, b, cy, h, cls) in snaps[0]:
            for (a2, b2, cy2, h2, cls2) in snaps[1]:
                if abs(cy - cy2) < 4 and min(b, b2) - max(a, a2) > 0.7 * min(b - a, b2 - a2):
                    all_bars.append((pg, min(a, a2), max(b, b2),
                                     (cy + cy2) / 2, max(h, h2), cls))
                    break
    print(f"confirmed static bars: {len(all_bars)} over {len(page_ends)} pages")

    # lattice fit on bar centers
    from extract import _fit_lattice_ys
    ys = np.array([b[3] for b in all_bars])
    score, a_l, ph0, inl = _fit_lattice_ys(ys)
    print(f"lattice: a={a_l:.2f} ph0={ph0:.2f} inliers={inl:.1%}")
    med_h = np.median([b[4] for b in all_bars])
    bars = []
    for (pg, x0, x1, cy, h, cls) in all_bars:
        d = abs((cy - ph0 + a_l / 2) % a_l - a_l / 2)
        if d <= 2.2 and abs(h - med_h) <= 6:
            bars.append((pg, x0, x1, cy, cls))
    print(f"lattice+height: {len(bars)}")

    # timing per page: sweep t = anchor + s*x from counter events
    ss = []
    per_page = {}
    for (pg, x0, x1, cy, cls) in bars:
        per_page.setdefault(pg, []).append((x0, x1, cy, cls))
    prelim = {}
    for pg, bs in per_page.items():
        t0p, t1p = page_starts[pg], page_ends[pg]
        e = ev[(ev > t0p + 0.05) & (ev <= t1p + 0.3)]
        bs = sorted(bs)
        if len(e) >= 2 and len(bs) >= 2:
            x1_first, x1_last = bs[0][1], bs[-1][1]
            if x1_last - x1_first > 100:
                s = (e[-1] - e[0]) / (x1_last - x1_first)
                if 0.002 < s < 0.05:
                    prelim[pg] = (s, e[0] - s * x1_first)
    s_global = float(np.median([v[0] for v in prelim.values()])) if prelim else None
    print(f"page sweep fits: {len(prelim)}/{len(per_page)}, s_global={s_global}")
    notes = []
    for pg, bs in sorted(per_page.items()):
        fit = prelim.get(pg)
        if fit is None:
            if s_global is None:
                continue
            # anchor with one event if available, else spread over page
            t0p, t1p = page_starts[pg], page_ends[pg]
            e = ev[(ev > t0p + 0.05) & (ev <= t1p + 0.3)]
            bs_sorted = sorted(bs)
            s = s_global
            b0 = (e[0] - s * bs_sorted[0][1]) if len(e) else (t0p + 0.8 - s * bs_sorted[0][0])
            fit = (s, b0)
        s, b0 = fit
        for (x0, x1, cy, cls) in sorted(bs):
            t0n = b0 + s * x0
            t1n = b0 + s * x1
            k = int(round((cy - ph0) / a_l))
            notes.append(dict(
                t_start=round(t0n, 3), t_end=round(t1n, 3), k=-k,
                cy=round(float(cy), 1), x0=int(x0), x1=int(x1),
                cls=["main", "high", "low"][cls],
                first_f=int(t0n * fps), last_f=int(t1n * fps),
            ))
    notes.sort(key=lambda n: n["t_start"])
    # class/extreme cleanup (same rules as tracking assemble)
    from collections import Counter
    k_all = [n["k"] for n in notes]
    kmax, kmin = max(k_all), min(k_all)
    mid = (kmax + kmin) / 2
    hs2 = Counter(n["k"] for n in notes if n["cls"] == "high" and n["k"] >= mid)
    ls2 = Counter(n["k"] for n in notes if n["cls"] == "low" and n["k"] <= mid)
    khigh = hs2.most_common(1)[0][0] if hs2 else kmax
    klow = ls2.most_common(1)[0][0] if ls2 else kmin
    cleaned = []
    for n in notes:
        if n["cls"] in ("high", "low") and n["k"] not in (khigh, klow):
            continue
        n["cls"] = "high" if n["k"] == khigh else "low" if n["k"] == klow else "main"
        cleaned.append(n)
    print(f"class cleanup: {len(notes)} -> {len(cleaned)} (khigh={khigh} klow={klow})")
    notes = enforce_monophony(cleaned)
    print(f"monophony: -> {len(notes)}")

    out = dict(
        video=os.path.basename(VIDEOS[which]),
        meta=parse_title(VIDEOS[which]),
        family="B", fps=fps, duration=round(duration, 2),
        lattice=dict(px_per_semitone=round(a_l, 3), phase=round(ph0, 2)),
        page_flips=[round(t, 3) for t in flips], n_pages=len(page_ends),
        n_notes=len(notes), notes=notes,
        method="static",
    )
    out_json = rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json"
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"wrote {out_json}: {len(notes)} notes, {len(page_ends)} pages")
    cap.release()


if __name__ == "__main__":
    run(sys.argv[1])
