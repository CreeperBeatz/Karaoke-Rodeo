# Geometry-first note cleanup. Key facts (user-confirmed): within a page every
# bar has a FIXED screen position; the playhead sweeps left->right at constant
# speed and bars only change color as it passes. Therefore:
#   * time maps linearly to x within a page (t = b + s*x),
#   * a bar's duration is exactly its pixel width * s,
#   * within one page, two bars can never overlap in x AND time -> such a
#     collision means a duplicate track or a background ghost,
#   * the lane is monophonic -> any residual time overlap is a smear.
#
# Recall-first: notes are only removed on physical impossibility (coexisting
# x-collisions) or clear sweep-line deviation while colliding. Two bars at the
# same x but far apart in time are on DIFFERENT sweeps (a missed page flip),
# never deleted. Pages are segmented by x-monotonicity (a sweep restart is an
# x reset confirmed by two consecutive notes), not by trusting flip detection.
#
# Usage as a script: cleans output/song_map_*.json in place, writing a
# cleanup_log_*.json sidecar with every removal/merge and its reason.
import bisect
import glob
import json
import os
import sys
from statistics import median

EPS = 1e-6
MIN_DUR = 0.035     # final notes shorter than this are dropped
SLIVER = 0.02       # ownership slivers shorter than this don't break a note
CONTAIN_TOL = 0.02  # containment tolerance for duplicate detection
X_RESET = 80        # px the next bar must jump left to start a new sweep


def _pitch(n):
    return n.get("midi", n.get("k"))


def _brief(n):
    return dict(t=n["t_start"], t1=n["t_end"], p=_pitch(n), x0=n["x0"], x1=n["x1"])


def undo_splits(notes, fps=None):
    """Re-join note segments that share the same source track (identical
    geometry), restoring t_start from first_f where available."""
    best = {}
    for n in notes:
        key = (n.get("first_f"), n["x0"], n["x1"], n.get("cy"), _pitch(n))
        if key in best:
            b = best[key]
            b["t_start"] = min(b["t_start"], n["t_start"])
            b["t_end"] = max(b["t_end"], n["t_end"])
        else:
            best[key] = dict(n)
    out = list(best.values())
    if fps:
        for n in out:
            if n.get("first_f") is not None:
                n["t_start"] = round(n["first_f"] / fps, 3)
    out.sort(key=lambda n: (n["t_start"], n["t_end"]))
    return out


def _sweeps(notes, flips=()):
    """Segment time-sorted notes into playhead sweeps purely by x-monotonicity
    (detected page flips are over-detected and would fragment groups). A new
    sweep = an x reset confirmed by the following note; a LONE left-field note
    (washed-out bar rescued late, or a ghost) becomes an orphan attached to
    the sweep active at its timestamp, where the fit can retime it."""
    notes = sorted(notes, key=lambda n: (n["t_start"], n["x0"]))
    groups, cur, orphans = [], [], []
    hi = None
    for i, n in enumerate(notes):
        if cur and hi is not None and n["x0"] < hi - X_RESET:
            nxt = notes[i + 1] if i + 1 < len(notes) else None
            if nxt is not None and nxt["x0"] < hi - X_RESET / 2:
                groups.append(cur)
                cur, hi = [], None
            else:
                orphans.append(n)
                continue
        cur.append(n)
        hi = n["x1"] if hi is None else max(hi, n["x1"])
    if cur:
        groups.append(cur)
    for o in orphans:
        g = min(groups, key=lambda g:
                0 if g[0]["t_start"] - 0.5 <= o["t_start"] <= g[-1]["t_end"] + 0.5
                else abs(o["t_start"] - g[0]["t_start"]))
        g.append(o)
    return groups


