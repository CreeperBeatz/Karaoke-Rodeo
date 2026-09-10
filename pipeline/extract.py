# Karaoke video -> song_map extraction (Phase 1 PoC).
#
# Works on カラオケ@DIVA-style videos. Two skin families:
#   A "kukan": 音数/区間 HUD, flat rect bars, thin blue playhead (v1 720p30, v3 1080p60)
#   B "page":  ノート/ページ HUD, rounded bars, playhead varies      (v2 720p60, v4 1080p60)
#
# Core idea: bars turn from dim/gray to a bright color exactly when the
# playhead (song time) passes them. We track colored bar components per frame;
# each note's geometry comes from its final colored extent and its timing from
# the growth ("wipe") of that colored region. Bars that never grow (next-page
# previews, static junk) are rejected.
import cv2
import numpy as np
import json
import os
import sys
import time
from collections import defaultdict

W, H = 1280, 720  # all analysis in 720p space


def hue_dist(a, b):
    d = abs(int(a) - int(b))
    return min(d, 180 - d)


class Profile:
    def __init__(self, family):
        self.family = family
        if family == "A":
            self.lane = (0, 52, W, 250)
            self.counter = (40, 15, 155, 50)  # 音数 count digits
            self.legend = (1000, 15, 1280, 50)
            self.lyrics = (0, 540, W, 720)
        else:
            self.lane = (0, 46, W, 238)
            self.counter = (55, 12, 195, 45)  # ノート count digits
            self.legend = (1000, 12, 1280, 48)
            self.lyrics = (0, 540, W, 720)


def detect_family(frame):
    """A: 音数 box top-left is dark navy/blue. B: ノート box is green/teal."""
    crop = frame[18:45, 15:160]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].astype(int)
    hue = hsv[:, :, 0].astype(int)
    m = sat > 60
    if m.sum() < 50:
        return "A"  # fallback
    med_hue = np.median(hue[m])
    # green/teal ~ 40-90; navy/blue/purple ~ 100-150
    return "B" if 30 <= med_hue <= 92 else "A"


def find_legend_swatches(frame, prof):
    """Find the three legend color swatches (音程/最高音/最低音) in top-right.
    Returns list of (hue, sat, val) sorted by x."""
    x0, y0, x1, y1 = prof.legend
    crop = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 140) & (hsv[:, :, 2] > 120)).astype(np.uint8)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    sw = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if 5 <= w <= 30 and 5 <= h <= 30 and area >= 25:
            m = lab == i
            hmed = np.median(hsv[:, :, 0][m])
            smed = np.median(hsv[:, :, 1][m])
            vmed = np.median(hsv[:, :, 2][m])
            sw.append((cent[i][0], (hmed, smed, vmed)))
    sw.sort()
    return [s[1] for s in sw]


class Note:
    __slots__ = ("cy", "x0", "x1", "first_f", "last_f", "growth", "cls",
                 "first_w", "h", "page", "hits")
    def __init__(self, f, x0, x1, cy, h, cls):
        self.first_f = f
        self.last_f = f
        self.x0 = x0
        self.x1 = x1
        self.cy = cy
        self.h = h
        self.cls = cls
        self.first_w = x1 - x0
        self.growth = [(f, x1)]
        self.page = -1
        self.hits = 1

    def update(self, f, x0, x1, cy, h, cls):
        self.last_f = f
        self.hits += 1
        self.x0 = min(self.x0, x0)
        if x1 > self.x1:
            self.x1 = x1
            self.growth.append((f, x1))
        self.cy = 0.7 * self.cy + 0.3 * cy
        self.h = max(self.h, h)


