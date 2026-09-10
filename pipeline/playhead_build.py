# Build the song map from the PLAYHEAD TRACE + static page snapshots.
#
# The playhead x-position per frame (ph_xs, recorded during pass1) is the
# ground-truth clock: pages are sustained left-resets of its sawtooth, and a
# bar that spans [x0, x1] starts/ends exactly when the playhead crosses those
# x. Bars themselves come from static detection at the page's all-colored
# moment (playhead at max, just before the reset), confirmed against a second
# frame ~0.4s earlier — background junk moves, bars don't.
#
# The tracked song_map supplies lattice + fps + metadata; its notes are only
# used as a fallback for pages whose playhead trace is unusable.
#
# Usage: python playhead_build.py v2
import json
import pickle
import sys
import time

import cv2
import numpy as np

import __main__
from extract import (VIDEOS, Profile, Note, W, H, find_legend_swatches,
                     hue_dist)
__main__.Profile = Profile
__main__.Note = Note
from pageshots import detect_bars_static
from monophony import enforce_monophony

SCRATCH = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\1813b478-5196-4d97-b594-ec02a435b54a\scratchpad"
# near-duplicate handling differs per skin: v4's dups are static/tracked pairs
# of one bar (identical spans); v2's tracked smears would swallow real bars
NEAR_DUP = {"v4": True}
# family-B videos have a per-note counter; family-A counters tick per section
PER_NOTE_COUNTER = {"v2", "v4"}


def playhead_pages(raw, min_span=250, flips=()):
    """Split the playhead trace into pages at sustained left-resets, playhead
    gaps, and known flip times (e.g. from the page-counter digits).
    Returns [(frame_indices, smoothed_x)] per page."""
    ph = np.asarray(raw["ph_xs"])
    fps = raw["fps"]
    idx = np.where(ph >= 0)[0]
    v = ph[idx].astype(float)
    sm = np.array([np.median(v[max(0, i - 3):i + 4]) for i in range(len(v))])
    flip_frames = sorted(int(t * fps) for t in flips)
    pages = []
    start = 0
    i = 0
    hold = int(round(fps * 0.4))
    gap = 0.8 * fps  # playhead vanishes during page transitions
    fi = 0
    while i < len(sm) - 1:
        brk = False
        while fi < len(flip_frames) and flip_frames[fi] <= idx[i]:
            fi += 1
        if fi < len(flip_frames) and idx[i] < flip_frames[fi] <= idx[i + 1]:
            brk = True
        elif idx[i + 1] - idx[i] > gap:
            brk = True
        elif sm[i] - sm[i + 1] > min_span:
            j = min(len(sm), i + 1 + hold)
            if len(sm[i + 1:j]) and np.max(sm[i + 1:j]) < sm[i] - 200:
                brk = True
        if brk:
            pages.append((idx[start:i + 1], sm[start:i + 1]))
            start = i + 1
        i += 1
    pages.append((idx[start:], sm[start:]))
    return [(f, x) for f, x in pages if len(f) >= fps * 1.0]