def _sweep_fit(ns):
    """Robust (Theil-Sen) fit of the playhead sweep t = b + s*x from note
    starts within one sweep. Returns (s, b) or None if unreliable."""
    pts = [(n["x0"], n["t_start"]) for n in ns]
    slopes = [(tb - ta) / (xb - xa)
              for i, (xa, ta) in enumerate(pts)
              for xb, tb in pts[i + 1:] if abs(xb - xa) > 30]
    slopes = [s for s in slopes if 0.002 < s < 0.05]  # sane sec/px range
    if len(slopes) < 3:
        return None
    s = median(slopes)
    b = median(t - s * x for x, t in pts)
    resid = median(abs(t - (b + s * x)) for x, t in pts)
    if resid > 0.25:
        return None
    return s, b


def _retime(n, s):
    n["t_end"] = round(n["t_start"] + max((n["x1"] - n["x0"]) * s, MIN_DUR + 0.005), 3)


def clean_notes(notes, flips, fps=None, events=None, solo_offsweep=False):
    """undo_splits -> sweep segmentation -> geometric retiming -> collision
    dedupe (duplicate union / ghost drop) -> monophony enforcement.
    solo_offsweep: additionally drop multi-frame tracks far off the sweep line
    even without a collision (junk colored at random times); single-frame
    wash rescues are exempt and get retimed instead."""
    log = events if events is not None else []
    notes = undo_splits(notes, fps)
    groups = _sweeps(notes, flips)
    fits = [_sweep_fit(g) for g in groups]
    good = [f for f in fits if f]
    s_global = median(s for s, _ in good) if good else None
    out = []
    for g, fit in zip(groups, fits):
        s = fit[0] if fit else s_global
        resid = None
        if fit:
            # original deviation from the sweep line = track quality score
            sf, bf = fit
            resid = {id(n): abs(n["t_start"] - (bf + sf * n["x0"])) for n in g}
            if solo_offsweep and len(g) >= 5:
                for n in list(g):
                    life = (n.get("last_f") or 0) - (n.get("first_f") or 0)
                    if resid[id(n)] > 0.7 and life >= 2:
                        g.remove(n)
                        log.append(dict(stage="dedupe", reason="offsweep-solo",
                                        removed=_brief(n)))
            # position is truth: a bar first seen late (wash-out flash, late
            # rescue) still STARTS where the sweep crossed its x0
            for n in g:
                if resid[id(n)] > 0.25:
                    n["t_start"] = round(bf + sf * n["x0"], 3)
        if s is not None:
            for n in g:
                _retime(n, s)
        kept = []
        for n in sorted(g, key=lambda n: (n["x0"], n["x1"])):
            drop = False
            for m in list(kept):
                ov = min(m["x1"], n["x1"]) - max(m["x0"], n["x0"])
                wmin = min(m["x1"] - m["x0"], n["x1"] - n["x0"])
                if wmin <= 0 or ov < 0.6 * wmin:
                    continue
                coexist = min(m["t_end"], n["t_end"]) - max(m["t_start"], n["t_start"]) > 0
                if coexist and _pitch(m) == _pitch(n):
                    # duplicate tracks of one bar: union, re-derive end from width
                    log.append(dict(stage="dedupe", reason="dup-union",
                                    removed=_brief(n), into=_brief(m)))
                    m["x0"], m["x1"] = min(m["x0"], n["x0"]), max(m["x1"], n["x1"])
                    m["t_start"] = min(m["t_start"], n["t_start"])
                    if s is not None:
                        _retime(m, s)
                    else:
                        m["t_end"] = max(m["t_end"], n["t_end"])
                    drop = True
                    break
                if coexist:
                    # two pitches can't sound at once: drop the worse sweep fit
                    rn = resid[id(n)] if resid else (n["x1"] - n["x0"]) * -1
                    rm = resid[id(m)] if resid else (m["x1"] - m["x0"]) * -1
                    loser, winner = (n, m) if rn >= rm else (m, n)
                    log.append(dict(stage="dedupe", reason="ghost-coexist",
                                    removed=_brief(loser), kept=_brief(winner)))
                    if loser is n:
                        drop = True
                        break
                    kept.remove(m)
                elif resid is not None:
                    # same x, different times: usually a missed flip (keep both);
                    # drop only a clear sweep outlier colliding with an inlier
                    rn, rm = resid[id(n)], resid[id(m)]
                    if rn > 0.5 and rm < 0.3:
                        log.append(dict(stage="dedupe", reason="ghost-offsweep",
                                        removed=_brief(n), kept=_brief(m)))
                        drop = True
                        break
                    if rm > 0.5 and rn < 0.3:
                        log.append(dict(stage="dedupe", reason="ghost-offsweep",
                                        removed=_brief(m), kept=_brief(n)))
                        kept.remove(m)
            if not drop:
                kept.append(n)
        out.extend(kept)
    out.sort(key=lambda n: (n["t_start"], n["t_end"]))
    return enforce_monophony(out, events=log)