def split_component(mask, x, y, w, h):
    """Split an L-shaped component (two bars on adjacent rows touching) by
    per-column center-of-mass jumps. Returns list of (x0,x1,cy,h) runs."""
    sub = mask[y:y + h, x:x + w]
    ys = np.arange(h).reshape(-1, 1)
    colsum = sub.sum(axis=0)
    valid = colsum > 0
    if not valid.any():
        return []
    cy_col = np.where(valid, (sub * ys).sum(axis=0) / np.maximum(colsum, 1), -1)
    runs = []
    start = None
    prev_cy = None
    for i in range(w):
        if not valid[i]:
            if start is not None:
                runs.append((start, i))
                start = None
            prev_cy = None
            continue
        if start is None:
            start = i
        # threshold must be BELOW half the row spacing: a legato fusion of two
        # pills passes through an x-overlap zone whose center sits midway,
        # turning one full-row jump into two half-jumps (~3.7px at a=7.5)
        elif prev_cy is not None and abs(cy_col[i] - prev_cy) > 3.0:
            runs.append((start, i))
            start = i
        prev_cy = cy_col[i]
    if start is not None:
        runs.append((start, w))
    out = []
    for a, b in runs:
        if b - a < 3:
            continue
        seg = sub[:, a:b]
        rows = np.where(seg.any(axis=1))[0]
        if len(rows) == 0:
            continue
        cy = float(np.mean([cy_col[i] for i in range(a, b) if valid[i]]))
        out.append((x + a, x + b, y + cy, len(rows)))
    return out


def extract_notes(path, dbg_dir, loose=False):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # --- probe many frames for family + legend; a single frame can mis-sample
    # a swatch (overlays/petals/flashes), so use the per-position MEDIAN over
    # all frames where the full legend (3 swatches) is visible
    family = None
    fam_votes = []
    sw_samples = []  # list of 3-swatch lists
    for frac in (0.15, 0.22, 0.30, 0.37, 0.45, 0.52, 0.60, 0.67, 0.75, 0.82):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(nframes * frac))
        ok, fr = cap.read()
        if not ok:
            continue
        fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
        fam = detect_family(fr)
        sw = find_legend_swatches(fr, Profile(fam))
        if len(sw) >= 3:
            fam_votes.append(fam)
            sw_samples.append(sw[:3])
    assert sw_samples, "legend swatches not found in any probe frame"
    # majority family among frames with a visible legend
    family = max(set(fam_votes), key=fam_votes.count)
    prof = Profile(family)
    # the 3 legend colors are visually distinct by design; a frame where two
    # sampled hues nearly coincide mis-found a component (overlay/petal/flash)
    def _distinct(sw):
        hs = [s[0] for s in sw]
        return all(hue_dist(hs[i], hs[j]) >= 10
                   for i in range(3) for j in range(i + 1, 3))
    good_frames = [s for s in sw_samples if _distinct(s)]
    pool = good_frames if good_frames else sw_samples
    swatches = []
    for pos in range(3):  # main, high, low
        swatches.append((float(np.median([s[pos][0] for s in pool])),
                         float(np.median([s[pos][1] for s in pool])),
                         float(np.median([s[pos][2] for s in pool]))))
    print(f"swatch samples: {len(sw_samples)} frames ({len(good_frames)} distinct), "
          f"hues per frame: {[[round(s[p][0]) for p in range(3)] for s in sw_samples]}")
    print(f"family={family} fps={fps:.2f} frames={nframes} "
          f"swatches hue/s/v={swatches}")

    lx0, ly0, lx1, ly1 = prof.lane
    cx0, cy0, cx1, cy1 = prof.counter
    hue_ref = [s[0] for s in swatches]

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    open_notes = []
    done_notes = []
    counter_diff = np.zeros(nframes + 10, np.float32)
    ph_xs = np.full(nframes + 10, -1, np.int32)
    prev_counter = None
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    t0 = time.time()
    S = max(1.0, fps / 30.0)  # frame-count scale vs 30fps
    f = -1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        f += 1
        if frame.shape[1] != W:
            frame = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)
        c = frame[cy0:cy1, cx0:cx1]
        if prev_counter is not None:
            counter_diff[f] = np.mean(cv2.absdiff(c, prev_counter))
        prev_counter = c

        lane = frame[ly0:ly1, lx0:lx1]
        hsv = cv2.cvtColor(lane, cv2.COLOR_BGR2HSV)
        hch, sch, vch = hsv[:, :, 0].astype(np.int16), hsv[:, :, 1], hsv[:, :, 2]

        # playhead: the one near-full-height saturated vertical line
        sat_col = ((sch > 160) & (vch > 130)).sum(axis=0)
        pc_x = int(np.argmax(sat_col))
        if sat_col[pc_x] > 0.62 * (ly1 - ly0):
            ph_xs[f] = pc_x

        detections = []
        for cls in range(3):
            hd = np.minimum(np.abs(hch - hue_ref[cls]),
                            180 - np.abs(hch - hue_ref[cls]))
            tol = 5 if cls == 0 else 8
            # loose profile (noisy backgrounds): flashes/explosions wash out
            # saturation and blank the mask for whole frames (bars then track
            # as 1-frame "tiny" junk); sweep/lattice/geometry absorb the junk.
            # strict profile (clean backgrounds): verified exact on v1.
            if loose or cls > 0:
                # extreme (最高音/最低音) bars are few, sit on known extreme
                # rows, and get washed by flares: always detect them loosely
                s_thr = max(120, int(swatches[cls][1]) - 100)
                v_thr = max(110, int(swatches[cls][2]) - 100)
            else:
                s_thr = max(115, int(swatches[cls][1]) - 60)
                v_thr = max(115, int(swatches[cls][2]) - 75)
            m = ((hd <= tol) & (sch >= s_thr) & (vch >= v_thr)).astype(np.uint8) * 255
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel)
            n, lab, stats, cent = cv2.connectedComponentsWithStats(m, 4)
            for i in range(1, n):
                x, y, w, h, area = stats[i]
                if w < 3 or h < 7 or h > 30 or area < 26:
                    continue
                # always try row-splitting moderately tall components: a clean
                # single bar has no cy jumps and comes back whole, while thin
                # bars (v5: h~10 on an 8.4px lattice) fuse at h~18
                if h > 14:
                    for (a, b, cy, hh) in split_component(lab == i, x, y, w, h):
                        if 7 <= hh <= 24 and b - a >= 3:
                            detections.append((a, b, cy, hh, cls))
                    continue
                if area / (w * h) < 0.55:
                    continue
                detections.append((x, x + w, y + h / 2, h, cls))

        # match detections to open notes. Monotonic-growth rule: a detection
        # whose right edge is well left of the track's extent is a NEW wipe
        # (same bar redrawn on a later page), not a continuation.
        match_gap = int(round(4 * S))
        for (a, b, cy, h, cls) in detections:
            best = None
            for note in open_notes:
                if abs(note.cy - cy) <= 5 and abs(note.x0 - a) <= 7 \
                        and note.last_f >= f - match_gap and b >= note.x1 - 8:
                    best = note
                    break
            if best is not None:
                best.update(f, a, b, cy, h, cls)
            else:
                open_notes.append(Note(f, a, b, cy, h, cls))
        # close stale notes
        still = []
        for note in open_notes:
            if f - note.last_f > 5 * S:
                done_notes.append(note)
            else:
                still.append(note)
        open_notes = still
        if f % 3000 == 0 and f:
            print(f"  {f}/{nframes} ({f/(time.time()-t0):.0f} fps) "
                  f"open={len(open_notes)} done={len(done_notes)}")
    done_notes.extend(open_notes)
    cap.release()
    print(f"pass1 done in {time.time()-t0:.0f}s: {len(done_notes)} raw tracks")
    return dict(fps=fps, nframes=nframes, family=family, prof=prof,
                swatches=swatches, notes=done_notes, loose=loose,
                counter_diff=counter_diff[:f + 1], ph_xs=ph_xs[:f + 1])


