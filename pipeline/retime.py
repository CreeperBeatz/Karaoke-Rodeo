# Per-note evidence-based retiming using the playhead trace + color flips.
#
# A note's true start = the frame where the playhead crosses its x0 AND the
# bar's left end turns colored right after (pale right before). Sweep fits and
# page segmentation both failed on noisy videos; this test needs neither. A
# note with no verified crossing within the search window is junk -> dropped.
#
# Usage: python retime.py v2 [window_s]
import json, pickle, sys, time
import numpy as np
import cv2
import __main__
from extract import VIDEOS, Profile, Note, W, H, hue_dist
__main__.Profile = Profile; __main__.Note = Note
from paths import CACHE_DIR as SC, map_path  # noqa: E402
CLS = {"main": 0, "high": 1, "low": 2}


def smoothed_playhead(raw):
    """Cleaned playhead trace. The true playhead moves linearly within a page,
    so a frame deviating > 25px from a robust local line (Theil-Sen over a
    +-0.5s window) is a background vertical, not the playhead. Then median
    filter and bridge short gaps by interpolation."""
    ph = np.asarray(raw["ph_xs"]).astype(float); fps = raw["fps"]
    ph[ph < 0] = np.nan
    n = len(ph)
    half = max(6, int(0.5 * fps))
    cleaned = ph.copy()
    for i in range(n):
        if np.isnan(ph[i]):
            continue
        lo, hi = max(0, i - half), min(n, i + half + 1)
        idx = np.arange(lo, hi)
        v = ph[lo:hi]
        ok = ~np.isnan(v)
        idx, v = idx[ok], v[ok]
        if len(v) < 8:
            continue
        if len(v) > 24:  # subsample for speed
            sel = np.linspace(0, len(v) - 1, 24).astype(int)
            idx, v = idx[sel], v[sel]
        di = idx[:, None] - idx[None, :]
        dv = v[:, None] - v[None, :]
        m = di > 0
        slopes = dv[m] / di[m]
        s_ = np.median(slopes)
        b_ = np.median(v - s_ * idx)
        if abs(ph[i] - (b_ + s_ * i)) > 25:
            cleaned[i] = np.nan
    smp = np.full(n, np.nan)
    for i in range(n):
        w = cleaned[max(0, i - 4):i + 5]; w = w[~np.isnan(w)]
        if len(w) >= 3:
            smp[i] = np.median(w)
    valid = np.where(~np.isnan(smp))[0]
    for a, b in zip(valid[:-1], valid[1:]):
        if 1 < b - a < 3.0 * fps and 0 <= smp[b] - smp[a] < 60 * (b - a) / fps * 3:
            smp[a + 1:b] = np.linspace(smp[a], smp[b], b - a + 1)[1:-1]
    return smp


def crossings(smp, x0, lo, hi, fps):
    """Frames where the playhead reaches x0: an upward crossing, OR the trace
    (re)appearing at x0..x0+45 after a gap/reset (first bar of a page: the
    playhead is born at that bar, it never crosses it). Collapsed to one
    candidate per 0.5s."""
    n = len(smp)
    lo, hi = max(1, lo), min(n - 1, hi)
    cands = []
    for f in range(lo, hi):
        cur = smp[f]
        if np.isnan(cur):
            continue
        prev = smp[f - 1]
        if not np.isnan(prev) and prev < x0 <= cur and cur - prev < 60:
            cands.append(f)
        elif (np.isnan(prev) or prev - cur > 200) and x0 <= cur <= x0 + 45:
            cands.append(f)
    col = []
    for f in cands:
        if not col or f - col[-1] > 0.5 * fps:
            col.append(f)
    return col


class Frames:
    def __init__(self, path):
        self.cap = cv2.VideoCapture(path)
        self.cache = {}
    def get(self, f):
        if f in self.cache:
            return self.cache[f]
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, f))
        ok, fr = self.cap.read()
        if not ok:
            return None
        fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
        if len(self.cache) > 400:
            self.cache.pop(next(iter(self.cache)))
        self.cache[f] = fr
        return fr