def run(which):
    sm_path = rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json"
    sm = json.load(open(sm_path, encoding="utf-8"))
    raw = pickle.load(open(SCRATCH + f"/raw_{which}.pkl", "rb"))
    fps = raw["fps"]
    prof = raw["prof"]
    a_l = sm["lattice"]["px_per_semitone"]
    ph0 = sm["lattice"]["phase"]
    swatches = raw["swatches"]

    flips_in = []
    if sm.get("family") == "B" or which in ("v2", "v4"):
        from static_extract import scan_page_flips
        fps_box = []
        flips_in = scan_page_flips(which, fps_box)
    pages = playhead_pages(raw, flips=flips_in)
    print(f"{which}: {len(pages)} playhead pages ({len(flips_in)} digit flips)")
    # B-skin clears bar colors after the page's LAST NOTE, before the flip:
    # the all-colored snapshot must anchor on the last note-counter event
    events = []
    try:
        events = json.load(open(SCRATCH + f"/counter_events_{which}.json"))["events"]
    except FileNotFoundError:
        pass
    events = np.array(events)

    cap = cv2.VideoCapture(VIDEOS[which])
    t0 = time.time()
    notes = []
    flips = []
    fallback_pages = 0
    all_h = []
    bar_h = {}
    for fr_idx, xs in pages:
        cx = np.maximum.accumulate(xs)
        span = cx[-1] - cx[0]
        if span < 300:
            continue  # not a singing sweep (intro/outro artifacts)
        # robust sweep line x = c + r*f: fake playhead detections (background
        # verticals) corrupt raw crossings, but the true sweep speed is
        # constant within a page
        f_arr = np.asarray(fr_idx, float)
        step = max(1, len(f_arr) // 80)
        fs, xs2 = f_arr[::step], np.asarray(xs, float)[::step]
        rates = [(xb - xa) / (fb - fa)
                 for i, (fa, xa) in enumerate(zip(fs, xs2))
                 for fb, xb in list(zip(fs, xs2))[i + 1:] if fb - fa > len(f_arr) / 8]
        rates = [r for r in rates if 0.3 < r < 20]
        line = None
        if len(rates) >= 5:
            r = float(np.median(rates))
            c = float(np.median(xs2 - r * fs))
            inl = np.abs(np.asarray(xs, float) - (c + r * f_arr)) < 60
            if inl.mean() > 0.55:
                r = float(np.median(rates))  # keep; refit intercept on inliers
                c = float(np.median(np.asarray(xs, float)[inl] - r * f_arr[inl]))
                line = (r, c)
        end_f = int(fr_idx[-1])
        flips.append(round(end_f / fps, 3))
        # snapshot at the all-colored moment + confirmation frame
        snap_f = end_f
        if len(events):
            lo_t, hi_t = fr_idx[0] / fps, end_f / fps
            in_pg = events[(events >= lo_t) & (events <= hi_t + 0.25)]
            if len(in_pg):
                snap_f = min(end_f, int(in_pg[-1] * fps))
        snaps = []
        for back in (1, int(fps * 0.45)):
            f = max(0, snap_f - back)
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, fr = cap.read()
            if not ok:
                continue
            fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
            snaps.append(detect_bars_static(fr, prof, swatches, (a_l, ph0)))
        if len(snaps) < 2 or not snaps[0]:
            fallback_pages += 1
            continue
        rightmost = max(b for (a, b, cy, h, cls) in snaps[0])
        all_h.extend(h for (a, b, cy, h, cls) in snaps[0])
        for (a, b, cy, h, cls) in snaps[0]:
            hit = any(abs(cy - cy2) < 4 and min(b, b2) - max(a, a2) >
                      0.6 * min(b - a, b2 - a2)
                      for (a2, b2, cy2, h2, cls2) in snaps[1])
            if not hit and b < rightmost - 10:
                continue
            bar_h[len(notes)] = h  # index of the note about to be appended
            # timing: sweep-line crossing of x0 / x1 within this page
            if line is not None:
                r, c = line
                t0n = (a - c) / r / fps
                t1n = (b - c) / r / fps
                t0n = min(max(t0n, fr_idx[0] / fps - 0.5), end_f / fps)
                t1n = min(max(t1n, t0n + 0.05), end_f / fps + 0.5)
            else:
                i0 = int(np.searchsorted(cx, a))
                i1 = int(np.searchsorted(cx, b))
                if i0 >= len(fr_idx):
                    continue
                t0n = fr_idx[min(i0, len(fr_idx) - 1)] / fps
                t1n = fr_idx[min(i1, len(fr_idx) - 1)] / fps
                if i1 >= len(fr_idx):
                    t1n = end_f / fps
            if t1n - t0n < 0.04:
                t1n = t0n + 0.05
            k = int(round((cy - ph0) / a_l))
            notes.append(dict(
                t_start=round(t0n, 3), t_end=round(t1n, 3), k=-k,
                cy=round(float(cy), 1), x0=int(a), x1=int(b),
                cls=["main", "high", "low"][cls],
                first_f=int(t0n * fps), last_f=int(t1n * fps),
            ))
    cap.release()
    # bar heights are uniform in this UI: off-height static "bars" are junk
    if all_h:
        med_h = float(np.median(all_h))
        notes = [n for i, n in enumerate(notes)
                 if abs(bar_h.get(i, med_h) - med_h) <= 6]
    print(f"static bars timed by playhead: {len(notes)} "
          f"({fallback_pages} pages without snapshots) in {time.time()-t0:.0f}s")

    # TWO-EVIDENCE UNION with the tracked map: a tracked note is kept when a
    # static bar confirms its position OR a counter event corroborates its
    # timing; static bars unmatched by any tracked note are already in `notes`.
    # Junk rarely has either kind of support.
    static_notes = notes
    notes = list(static_notes)
    matched_static = set()
    kept_ev = kept_static = dropped_junk = 0
    for n in sm["notes"]:
        si = -1
        for i, s in enumerate(static_notes):
            if abs(n["cy"] - s["cy"]) < 4.5 and \
                    min(n["x1"], s["x1"]) - max(n["x0"], s["x0"]) > \
                    0.5 * min(n["x1"] - n["x0"], s["x1"] - s["x0"]) and \
                    abs(n["t_start"] - s["t_start"]) < 3.0:
                si = i
                break
        if si >= 0:
            matched_static.add(si)
            kept_static += 1
            continue  # the static version (playhead-timed) already represents it
        if which in PER_NOTE_COUNTER:
            ok = len(events) and (np.min(np.abs(events - n["t_end"])) < 0.35 or
                                  np.min(np.abs(events - n["t_start"])) < 0.35)
        else:
            # per-section counter: no per-note corroboration exists. Keep the
            # tracked note unless a DIFFERENT static bar contradicts it
            # (same x-range, different row) — absence of static support may
            # just be occlusion at the snapshot moment.
            ok = not any(abs(n["cy"] - s["cy"]) >= 4.5
                         and min(n["x1"], s["x1"]) - max(n["x0"], s["x0"]) >
                         0.7 * (n["x1"] - n["x0"])
                         and abs(n["t_start"] - s["t_start"]) < 2.5
                         for s in static_notes)
        if ok:
            notes.append(dict(n))
            kept_ev += 1
        else:
            dropped_junk += 1
    print(f"union: {len(static_notes)} static + {kept_ev} event-backed tracked "
          f"(static-confirmed tracked: {kept_static}, dropped junk: {dropped_junk})")
    notes.sort(key=lambda n: n["t_start"])

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
    # near-duplicates: same row + same x-span + starts within ~1s are one bar
    # (static and tracked versions of it that dodged the union match)
    cleaned.sort(key=lambda n: (n["t_start"], n["t_end"]))
    if NEAR_DUP.get(which):
        dedup = []
        for n in cleaned:
            dup = any(m["k"] == n["k"]
                      and min(m["x1"], n["x1"]) - max(m["x0"], n["x0"]) >
                      0.7 * min(m["x1"] - m["x0"], n["x1"] - n["x0"])
                      and abs(m["t_start"] - n["t_start"]) < 1.2
                      for m in dedup[-12:])
            if not dup:
                dedup.append(n)
        if len(dedup) != len(cleaned):
            print(f"near-dup pass: {len(cleaned)} -> {len(dedup)}")
        cleaned = dedup
    notes = enforce_monophony(cleaned)
    print(f"class+monophony: -> {len(notes)}  (khigh={khigh} klow={klow})")

    if len(notes) < 0.5 * len(sm["notes"]):
        print("ABORT: implausibly few notes; map left unchanged")
        return
    sm["notes"] = notes
    sm["n_notes"] = len(notes)
    sm["page_flips"] = flips[:-1] if flips else sm["page_flips"]
    sm["n_pages"] = len(flips)
    sm["method"] = "playhead+static"
    json.dump(sm, open(sm_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {sm_path}: {len(notes)} notes, {len(flips)} pages")


if __name__ == "__main__":
    run(sys.argv[1])