def filter_notes(res):
    """Keep tracks that exhibited wipe growth; reject static junk/previews."""
    S = max(1.0, res["fps"] / 30.0)
    ph_xs = res["ph_xs"]
    # thin gate must adapt to the skin's bar height (v5 bars are ~12px vs 22)
    hs = [n.h for n in res["notes"] if n.x1 - n.x0 >= 7]
    thin_thr = max(8, 0.6 * (np.median(hs) if hs else 18))
    print(f"adaptive thin threshold: {thin_thr:.1f}")
    keep, reject = [], []
    for n in res["notes"]:
        w = n.x1 - n.x0
        lifetime = n.last_f - n.first_f
        grew = n.x1 - (n.x0 + n.first_w)
        hit_rate = n.hits / (lifetime + 1)
        loose = res.get("loose", False)
        if w < 7:
            reject.append((n, "tiny"))
        elif lifetime < 2:
            # loose: a full-width bar visible for a single frame is a real bar
            # whose surroundings are washed out (flash); slivers are junk
            if loose and w >= 12 and n.h >= thin_thr:
                keep.append(n)
            else:
                reject.append((n, "tiny"))
        elif grew < 3 and w > 26:
            reject.append((n, "static"))  # never wiped: preview or junk
        elif hit_rate < (0.45 if loose else 0.55):
            reject.append((n, "flicker"))  # textured background junk
        elif n.h < thin_thr:
            reject.append((n, "thin"))
        elif lifetime < 6 * S and grew < 3:
            reject.append((n, "remnant"))  # page-flip fade fragment
        else:
            keep.append(n)
    res["kept"] = keep
    res["rejected"] = reject
    from collections import Counter
    print(f"kept {len(keep)} / rejected {len(reject)} "
          f"{Counter(r for _, r in reject)}")
    return res