def enforce_monophony(notes, min_dur=MIN_DUR, events=None):
    log = events if events is not None else []
    notes = sorted(notes, key=lambda n: (n["t_start"], n["t_end"]))
    # 1) drop duplicates: a note fully contained in an earlier same-pitch note
    kept = []
    for n in notes:
        dup = next((m for m in kept if _pitch(m) == _pitch(n)
                    and m["t_start"] <= n["t_start"] + CONTAIN_TOL
                    and m["t_end"] >= n["t_end"] - CONTAIN_TOL), None)
        if dup is None:
            kept.append(n)
        else:
            log.append(dict(stage="monophony", reason="contained-dup",
                            removed=_brief(n), kept=_brief(dup)))
    notes = kept
    # 2) sweep: between consecutive boundaries, the latest-starting active
    # note owns the interval ("last note wins")
    bounds = sorted({t for n in notes for t in (n["t_start"], n["t_end"])})
    segs = []  # [a, b, note_index]
    for a, b in zip(bounds, bounds[1:]):
        owner, best = None, None
        for i, n in enumerate(notes):
            if n["t_start"] <= a + EPS and n["t_end"] >= b - EPS:
                if best is None or n["t_start"] > best:
                    owner, best = i, n["t_start"]
        if owner is not None:
            segs.append([a, b, owner])
    # 3) drop ownership slivers, then re-join a note split by a dropped sliver
    segs = [s for s in segs if s[1] - s[0] >= SLIVER]
    merged = []
    for s in segs:
        if merged and merged[-1][2] == s[2] and s[0] - merged[-1][1] <= min_dur + EPS:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    covered = set()
    out = []
    for a, b, i in merged:
        if b - a < min_dur:
            continue
        covered.add(i)
        n = dict(notes[i])
        n["t_start"], n["t_end"] = round(a, 3), round(b, 3)
        out.append(n)
    for i, n in enumerate(notes):
        if i not in covered:
            log.append(dict(stage="monophony", reason="shadowed", removed=_brief(n)))
    return out


def count_overlaps(notes, tol=0.001):
    notes = sorted(notes, key=lambda n: n["t_start"])
    return sum(1 for a, b in zip(notes, notes[1:]) if a["t_end"] - b["t_start"] > tol)


def clean_file(path):
    with open(path, encoding="utf-8") as fh:
        sm = json.load(fh)
    before, ov_before = len(sm["notes"]), count_overlaps(sm["notes"])
    events = []
    sm["notes"] = clean_notes(sm["notes"], sm["page_flips"], sm.get("fps"), events)
    sm["n_notes"] = len(sm["notes"])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(sm, fh, ensure_ascii=False, indent=1)
    log_path = path.replace("song_map_", "cleanup_log_")
    with open(log_path, "w", encoding="utf-8") as fh:
        json.dump(events, fh, ensure_ascii=False, indent=1)
    from collections import Counter
    reasons = Counter(e["reason"] for e in events)
    print(f"{os.path.basename(path)}: {before} -> {len(sm['notes'])} notes, "
          f"overlaps {ov_before} -> {count_overlaps(sm['notes'])}, {dict(reasons)}")


if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    for path in sorted(glob.glob(os.path.join(outdir, "song_map_*.json"))):
        clean_file(path)
