# Per-page validation shots + independent bar counts.
#
# Just before a page flip, every real bar on the page is fully colored (the
# playhead has passed them all), and nothing moves — so a SINGLE frame gives
# per-page ground truth that doesn't depend on tracking. For each page this
# script:
#   * seeks to flip_frame - margin,
#   * statically detects colored bars in the lane (loose thresholds, lattice
#     row snapping, no motion/growth requirements),
#   * overlays the song_map notes for that page (green = mapped, red circle =
#     detected bar with no mapped note nearby -> a MISS),
#   * writes shots to <scratch>/shots_<which>/page###.jpg,
#   * prints per-page counts: mapped vs statically detected.
#
# Usage: python pageshots.py v2 [margin_frames]
import bisect
import json
import os
import sys

import cv2
import numpy as np

from extract import VIDEOS, Profile, W, H, split_component

from paths import CACHE_DIR as SCRATCH, map_path  # noqa: E402


def _waist_split(sub, min_w=4):
    """Split a same-row mask run at column-height waists: touching pills have
    ~full-height bodies and a narrow junction. Returns [(c0, c1)] segments."""
    hcol = (sub > 0).sum(axis=0)
    pos = hcol[hcol > 0]
    if not len(pos):
        return []
    medh = np.median(pos)
    thr = max(4, 0.65 * medh)
    segs, start = [], None
    for i, h in enumerate(hcol):
        if h >= thr:
            if start is None:
                start = i
        elif start is not None:
            segs.append((start, i))
            start = None
    if start is not None:
        segs.append((start, len(hcol)))
    return [s for s in segs if s[1] - s[0] >= min_w]


def detect_bars_static(frame, prof, swatches, lattice=None):
    """Loose static detection of colored bars in the lane of one frame.
    Splits components both vertically (adjacent rows) and horizontally
    (touching pills) instead of merging."""
    lx0, ly0, lx1, ly1 = prof.lane
    lane = frame[ly0:ly1, lx0:lx1]
    hsv = cv2.cvtColor(lane, cv2.COLOR_BGR2HSV)
    hch = hsv[:, :, 0].astype(np.int16)
    sch, vch = hsv[:, :, 1], hsv[:, :, 2]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    bars = []
    for cls, (h0, s0, v0) in enumerate(swatches):
        hd = np.minimum(np.abs(hch - h0), 180 - np.abs(hch - h0))
        tol = 7 if cls == 0 else 9
        m = ((hd <= tol) & (sch >= max(90, int(s0) - 90))
             & (vch >= max(90, int(v0) - 100))).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel)
        n, lab, stats, cent = cv2.connectedComponentsWithStats(m, 4)
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if w < 4 or h < 7 or h > 34 or area < 26:
                continue
            rows = [(x, x + w, y, h, lab == i)]
            if h > 22:  # possibly two lattice rows fused vertically
                rows = []
                for (a, b, cy, hh) in split_component(lab == i, x, y, w, h):
                    if 7 <= hh <= 24 and b - a >= 4:
                        y0r = int(max(0, cy - hh / 2 - 1))
                        rows.append((a, b, y0r, int(hh + 2), lab == i))
            for (a, b, yy, hh, full) in rows:
                sub = full[yy:yy + hh, a:b]
                for (c0, c1) in _waist_split(sub):
                    seg = sub[:, c0:c1]
                    rr = np.where(seg.any(axis=1))[0]
                    if not len(rr):
                        continue
                    seg_h = rr[-1] - rr[0] + 1
                    if seg_h < 7:
                        continue
                    ys, xs2 = np.nonzero(seg)
                    cy = yy + float(ys.mean())
                    bars.append((a + c0, a + c1, cy, seg_h, cls))
    if lattice:
        a, ph0 = lattice
        bars = [b for b in bars if abs((b[2] - ph0 + a / 2) % a - a / 2) <= 2.2]
    bars.sort(key=lambda b: (round(b[2] / 4), b[0]))
    return bars


def run(which, margin=12):
    sm = json.load(open(map_path(which),
                        encoding="utf-8"))
    fps = sm["fps"]
    flips = sm["page_flips"]
    lattice = (sm["lattice"]["px_per_semitone"], sm["lattice"]["phase"])
    prof = Profile(sm["family"])
    cap = cv2.VideoCapture(VIDEOS[which])
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    # legend swatches from a mid-video frame
    from extract import find_legend_swatches
    cap.set(cv2.CAP_PROP_POS_FRAMES, nframes // 2)
    ok, fr = cap.read()
    fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
    swatches = find_legend_swatches(fr, prof)[:3]

    outdir = os.path.join(SCRATCH, f"shots_{which}")
    os.makedirs(outdir, exist_ok=True)
    page_ends = flips + [sm["duration"]]
    notes = sm["notes"]
    lx0, ly0 = prof.lane[0], prof.lane[1]
    report = []
    for pg, t_end in enumerate(page_ends):
        t0 = flips[pg - 1] if pg > 0 else 0
        f_shot = max(0, int(t_end * fps) - margin)
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_shot)
        ok, fr = cap.read()
        if not ok:
            continue
        fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
        bars = detect_bars_static(fr, prof, swatches, lattice)
        mapped = [n for n in notes if t0 - 0.01 <= n["t_start"] < t_end - 0.01]
        # match static bars to mapped notes (x/row proximity)
        missed = []
        for (a, b, cy, h, cls) in bars:
            hit = any(abs(n["cy"] - cy) < 4.5 and
                      min(n["x1"], b) - max(n["x0"], a) > 0.4 * (b - a)
                      for n in mapped)
            if not hit:
                missed.append((a, b, cy))
        vis = fr.copy()
        for n in mapped:
            y = int(ly0 + n["cy"])
            cv2.rectangle(vis, (lx0 + n["x0"], y - 8), (lx0 + n["x1"], y + 8),
                          (0, 255, 0), 1)
        for (a, b, cy) in missed:
            y = int(ly0 + cy)
            cv2.circle(vis, (lx0 + (a + b) // 2, y), 14, (0, 0, 255), 2)
        cv2.imwrite(os.path.join(outdir, f"page{pg:03d}.jpg"), vis,
                    [cv2.IMWRITE_JPEG_QUALITY, 88])
        report.append((pg, len(mapped), len(bars), len(missed)))
    cap.release()
    tot_m = sum(r[1] for r in report)
    tot_d = sum(r[2] for r in report)
    tot_x = sum(r[3] for r in report)
    print(f"{which}: mapped {tot_m}, static-detected {tot_d}, "
          f"detected-but-unmapped {tot_x}")
    worst = sorted(report, key=lambda r: -r[3])[:12]
    print("worst pages (pg, mapped, detected, missed):", worst)
    return report


if __name__ == "__main__":
    run(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 12)