def colored_frac(fr, prof, sw, n, x_from, x_to):
    lx0, ly0, lx1, ly1 = prof.lane
    cy = int(round(n["cy"]))
    y0, y1 = max(0, cy - 3), cy + 4
    x_from, x_to = max(0, x_from), min(lx1 - lx0, x_to)
    if x_to - x_from < 3:
        return 0.0
    patch = fr[ly0 + y0:ly0 + y1, lx0 + x_from:lx0 + x_to]
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    h0 = sw[CLS.get(n["cls"], 0)][0]
    hd = np.minimum(np.abs(hsv[:, :, 0].astype(int) - h0), 180 - np.abs(hsv[:, :, 0].astype(int) - h0))
    m = (hd <= 10) & (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 100)
    return float(m.mean())


def run(which, window=12.0):
    sm_path = map_path(which)
    sm = json.load(open(sm_path, encoding="utf-8"))
    raw = pickle.load(open(SC + f"/raw_{which}.pkl", "rb"))
    fps = raw["fps"]; prof = raw["prof"]; sw = raw["swatches"]
    smp = smoothed_playhead(raw); n = len(smp)
    frames = Frames(VIDEOS[which])
    dt = max(2, int(round(0.25 * fps)))
    kept, dropped, moved = [], 0, 0
    t0 = time.time()
    for nt in sm["notes"]:
        x0, x1 = nt["x0"], nt["x1"]
        fc = int(round(nt["t_start"] * fps))
        lo, hi = max(1, fc - int(window * fps)), min(n - 1, fc + int(window * fps))
        col = crossings(smp, x0, lo, hi, fps)
        best = None
        for f in sorted(col, key=lambda f: abs(f - fc)):
            fa, fb = frames.get(f + dt), frames.get(f - dt)
            if fa is None or fb is None:
                continue
            after = colored_frac(fa, prof, sw, nt, x0 + 2, min(x1 - 1, x0 + 24))
            before = colored_frac(fb, prof, sw, nt, x0 + 2, min(x1 - 1, x0 + 24))
            if after >= 0.35 and before <= 0.30:
                best = f
                break
        if best is None:
            dropped += 1
            continue
        t_new = best / fps
        # end: playhead reaching x1 after t_new
        f_end = None
        for f in range(best, min(n, best + int(15 * fps))):
            if not np.isnan(smp[f]) and smp[f] >= x1 and smp[f] - x1 < 80:
                f_end = f
                break
        if f_end is None:
            # local speed from the trace around the crossing
            seg = smp[best:best + int(fps)]
            seg = seg[~np.isnan(seg)]
            rate = (seg[-1] - seg[0]) / max(1, len(seg) - 1) if len(seg) > 3 else 3.0
            rate = rate if 0.3 < rate < 20 else 3.0
            f_end = best + max(2, int((x1 - x0) / rate))
        if abs(t_new - nt["t_start"]) > 0.15:
            moved += 1
        m = dict(nt)
        m["t_start"] = round(t_new, 3)
        m["t_end"] = round(max(f_end / fps, t_new + 0.05), 3)
        m["first_f"], m["last_f"] = best, int(f_end)
        kept.append(m)
    kept.sort(key=lambda n: (n["t_start"], n["t_end"]))
    print(f"{which}: {len(sm['notes'])} -> {len(kept)} (moved {moved}, dropped {dropped} unverifiable) "
          f"in {time.time()-t0:.0f}s")
    from monophony import enforce_monophony
    notes = enforce_monophony(kept)
    sm["notes"] = notes; sm["n_notes"] = len(notes)
    sm["method"] = sm.get("method", "") + "+retimed"
    json.dump(sm, open(sm_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {sm_path}: {len(notes)} notes")


if __name__ == "__main__":
    run(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 12.0)