def teardown_flips(notes, fps):
    """Page flip frames = frames where several tracks die together."""
    from collections import Counter
    deaths = Counter()
    for n in notes:
        deaths[n.last_f] += 1
    frames = sorted(deaths)
    flips = []
    i = 0
    while i < len(frames):
        j = i
        tot = 0
        while j < len(frames) and frames[j] - frames[i] <= 3:
            tot += deaths[frames[j]]
            j += 1
        if tot >= 3:
            flips.append(frames[j - 1])
            i = j
        else:
            i += 1
    # merge flips closer than half a second
    merged = []
    for fl in flips:
        if merged and fl - merged[-1] < fps * 0.5:
            merged[-1] = fl
        else:
            merged.append(fl)
    return merged


def sweep_gate(res):
    """Within each page, real notes' (first_f, x0) lie on the playhead sweep
    line. Robust-fit per page, drop outliers (background junk)."""
    fps = res["fps"]
    kept = res["kept"]
    flips = teardown_flips(kept, fps)
    bounds = [0] + [fl + 2 for fl in flips] + [10 ** 9]
    keep, rej = [], 0
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        page = [n for n in kept if lo <= n.first_f < hi]
        if len(page) < 4:
            keep.extend(page)
            continue
        xs = np.array([n.x0 for n in page], np.float64)
        fs = np.array([n.first_f for n in page], np.float64)
        # robust line fit via median of pairwise slopes (Theil-Sen-ish)
        idx = np.argsort(xs)
        xs_s, fs_s = xs[idx], fs[idx]
        slopes = []
        for i in range(len(xs_s) - 1):
            dx = xs_s[i + 1] - xs_s[i]
            if dx > 15:
                slopes.append((fs_s[i + 1] - fs_s[i]) / dx)
        if not slopes:
            keep.extend(page)
            continue
        beta = np.median(slopes)
        if beta <= 0:
            keep.extend(page)
            continue
        alpha = np.median(fs - beta * xs)
        resid = np.abs(fs - (alpha + beta * xs)) / fps  # seconds
        # loose gate: the geometry cleanup has a per-sweep fit that catches
        # colliding ghosts; this only needs to kill far-off background junk
        for n, r in zip(page, resid):
            if r <= 0.9:
                keep.append(n)
            else:
                rej += 1
    print(f"sweep gate: kept {len(keep)}, rejected {rej} "
          f"({len(flips)} teardown flips)")
    res["kept"] = keep
    res["teardown_flips"] = flips
    return res


def _fit_lattice_ys(ys, lo=6.5):
    best = None
    for a in np.arange(lo, 13.0, 0.02):
        ph = np.mod(ys, a)
        ang = ph / a * 2 * np.pi
        C, S = np.cos(ang).sum(), np.sin(ang).sum()
        R = np.hypot(C, S) / len(ys)
        mean_ph = (np.arctan2(S, C) % (2 * np.pi)) / (2 * np.pi) * a
        d = np.abs((ph - mean_ph + a / 2) % a - a / 2)
        score = (d < 1.6).mean() + R * 0.25
        if best is None or score > best[0]:
            best = (score, a, mean_ph, (d < 1.6).mean())
    return best


