# Geometry-first timing rebuild.
#
# Principle (confirmed on v1/v5): within a page the playhead sweeps at a constant
# rate, so every bar's timing is t = T0_page + x / R_page. Everything here is
# derived from two signals the video shows unambiguously:
#   1. the playhead itself: a NARROW, near-full-height saturated vertical line
#      of one hue (blue for family A, orange for family B). Requiring the line
#      to be isolated (columns 8px left/right NOT saturated) rejects the
#      backgrounds that fooled extract.py's playhead trace (sky, explosions).
#   2. statically detected colored bars (pageshots.detect_bars_static), each
#      assigned to the page during which it was seen.
# Every candidate is verified by the color flip at its computed t_start.
#
# Usage: python -X utf8 geotime.py v2 [scan|build|all]
#   scan  -> sequential decode, caches SC/geo_<v>.pkl (playhead runs + samples)
#   build -> pages, candidates, verification, writes output/song_map_<v>.json
import json, pickle, sys, time, os
import numpy as np
import cv2
import __main__
from extract import VIDEOS, Profile, Note, W, H
__main__.Profile = Profile; __main__.Note = Note
from pageshots import detect_bars_static
from retime import Frames, colored_frac, SC
from monophony import enforce_monophony

from paths import map_path  # noqa: E402
CLSN = ["main", "high", "low"]


# ----------------------------------------------------------------- pass 1
_LUT_CACHE = {}


def sat_mask(hsv, hue0=None):
    """uint8 mask (255) of saturated bright pixels (S>=120, V>=140), optionally
    restricted to hues within +-10 (circular) of hue0. OpenCV ops: ~0.5 ms per
    lane vs ~4 ms for the equivalent numpy expression."""
    m = cv2.inRange(hsv, (0, 120, 140), (180, 255, 255))
    if hue0 is not None:
        lut = _LUT_CACHE.get(hue0)
        if lut is None:
            hh = np.arange(256)
            lut = ((np.minimum(np.abs(hh - hue0), 180 - np.abs(hh - hue0)) <= 10) & (hh < 180)).astype(np.uint8) * 255
            _LUT_CACHE[hue0] = lut
        m = cv2.bitwise_and(m, cv2.LUT(cv2.extractChannel(hsv, 0), lut))
    return m


def playhead_runs(hsv, Hl, hue0=None, m=None):
    """Narrow isolated saturated vertical lines in the lane: [(x, hue, width)].
    With hue0 known (2nd pass) only pixels of the playhead's hue count, so a
    saturated sky/explosion of another hue cannot hide the line.
    m: precomputed sat_mask(hsv, hue0) (optional)."""
    if m is None:
        m = sat_mask(hsv, hue0)
    q = cv2.reduce(m, 0, cv2.REDUCE_SUM, dtype=cv2.CV_32S).ravel() // 255
    cand = q >= 0.72 * Hl
    n = len(q)
    if not cand.any():
        return []
    d = np.diff(np.concatenate(([0], cand.view(np.int8), [0])))
    starts = np.flatnonzero(d == 1); ends = np.flatnonzero(d == -1) - 1
    out = []
    for a, b in zip(starts.tolist(), ends.tolist()):
        w = b - a + 1
        if w > 14 or a < 3:
            continue
        la, rb = max(0, a - 8), min(n - 1, b + 8)
        if q[la] > 0.4 * Hl or q[rb] > 0.4 * Hl:
            continue
        xc = (a + b) // 2
        hues = hsv[:, xc, 0][m[:, xc] > 0]
        out.append((xc, int(np.median(hues)) if len(hues) else -1, w))
    return out


