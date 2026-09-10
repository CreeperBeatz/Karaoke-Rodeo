# Add missing bars: sample the video every ~0.5s, statically detect colored
# bars, cluster repeats, and time each new bar by the playhead-crossing +
# color-flip test (same evidence rule as retime.py). No page segmentation.
# Usage: python addstatic.py v2
import json, pickle, sys, time
import numpy as np
import cv2
import __main__
from extract import VIDEOS, Profile, Note, W, H
__main__.Profile = Profile; __main__.Note = Note
from pageshots import detect_bars_static
from retime import Frames, colored_frac, SC, smoothed_playhead, crossings
from monophony import enforce_monophony


def find_flip(frames, prof, sw, nt, xa, xb, t_hi, fps, max_back=16.0):
    """Trace-independent timing: the bar region [xa, xb] is colored at t_hi;
    step back until it is pale, then binary-search the color-flip frame."""
    def col(t):
        fr = frames.get(int(round(t * fps)))
        return None if fr is None else colored_frac(fr, prof, sw, nt, xa, xb)
    c = col(t_hi)
    if c is None or c < 0.35:
        return None
    t, t_lo = t_hi, None
    while t_hi - t < max_back:
        t -= 0.4
        if t < 0:
            return None
        c = col(t)
        if c is None:
            return None
        if c < 0.2:
            t_lo = t
            break
    if t_lo is None:
        return None
    lo, hi = t_lo, t_lo + 0.4
    while (hi - lo) * fps > 1.5:
        mid = (lo + hi) / 2
        c = col(mid)
        if c is None:
            return None
        if c >= 0.3:
            hi = mid
        else:
            lo = mid
    return hi


def run(which, step_s=0.5):
    sm_path = rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json"
    sm = json.load(open(sm_path, encoding="utf-8"))
    raw = pickle.load(open(SC + f"/raw_{which}.pkl", "rb"))
    fps = raw["fps"]; prof = raw["prof"]; sw = raw["swatches"]
    a_l, ph0 = sm["lattice"]["px_per_semitone"], sm["lattice"]["phase"]
    smp = smoothed_playhead(raw); n = len(smp)
    frames = Frames(VIDEOS[which])
    t0 = time.time()
    # 1) sample colored bars through the song
    samples = []  # (t, x0, x1, cy, cls)
    step = max(1, int(step_s * fps))
    for f in range(int(2 * fps), n - step, step):
        fr = frames.get(f)
        if fr is None:
            continue
        for (a, b, cy, h, cls) in detect_bars_static(fr, prof, sw, (a_l, ph0)):
            samples.append((f / fps, a, b, cy, cls, h))
    frames.cache.clear()
    hs = [s[5] for s in samples]
    med_h = np.median(hs) if hs else 0
    samples = [s for s in samples if abs(s[5] - med_h) <= 6]
    # 2) cluster repeats: same row, same span (±8px), within 10s
    samples.sort()
    clusters = []
    for s in samples:
        t, a, b, cy, cls, h = s
        hit = None
        for c in reversed(clusters):
            if t - c["t_last"] > 10:
                break
            if abs(c["cy"] - cy) < 4 and abs(c["x0"] - a) <= 8 and abs(c["x1"] - b) <= 8:
                hit = c
                break
        if hit:
            hit["t_last"] = t; hit["seen"] += 1
            hit["x0"] = min(hit["x0"], a); hit["x1"] = max(hit["x1"], b)
        else:
            clusters.append(dict(t_first=t, t_last=t, x0=a, x1=b, cy=cy, cls=cls, seen=1))
    print(f"{which}: {len(samples)} bar samples -> {len(clusters)} candidate bars "
          f"({time.time()-t0:.0f}s)")
    # 3) time each candidate by playhead crossing + color flip, skip ones the map has
    notes = list(sm["notes"])
    dt = max(2, int(round(0.25 * fps)))
    added = skipped = unver = replaced = flipped = 0
    CLSN = ["main", "high", "low"]
    for c in clusters:
        x0, x1, cy = int(c["x0"]), int(c["x1"]), c["cy"]
        k = int(round((cy - ph0) / a_l))
        nt = dict(x0=x0, x1=x1, cy=round(float(cy), 1), cls=CLSN[c["cls"]], k=-k)
        lo = max(1, int((c["t_first"] - 20) * fps)); hi = min(n - 1, int((c["t_last"] + 1) * fps))
        col = crossings(smp, x0, lo, hi, fps)
        # PREFER the direct color-flip search anchored on the observed colored
        # time: it stays inside the bar's own page even when a previous page
        # has an identical layout (trace crossings can pick that wrong page
        # when the true crossing sits in a trace hole).
        t_new = None
        if c["seen"] >= 2 and x1 - x0 >= 12:
            t_new = find_flip(frames, prof, sw, nt, x0 + 2, min(x1 - 1, x0 + 24), c["t_first"], fps)
            if t_new is not None:
                flipped += 1
        if t_new is None:
            best = None
            for f in sorted(col, key=lambda f: abs(f - c["t_first"] * fps)):
                if abs(f / fps - c["t_first"]) > 10:
                    break
                fa, fb = frames.get(f + dt), frames.get(f - dt)
                if fa is None or fb is None:
                    continue
                if colored_frac(fa, prof, sw, nt, x0 + 2, min(x1 - 1, x0 + 24)) >= 0.35 and                    colored_frac(fb, prof, sw, nt, x0 + 2, min(x1 - 1, x0 + 24)) <= 0.30:
                    best = f
                    break
            if best is not None:
                t_new = best / fps
        if t_new is None:
            unver += 1
            continue
        # already in map? same row, overlapping span, same time. A matched map
        # note much WIDER than the bar is a tracking smear spanning several
        # bars: replace it with the static geometry.
        match = [m for m in notes if m["k"] == nt["k"] and abs(m["t_start"] - t_new) < 0.6
                 and min(m["x1"], x1) - max(m["x0"], x0) > 0.4 * min(x1 - x0, m["x1"] - m["x0"])]
        if match:
            wide = [m for m in match if (m["x1"] - m["x0"]) > 1.4 * (x1 - x0) + 6]
            if not wide:
                skipped += 1
                continue
            for m in wide:
                notes.remove(m)
            replaced += 1
        best = int(round(t_new * fps))
        f_end = None
        for f in range(best, min(n, best + int(15 * fps))):
            if not np.isnan(smp[f]) and smp[f] >= x1 and smp[f] - x1 < 80:
                f_end = f
                break
        if f_end is None:
            t_e = find_flip(frames, prof, sw, nt, max(x0 + 1, x1 - 24), x1 - 2, c["t_last"], fps)
            if t_e is not None and t_e > t_new:
                f_end = int(round(t_e * fps))
        if f_end is None:
            f_end = best + max(2, int((x1 - x0) / 3.0))
        nt.update(t_start=round(t_new, 3), t_end=round(max(f_end / fps, t_new + 0.05), 3),
                  first_f=best, last_f=int(f_end))
        notes.append(nt)
        added += 1
    print(f"added {added} (replacing {replaced} smears, {flipped} timed by color-flip search), already present {skipped}, unverifiable {unver} ({time.time()-t0:.0f}s)")
    notes.sort(key=lambda n: (n["t_start"], n["t_end"]))
    notes = enforce_monophony(notes)
    sm["notes"] = notes; sm["n_notes"] = len(notes)
    sm["method"] = sm.get("method", "") + "+addstatic"
    json.dump(sm, open(sm_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {sm_path}: {len(notes)} notes")


if __name__ == "__main__":
    run(sys.argv[1])