def fit_lattice(res):
    """Fit cy = ph0 + a*k (a = px/semitone) on confident notes, then gate all
    kept notes on lattice residual."""
    med_h_all = np.median([n.h for n in res["kept"]]) if res["kept"] else 18
    conf = [n for n in res["kept"]
            if n.cls == 0 and n.x1 - (n.x0 + n.first_w) > 10
            and abs(n.h - med_h_all) <= 4]
    ys = np.array([n.cy for n in (conf if len(conf) >= 40 else res["kept"])])
    # thin-bar skins pack a wide range into dense rows (v5: ~4.25px/semitone)
    lo = 3.8 if med_h_all <= 13 else 6.5
    score, a, ph0, inlier = _fit_lattice_ys(ys, lo)
    print(f"lattice: a={a:.2f}px/semitone phase={ph0:.2f} "
          f"inliers={inlier:.2%} (fit on {len(ys)} confident)")
    res["lattice"] = (a, ph0)
    # bars all share one height; junk doesn't
    med_h = np.median([n.h for n in res["kept"]])
    kept2, rej = [], 0
    for n in res["kept"]:
        d = abs((n.cy - ph0 + a / 2) % a - a / 2)
        if d <= 2.0 and abs(n.h - med_h) <= 5:
            kept2.append(n)
        else:
            rej += 1
    print(f"lattice+height gate: kept {len(kept2)}, rejected {rej} (med_h={med_h})")
    # duplicate tracks of one bar are UNIONED later by the geometry cleanup
    # (dropping the shorter track here loses real notes and geometry)
    res["kept"] = kept2
    res["ks"] = np.round((np.array([n.cy for n in kept2]) - ph0) / a).astype(int)
    return res


def detect_pages(res):
    """Page boundaries: teardown flips (mass note closures)."""
    flips = res.get("teardown_flips") or teardown_flips(res["kept"], res["fps"])
    res["page_flips"] = flips
    print(f"page flips detected: {len(flips)} -> singing pages ~{len(flips)+1}")
    return res


def assemble(res, video_path, out_json):
    from meta import parse_title, NOTE_NAMES_EN
    fps = res["fps"]
    a, ph0 = res["lattice"]
    kept = res["kept"]
    # wipe rate (px/frame) per note where measurable
    rates = []
    for n in kept:
        gf = n.growth[-1][0]
        grew = n.x1 - (n.x0 + n.first_w)
        rates.append(grew / (gf - n.first_f) if gf - n.first_f >= 3 and grew > 15
                     else None)
    med_rate = np.median([r for r in rates if r]) if any(rates) else 3.0
    notes = []
    for n, k, rate in zip(kept, res["ks"], rates):
        t0 = n.first_f / fps
        # local rate: this note's own, else median of neighbors within 3s
        if rate is None:
            near = [r for m, r in zip(kept, rates)
                    if r and abs(m.first_f - n.first_f) < 3 * fps]
            rate = np.median(near) if near else med_rate
        dur_growth = (n.growth[-1][0] - n.first_f) / fps
        dur_rate = (n.x1 - n.x0) / rate / fps
        t1 = t0 + max(dur_growth, dur_rate)
        notes.append(dict(
            t_start=round(t0, 3), t_end=round(t1, 3),
            k=int(-k), cy=round(float(n.cy), 1),
            x0=int(n.x0), x1=int(n.x1),
            cls=["main", "high", "low"][n.cls],
            first_f=int(n.first_f), last_f=int(n.last_f),
        ))
    notes.sort(key=lambda d: d["t_start"])
    # class/pitch consistency: the song has exactly one highest and one lowest
    # pitch. "high"/"low" bars elsewhere are background junk; main bars at the
    # extreme rows are just that extreme note (reclassify).
    from collections import Counter
    k_all = [n["k"] for n in notes]
    kmax, kmin = max(k_all), min(k_all)
    # extreme rows = the MODAL row of each extreme-colored class: the global
    # max/min of k is poisoned by a single junk track past the real extreme,
    # which then kills every real 最高音/最低音 bar
    # candidates limited to the top/bottom half of the range: junk flooding an
    # extreme color class otherwise drags the mode to an arbitrary row (v4),
    # while junk ABOVE the real top must not block it either (v2)
    mid = (kmax + kmin) / 2
    hs = Counter(n["k"] for n in notes if n["cls"] == "high" and n["k"] >= mid)
    ls = Counter(n["k"] for n in notes if n["cls"] == "low" and n["k"] <= mid)
    khigh = hs.most_common(1)[0][0] if hs else kmax
    klow = ls.most_common(1)[0][0] if ls else kmin
    print(f"extreme rows: khigh={khigh} (global kmax={kmax}), "
          f"klow={klow} (global kmin={kmin})")
    cleaned = []
    dropped_cls = []
    for n in notes:
        # the two extreme swatch hues can be near-identical (e.g. v4: 169 vs
        # 167), so the classes are interchangeable: accept either color at
        # either extreme row; junk = extreme color off both extreme rows
        if n["cls"] in ("high", "low") and n["k"] not in (khigh, klow):
            dropped_cls.append(n["k"])
            continue  # junk
        n["cls"] = "high" if n["k"] == khigh else "low" if n["k"] == klow else "main"
        cleaned.append(n)
    if dropped_cls:
        from collections import Counter
        print(f"class-drop k histogram (kmin={kmin} kmax={kmax}): "
              f"{dict(sorted(Counter(dropped_cls).items()))}")
    print(f"class cleanup: {len(notes)} -> {len(cleaned)}")
    notes = cleaned
    flips = [round(e / fps, 3) for e in res["page_flips"]]
    # geometry-first cleanup: bars have fixed positions and time = x within a
    # page, so retime from the sweep line, drop x-collision ghosts, and
    # enforce a monophonic lane
    from monophony import clean_notes
    events = []
    notes = clean_notes(notes, flips, fps, events,
                        solo_offsweep=res.get("solo_offsweep", False))
    with open(out_json.replace("song_map_", "cleanup_log_"), "w", encoding="utf-8") as fh:
        json.dump(events, fh, ensure_ascii=False, indent=1)
    from collections import Counter
    print(f"geometry cleanup: -> {len(notes)} "
          f"{dict(Counter(e['reason'] for e in events))}")
    out = dict(
        video=os.path.basename(video_path),
        meta=parse_title(video_path),
        family=res["family"], fps=fps,
        duration=round(res["nframes"] / fps, 2),
        lattice=dict(px_per_semitone=round(a, 3), phase=round(ph0, 2)),
        page_flips=flips, n_pages=len(flips) + 1,
        n_notes=len(notes), notes=notes,
    )
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"wrote {out_json}: {len(notes)} notes, ~{len(flips)+1} pages")
    return out