def _scan_chunk(args):
    """Worker: frames [f0, f1) of one video -> (ph runs, washed fractions, bar samples).
    Plain tuples in/out so it works in spawned processes (no __main__ pickles)."""
    path, f0, f1, family, lane, sw, lattice, hue0, step, fps = args
    from extract import Profile
    prof = Profile(family); prof.lane = tuple(lane)
    lx0, ly0, lx1, ly1 = lane; Hl = ly1 - ly0
    cap = cv2.VideoCapture(path)
    if f0 > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    ph, washed, samples = [], [], []
    for f in range(f0, f1):
        ok, fr = cap.read()
        if not ok:
            break
        if fr.shape[1] != W:
            fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(fr[ly0:ly1, lx0:lx1], cv2.COLOR_BGR2HSV)
        m_all = sat_mask(hsv)
        washed.append(cv2.countNonZero(m_all) / m_all.size)
        m = m_all if hue0 is None else sat_mask(hsv, hue0)
        ph.append(playhead_runs(hsv, Hl, hue0, m))
        if f % step == 0 and f >= fps:
            for (a, b, cy, h, cls) in detect_bars_static(fr, prof, sw, lattice):
                samples.append((f / fps, int(a), int(b), float(cy), int(cls), int(h)))
    cap.release()
    return f0, ph, washed, samples