from paths import VIDEOS, CACHE_DIR, MAPS_DIR  # noqa: E402

if __name__ == "__main__":
    import pickle
    which = sys.argv[1]
    scratch = CACHE_DIR
    os.makedirs(scratch, exist_ok=True)
    outdir = MAPS_DIR
    os.makedirs(outdir, exist_ok=True)
    path = VIDEOS[which]
    # cache raw pass1 tracks so gate iterations don't re-scan the video
    raw_pkl = os.path.join(scratch, f"raw_{which}.pkl")
    LOOSE = {"v1": False, "v2": True, "v3": True, "v4": True, "v5": True}
    if "--from-raw" in sys.argv and os.path.exists(raw_pkl):
        with open(raw_pkl, "rb") as fh:
            res = pickle.load(fh)
        res.setdefault("loose", LOOSE.get(which, True))
        print(f"loaded raw tracks from cache: {len(res['notes'])} "
              f"(loose={res.get('loose')})")
    else:
        res = extract_notes(path, scratch, loose=LOOSE.get(which, True))
        with open(raw_pkl, "wb") as fh:
            pickle.dump(res, fh)
    res["solo_offsweep"] = which in ("v3",)
    res = filter_notes(res)
    res = sweep_gate(res)
    res = fit_lattice(res)
    res = detect_pages(res)
    # save intermediate tracks for label pass
    import pickle
    with open(os.path.join(scratch, f"tracks_{which}.pkl"), "wb") as fh:
        pickle.dump(dict(
            fps=res["fps"], family=res["family"], lattice=res["lattice"],
            kept=[(n.first_f, n.last_f, n.x0, n.x1, n.cy, n.h, n.cls,
                   n.first_w, n.growth) for n in res["kept"]],
        ), fh)
    assemble(res, path, os.path.join(outdir, f"song_map_{which}.json"))