def scan(which, step_s=0.5, hue0=None, workers=None):
    """Sequential decode of the whole video, split into `workers` frame ranges
    processed in parallel (each worker seeks to its chunk start). Output is
    identical to a single sequential pass (verified: v2 ph/washed/samples equal)."""
    raw = pickle.load(open(SC + f"/raw_{which}.pkl", "rb"))
    prof = raw["prof"]; sw = raw["swatches"]
    sm = json.load(open(map_path(which), encoding="utf-8"))
    lattice = (sm["lattice"]["px_per_semitone"], sm["lattice"]["phase"])
    cap = cv2.VideoCapture(VIDEOS[which]); fps = cap.get(cv2.CAP_PROP_FPS)
    nf = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); cap.release()
    step = max(1, int(round(step_s * fps)))
    if workers is None:
        workers = int(os.environ.get("KARAOKE_WORKERS") or 0) or max(1, min(6, (os.cpu_count() or 4) // 2))
    t0 = time.time()
    # chunk boundaries on multiples of `step` so the static-sample frames are the same set
    nchunks = max(1, workers * 2)
    bounds = [int(round(i * nf / nchunks)) for i in range(nchunks + 1)]
    bounds = sorted(set(b - b % step for b in bounds[:-1]) | {nf + 5})
    jobs = [(VIDEOS[which], bounds[i], bounds[i + 1], prof.family, tuple(prof.lane), [tuple(map(float, s)) for s in sw],
             lattice, hue0, step, fps) for i in range(len(bounds) - 1)]
    if workers > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(workers) as pool:
            parts = pool.map(_scan_chunk, jobs)
    else:
        parts = [_scan_chunk(j) for j in jobs]
    parts.sort(key=lambda p: p[0])
    ph, washed, samples = [], [], []
    for _, p_ph, p_w, p_s in parts:
        ph.extend(p_ph); washed.extend(p_w); samples.extend(p_s)
    f = len(ph)
    res = dict(fps=fps, nframes=f, ph=ph, hue0=hue0, washed=np.array(washed, np.float32), samples=samples, lane=prof.lane)
    pickle.dump(res, open(SC + f"/geo_{which}.pkl", "wb"))
    print(f"{which}: scanned {f} frames in {time.time()-t0:.0f}s ({workers} workers), {len(samples)} bar samples")
    return res


# ----------------------------------------------------------------- pass 2
def theil(ts, xs, maxn=60):
    ts = np.asarray(ts, float); xs = np.asarray(xs, float)
    if len(ts) > maxn:
        sel = np.linspace(0, len(ts) - 1, maxn).astype(int); ts, xs = ts[sel], xs[sel]
    dt = ts[:, None] - ts[None, :]; dx = xs[:, None] - xs[None, :]
    m = dt > 0.02
    if m.sum() < 3:
        return None
    R = float(np.median(dx[m] / dt[m]))
    T0 = float(np.median(ts - xs / R)) if R > 0 else None
    return (R, T0) if T0 is not None else None


def build_pages(geo):
    fps = geo["fps"]; ph = geo["ph"]
    # dominant playhead hue
    hist = np.zeros(180)
    for runs in ph:
        for (x, h, w) in runs:
            if h >= 0:
                hist[h] += 1
    circ = np.array([hist[(np.arange(i - 6, i + 7)) % 180].sum() for i in range(180)])
    hue0 = int(np.argmax(circ))
    def hd(h): return min(abs(h - hue0), 180 - abs(h - hue0))
    # per-frame pick with continuity
    det = []  # (f, x)
    prev = None
    for f, runs in enumerate(ph):
        rs = [r for r in runs if r[1] >= 0 and hd(r[1]) <= 12]
        if not rs:
            continue
        if prev is not None and f - prev[0] <= int(0.4 * fps):
            exp = prev[1] + prev[2] * (f - prev[0]) / fps
            near = [r for r in rs if abs(r[0] - exp) <= 60]
            if near:
                r = min(near, key=lambda r: abs(r[0] - exp))
                rate = prev[2]
                if f - prev[0] > 0:
                    inst = (r[0] - prev[1]) / ((f - prev[0]) / fps)
                    rate = 0.7 * prev[2] + 0.3 * inst if prev[2] else inst
                prev = (f, r[0], rate); det.append((f, r[0])); continue
        r = min(rs, key=lambda r: r[0])  # page start: leftmost
        prev = (f, r[0], 200.0); det.append((f, r[0]))
    # segment into monotone sweeps
    segs, cur = [], []
    for f, x in det:
        if cur and (x < cur[-1][1] - 60 or f - cur[-1][0] > 0.7 * fps):
            segs.append(cur); cur = []
        cur.append((f, x))
    if cur:
        segs.append(cur)
    pages = []
    for s in segs:
        if len(s) < 8 or (s[-1][0] - s[0][0]) < 0.4 * fps:
            continue
        ts = [f / fps for f, _ in s]; xs = [x for _, x in s]
        fit = theil(ts, xs)
        if fit is None:
            continue
        R, T0 = fit
        if not (60 < R < 1200):
            continue
        res = np.abs(np.array(xs) - (np.array(ts) - T0) * R)
        if np.median(res) > 8:
            continue
        pages.append(dict(t_a=ts[0], t_b=ts[-1], R=R, T0=T0, n=len(s), x_a=xs[0], x_b=xs[-1]))
    # merge consecutive pages lying on the same line (trace hole in between)
    merged = []
    for p in pages:
        if merged:
            q = merged[-1]
            pred = (p["t_a"] - q["T0"]) * q["R"]
            if abs(pred - p["x_a"]) <= 20 and p["t_a"] - q["t_b"] < 8.0 and p["x_a"] > q["x_b"]:
                q["t_b"] = p["t_b"]; q["x_b"] = p["x_b"]; q["n"] += p["n"]
                continue
        merged.append(dict(p))
    return hue0, merged


def colored_frac_strict(fr, prof, sw, n, x_from, x_to):
    """Like retime.colored_frac but with a saturation floor near the swatch's
    own saturation: separates bars (S~250) from a bar-coloured sky (S~160)."""
    lx0, ly0, lx1, ly1 = prof.lane
    cy = int(round(n["cy"])); y0, y1 = max(0, cy - 3), cy + 4
    x_from, x_to = max(0, x_from), min(lx1 - lx0, x_to)
    if x_to - x_from < 3:
        return 0.0
    patch = fr[ly0 + y0:ly0 + y1, lx0 + x_from:lx0 + x_to]
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    h0, s0, v0 = sw[CLSN.index(n["cls"])]
    hd = np.minimum(np.abs(hsv[:, :, 0].astype(int) - h0), 180 - np.abs(hsv[:, :, 0].astype(int) - h0))
    m = (hd <= 8) & (hsv[:, :, 1] >= s0 - 40) & (hsv[:, :, 2] >= 100)
    return float(m.mean())


def flip_time(frames, prof, sw, nt, t_seen, fps, max_back=4.0):
    """Frame time where the bar's left end turns colored, searching back from a
    time it was seen colored. Trace-independent. None if no pale frame found."""
    xa, xb = nt["x0"] + 2, min(nt["x1"] - 1, nt["x0"] + 24)
    def col(t):
        fr = frames.get(int(round(t * fps)))
        return None if fr is None else colored_frac(fr, prof, sw, nt, xa, xb)
    hi = t_seen
    c = col(hi)
    if c is None or c < 0.4:
        return None
    lo = hi - 0.5
    while True:
        if hi - lo > max_back + 0.5 or lo < 0:
            return None
        c = col(lo)
        if c is None:
            return None
        if c < 0.2:
            break
        lo -= 0.5
    while (hi - lo) * fps > 1.2:
        mid = (lo + hi) / 2
        c = col(mid)
        if c is None:
            return None
        if c >= 0.3:
            hi = mid
        else:
            lo = mid
    return hi


def fit_line_pts(pts):
    """pts: [(t, x)] -> (R, T0, inlier_mask) via Theil-Sen, inliers |dt| < 0.08s."""
    ts = np.array([p[0] for p in pts]); xs = np.array([p[1] for p in pts], float)
    fit = theil(ts, xs)
    if fit is None or not (60 < fit[0] < 1200):
        return None
    R, T0 = fit
    res = np.abs(ts - (T0 + xs / R))
    return R, T0, res < 0.08


def refine_page_by_flips(p, clusters, frames, prof, sw, fps, x_lo, log):
    """For a page whose playhead was (mostly) invisible: time its bars by their
    color flips and fit 1 or 2 sweep lines through (t_flip, x0)."""
    pts = []
    for c in clusters:
        if c["seen"] < 2 or c["x1"] - c["x0"] < 20 or c["x0"] < x_lo + 8:
            continue
        nt = dict(x0=int(c["x0"]), x1=int(c["x1"]), cy=float(np.median(c["cys"])), cls=CLSN[c["cls"]])
        tf = flip_time(frames, prof, sw, nt, c["t_first"], fps)
        if tf is not None:
            pts.append((tf, c["x0"]))
    if len(pts) < 4:
        return [p]
    pts.sort()
    # RANSAC over point pairs: the true sweep line(s) collect >= 4 flips each,
    # junk flips (background flicker) do not line up
    def best_line(P):
        top = None
        for i in range(len(P)):
            for j in range(i + 1, len(P)):
                (ti, xi), (tj, xj) = P[i], P[j]
                if abs(xj - xi) < 100 or tj <= ti:
                    continue
                R = (xj - xi) / (tj - ti)
                if not (60 < R < 1200):
                    continue
                T0 = ti - xi / R
                inl = [q for q in P if abs(q[0] - (T0 + q[1] / R)) < 0.08]
                if top is None or len(inl) > len(top[2]):
                    top = (R, T0, inl)
        if top is None or len(top[2]) < 4:
            return None
        fit = fit_line_pts(top[2])  # refine on inliers
        return (fit[0], fit[1], top[2]) if fit else top
    best = []
    P = list(pts)
    for _ in range(2):
        ln = best_line(P)
        if ln is None:
            break
        best.append(ln[:2])
        P = [q for q in P if q not in ln[2]]
    if not best:
        log.append(f"    page {p['vis_a']:.1f}s: {len(pts)} flips, no consistent line -> kept playhead fit")
        return [p]
    out = []
    for (R, T0) in best:
        out.append(dict(t_a=T0 + x_lo / R, t_b=p["t_b"], R=R, T0=T0, n=len(pts), x_a=x_lo, x_b=p["x_b"], flipfit=True))
    out.sort(key=lambda q: q["T0"])
    log.append(f"    page {p['vis_a']:.1f}s: {len(pts)} flips -> {len(out)} line(s) " +
               ", ".join(f"R={q['R']:.0f} T0={q['T0']:.2f}" for q in out))
    return out


def measure_sequential(path, need, plan, prof, sw):
    """One sequential pass over the video; at every frame listed in `need`
    ({frame: [(plan idx, role)]}) store the colour fractions (normal and strict)
    of that candidate's left-end patch in plan[idx]["res"]. Frames nobody needs
    are only grabbed (decoded, not converted)."""
    if not need:
        return
    cap = cv2.VideoCapture(path)
    last = max(need); f = 0; t0 = time.time()
    while f <= last:
        if f in need:
            ok, fr = cap.read()
            if not ok:
                break
            if fr.shape[1] != W:
                fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
            for i, role in need[f]:
                pl = plan[i]; nt = pl["nt"]
                pl["res"][role] = colored_frac(fr, prof, sw, nt, pl["xa"], pl["xb"])
                if role in ("b", "a"):
                    pl["res"][role + "s"] = colored_frac_strict(fr, prof, sw, nt, pl["xa"], pl["xb"])
        else:
            if not cap.grab():
                break
        f += 1
    cap.release()
    print(f"  measured {sum(len(v) for v in need.values())} patches on {len(need)} frames sequentially in {time.time()-t0:.0f}s")


def build(which, geo, out_suffix=""):
    raw = pickle.load(open(SC + f"/raw_{which}.pkl", "rb"))
    prof = raw["prof"]; sw = raw["swatches"]
    sm_path = map_path(which)
    sm = json.load(open(sm_path, encoding="utf-8"))
    a_l, ph0 = sm["lattice"]["px_per_semitone"], sm["lattice"]["phase"]
    fps = geo["fps"]; washed = geo["washed"]
    hue0, pages = build_pages(geo)
    print(f"{which}: playhead hue {hue0}, {len(pages)} pages; "
          f"R p10/50/90 = {np.percentile([p['R'] for p in pages],[10,50,90]).round(0)}")
    # family A pages tile time with a constant period P = W/R: fill holes where
    # the playhead was invisible (saturated sky) for whole pages.
    Ps = [q["T0"] - p["T0"] for p, q in zip(pages, pages[1:])]
    P = float(np.median(Ps)); Rm = float(np.median([p["R"] for p in pages]))
    regular = np.mean([abs(g / P - round(g / P)) < 0.04 for g in Ps]) > 0.8
    print(f"  T0 gaps median {P:.2f}s, regular tiling: {regular}")
    if regular:
        filled = []
        for p, q in zip(pages, pages[1:]):
            filled.append(p)
            k = int(round((q["T0"] - p["T0"]) / P))
            for j in range(1, k):
                T0 = p["T0"] + j * P
                filled.append(dict(t_a=T0 + p["x_a"] / Rm, t_b=T0 + p["x_b"] / Rm, R=Rm, T0=T0, n=0, x_a=p["x_a"], x_b=p["x_b"], filled=True))
        filled.append(pages[-1])
        # extrapolate to the song's start/end (playhead invisible on saturated skies)
        t_first = min(s[0] for s in geo["samples"]) if geo["samples"] else 0
        t_last = max(s[0] for s in geo["samples"]) if geo["samples"] else 0
        def mk(T0, ref):
            return dict(t_a=T0 + ref["x_a"] / Rm, t_b=T0 + ref["x_b"] / Rm, R=Rm, T0=T0, n=0, x_a=ref["x_a"], x_b=ref["x_b"], filled=True)
        while filled[0]["T0"] - P > t_first - P:
            filled.insert(0, mk(filled[0]["T0"] - P, filled[0]))
        while filled[-1]["T0"] + P < t_last:
            filled.append(mk(filled[-1]["T0"] + P, filled[-1]))
        print(f"  filled {len(filled) - len(pages)} missing pages (incl. extrapolated ends)")
        pages = filled
    # a page is VISIBLE from the moment the playhead reaches the first bar
    # column (x_lo) until the next page reaches it: T0 is the line's x=0 time.
    x_lo = max(0.0, float(np.percentile([s[1] for s in geo["samples"]], 5)) - 12) if geo["samples"] else 0.0
    for p in pages:
        p["vis_a"] = p["T0"] + x_lo / p["R"]
    for p, q in zip(pages, pages[1:]):
        p["t_end"] = q["vis_a"]
    pages[-1]["t_end"] = geo["nframes"] / fps
    n_before = len(pages)
    pages = [p for p in pages if p["t_end"] - p["vis_a"] > 0.3]
    if len(pages) != n_before:
        print(f"  dropped {n_before - len(pages)} degenerate pages")
        for p, q in zip(pages, pages[1:]):
            p["t_end"] = q["vis_a"]
    print(f"  x_lo {x_lo:.0f}px, page visible offset ~{x_lo / pages[0]['R']:.2f}s")
    def page_of(t):
        # page showing at time t = the latest page that became visible before t
        best = None
        for i, p in enumerate(pages):
            if p["vis_a"] <= t:
                best = i
            else:
                break
        return best
    # extra candidate frames: just before each page flip ALL its bars are colored
    frames = Frames(VIDEOS[which])
    extra = []
    for p in pages:
        for back in (0.10, 0.30):
            t = p["t_end"] - back
            if t <= p["vis_a"]:
                continue
            fr = frames.get(int(round(t * fps)))
            if fr is None:
                continue
            lat = (a_l, ph0)
            for (a, b, cy, h, cls) in detect_bars_static(fr, prof, sw, lat):
                extra.append((t, int(a), int(b), float(cy), int(cls), int(h)))
    # washed-out frames (bar-colored sky / explosions): the normal static
    # detector drowns; bars are still far more saturated (S~250 vs sky ~160),
    # so re-detect there with a strict saturation floor.
    strict_sw = [(h0, s0 + 50, v0) for (h0, s0, v0) in sw]
    n_washed = 0
    step = max(1, int(round(0.5 * fps)))
    for f in range(0, len(washed), step):
        if washed[f] > 0.5:
            fr = frames.get(f)
            if fr is None:
                continue
            n_washed += 1
            for (a, b, cy, h, cls) in detect_bars_static(fr, prof, strict_sw, (a_l, ph0)):
                extra.append((f / fps, int(a), int(b), float(cy), int(cls), int(h)))
    print(f"  {len(extra)} extra bar samples (end-of-page frames + {n_washed} washed frames re-detected strictly)")
    all_samples = sorted(geo["samples"] + extra)
    # --- candidates per page from static samples: cluster on (row, x0), x1 = max
    cands = {}  # (page, key) -> dict
    for (t, x0, x1, cy, cls, h) in all_samples:
        pi = page_of(t)
        if pi is None or t > pages[pi]["t_end"] + 0.2:
            continue
        hit = None
        for c in cands.get(pi, []):
            if abs(c["cy"] - cy) < 4 and abs(c["x0"] - x0) <= 6 and abs(c["x1"] - x1) <= 8:
                hit = c; break
        if hit:
            hit["seen"] += 1; hit["x1"] = max(hit["x1"], x1); hit["x0"] = min(hit["x0"], x0)
            hit["cys"].append(cy); hit["hs"].append(h)
        else:
            cands.setdefault(pi, []).append(dict(x0=x0, x1=x1, cy=cy, cys=[cy], hs=[h], cls=cls, seen=1, src="static", t_first=t))
    # pages whose playhead was mostly invisible: re-fit their sweep from bar flips
    log = []
    new_pages = []
    for pi, p in enumerate(pages):
        cov = (p["t_b"] - p["t_a"]) / max(0.1, p["t_end"] - p["vis_a"])
        if p.get("filled") or cov >= 0.5 or p["t_end"] - p["vis_a"] < 1.0:
            new_pages.append(p); continue
        new_pages.extend(refine_page_by_flips(p, cands.get(pi, []), frames, prof, sw, fps, x_lo, log))
    if len(new_pages) != len(pages) or any(q.get("flipfit") for q in new_pages):
        print("  flip-fit refinement:" + chr(10) + chr(10).join(log))
        pages = new_pages
        for p in pages:
            p["vis_a"] = p["T0"] + x_lo / p["R"]
        pages.sort(key=lambda q: q["vis_a"])
        for p, q in zip(pages, pages[1:]):
            p["t_end"] = q["vis_a"]
        pages[-1]["t_end"] = geo["nframes"] / fps
        # re-cluster samples against the refined pages
        cands = {}
        for (t, x0, x1, cy, cls, h) in all_samples:
            pi = page_of(t)
            if pi is None or t > pages[pi]["t_end"] + 0.2:
                continue
            hit = None
            for c in cands.get(pi, []):
                if abs(c["cy"] - cy) < 4 and abs(c["x0"] - x0) <= 6 and abs(c["x1"] - x1) <= 8:
                    hit = c; break
            if hit:
                hit["seen"] += 1; hit["x1"] = max(hit["x1"], x1); hit["x0"] = min(hit["x0"], x0)
                hit["cys"].append(cy); hit["hs"].append(h)
            else:
                cands.setdefault(pi, []).append(dict(x0=x0, x1=x1, cy=cy, cys=[cy], hs=[h], cls=cls, seen=1, src="static", t_first=t))
    hs_all = [h for c in cands.values() for cc in c for h in cc["hs"]]
    med_h = np.median(hs_all) if hs_all else 10
    # --- existing map notes as extra candidates where no static one overlaps
    n_map_added = 0
    for n in sm["notes"]:
        pi = page_of(n["t_start"] + 0.03)
        if pi is None:
            continue
        lst = cands.setdefault(pi, [])
        ov = [c for c in lst if abs(c["cy"] - n["cy"]) < 4 and min(c["x1"], n["x1"]) - max(c["x0"], n["x0"]) > 0]
        if ov:
            continue
        lst.append(dict(x0=n["x0"], x1=n["x1"], cy=n["cy"], cys=[n["cy"]], hs=[med_h], cls=CLSN.index(n["cls"]),
                        seen=1, src="map")); n_map_added += 1
    # --- time + verify
    notes = []; rej = dict(height=0, seen1=0, outside=0, flip=0, unstable=0, washed=0); n_static = 0
    t0 = time.time()
    todo = []
    for pi, lst in cands.items():
        p = pages[pi]
        for c in lst:
            if abs(np.median(c["hs"]) - med_h) > 6 or c["x1"] - c["x0"] < 12 or c["x0"] < x_lo:
                rej["height"] += 1; continue

            ts = p["T0"] + c["x0"] / p["R"]; te = p["T0"] + c["x1"] / p["R"]
            if ts < p["vis_a"] - 0.05 or te > p["t_end"] + 0.1:
                rej["outside"] += 1; continue
            todo.append((ts, te, pi, c))
    todo.sort(key=lambda z: z[0])
    dt = 0.2
    # Every candidate needs 2-3 frames (before / after its computed t_start and a
    # stability check later). Fetching them by random seek cost ~60 ms each
    # (4000 seeks = 150 s on v2), so plan all frame requests first and measure
    # the colour fractions in ONE sequential decode.
    plan = []; need = {}
    for i, (ts, te, pi, c) in enumerate(todo):
        cy = float(np.median(c["cys"]))
        k = int(round((cy - ph0) / a_l))
        nt = dict(x0=int(c["x0"]), x1=int(c["x1"]), cy=round(cy, 1), cls=CLSN[c["cls"]], k=-k)
        xa, xb = nt["x0"] + 2, min(nt["x1"] - 1, nt["x0"] + 24)
        p = pages[pi]
        fb = int(round(max(ts - dt, p["vis_a"] + 0.03) * fps)); fa = int(round(min(ts + dt, te + 0.1, p["t_end"] - 0.02) * fps))
        t_chk = min(te + 0.5, p["t_end"] - 0.05)
        fc = int(round(t_chk * fps)) if t_chk > ts + dt + 0.1 else None
        plan.append(dict(nt=nt, xa=xa, xb=xb, fb=fb, fa=fa, fc=fc, res={}))
        for f, role in ((fb, "b"), (fa, "a"), (fc, "c")):
            if f is not None and f >= 0:
                need.setdefault(f, []).append((i, role))
    measure_sequential(VIDEOS[which], need, plan, prof, sw)
    for pl, (ts, te, pi, c) in zip(plan, todo):
        nt = pl["nt"]; r = pl["res"]; p = pages[pi]; fb = pl["fb"]
        if "b" not in r or "a" not in r:
            rej["flip"] += 1; continue
        before, after = r["b"], r["a"]
        if after < 0.4:
            rej["flip"] += 1; continue
        if pl["fc"] is not None and "c" in r and r["c"] < 0.4:  # a real bar stays colored until the page flips
            rej["unstable"] += 1; continue
        if c["seen"] < 2 and c["src"] == "static" and (after < 0.6 or before > 0.15):
            rej["seen1"] += 1; continue  # seen once: demand a crisp flip
        if before > 0.3:
            if ts - p["vis_a"] < 0.15 and c["seen"] >= 3:
                pass  # first bar of the page: no pale frame exists; it is colored all page long
            elif washed[min(fb, len(washed) - 1)] > 0.5:
                # bar-coloured sky / explosion: redo the flip test with a strict saturation floor
                b2, a2 = r["bs"], r["as"]
                if b2 <= 0.3 and a2 >= 0.4:
                    rej["washed"] += 1  # counted, but accepted
                else:
                    rej["flip"] += 1; continue
            else:
                rej["flip"] += 1; continue
        nt.update(t_start=round(ts, 3), t_end=round(max(te, ts + 0.05), 3),
                  first_f=int(round(ts * fps)), last_f=int(round(te * fps)), page=pi, seen=c["seen"], src=c["src"])
        notes.append(nt); n_static += c["src"] == "static"
    print(f"  {len(todo)} candidates ({n_map_added} from old map) -> {len(notes)} verified "
          f"({n_static} static); rejected {rej}; {time.time()-t0:.0f}s")
    # --- dedupe within page: same row, x-overlap -> keep most seen / narrower
    # a bar seen >=3 times is real; among overlapping variants of a row prefer
    # the NARROWER well-seen one (touching pills merged in some frames), then the most seen
    notes.sort(key=lambda n: (n["page"], n["k"], 0 if n["seen"] >= 3 else 1, n["x1"] - n["x0"] if n["seen"] >= 3 else -n["seen"]))
    kept = []
    for n in notes:
        dup = next((m for m in kept if m["page"] == n["page"] and m["k"] == n["k"]
                    and min(m["x1"], n["x1"]) - max(m["x0"], n["x0"]) > 0.3 * min(m["x1"] - m["x0"], n["x1"] - n["x0"])), None)
        if dup is None:
            kept.append(n)
    print(f"  after dedupe {len(kept)}")
    kept.sort(key=lambda n: (n["t_start"], n["t_end"]))
    for n, m in zip(kept, kept[1:]):  # bars are x-disjoint within a page: just trim
        if n["t_end"] > m["t_start"]:
            n["t_end"] = round(max(m["t_start"] - 0.01, n["t_start"] + 0.05), 3)
    notes = kept
    sm["notes"] = notes; sm["n_notes"] = len(notes)
    sm["page_flips"] = [round(p["vis_a"], 3) for p in pages[1:]]
    sm["n_pages"] = len(pages)
    sm["pages"] = [dict(vis_a=round(p["vis_a"], 3), t_end=round(p["t_end"], 3), R=round(p["R"], 2), T0=round(p["T0"], 4)) for p in pages]
    sm["method"] = "geotime"
    sm_path = map_path(which, out_suffix)
    json.dump(sm, open(sm_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {sm_path}: {len(notes)} notes, {len(pages)} pages")


if __name__ == "__main__":
    which = sys.argv[1]; mode = sys.argv[2] if len(sys.argv) > 2 else "all"
    gp = SC + f"/geo_{which}.pkl"
    if mode in ("scan", "all") and not (mode == "all" and os.path.exists(gp)):
        geo = scan(which)
    else:
        geo = pickle.load(open(gp, "rb"))
    if mode in ("scan", "all", "rescan") and geo.get("hue0") is None:
        # 2nd pass with the playhead hue known (found from isolated detections)
        hue0, _ = build_pages(geo)
        print(f"{which}: rescanning with playhead hue {hue0}")
        geo = scan(which, hue0=hue0)
    if mode in ("build", "all"):
        build(which, geo, sys.argv[3] if len(sys.argv) > 3 else "")
