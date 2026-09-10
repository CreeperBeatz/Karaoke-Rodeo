# Analyze scan npz: derive page boundaries from counter-crop diffs and
# playhead resets; sanity-check against expected page counts.
import numpy as np
import sys

scratch = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\571acd04-1726-45ca-8d3b-d943a190ed63\scratchpad"


def analyze(name, expected_pages):
    d = np.load(scratch + f"\\scan_{name}.npz")
    cd, counts, ph, fps = d["counter_diff"], d["counts"], d["ph_x"], float(d["fps"])
    n = len(cd)
    print(f"=== {name}: {n} frames fps={fps}")
    print(f"counter_diff: mean={cd.mean():.3f} p50={np.percentile(cd,50):.3f} "
          f"p95={np.percentile(cd,95):.3f} p99={np.percentile(cd,99):.3f} max={cd.max():.1f}")
    # counter transitions: frames where diff much larger than local baseline
    thr = max(cd.mean() * 6, np.percentile(cd, 99) * 0.8, 2.0)
    hits = np.where(cd > thr)[0]
    # merge consecutive frames into events
    events = []
    for f in hits:
        if events and f - events[-1][-1] <= 3:
            events[-1].append(f)
        else:
            events.append([f])
    print(f"thr={thr:.2f} -> {len(events)} counter-change events (expect ~{expected_pages-1}-{expected_pages+1})")
    for e in events[:8]:
        print(f"   event at frame {e[0]} t={e[0]/fps:.2f}s len={len(e)}")
    # playhead stats
    valid = ph >= 0
    print(f"playhead detected in {valid.sum()}/{n} frames ({100*valid.mean():.1f}%)")
    # playhead resets (x drops by > 200 px)
    pv = np.where(valid)[0]
    resets = []
    for a, b in zip(pv[:-1], pv[1:]):
        if b - a < int(fps) and ph[b] < ph[a] - 200:
            resets.append(b)
    print(f"playhead resets: {len(resets)}")
    # bar-color pixel counts summary
    for j, k in enumerate(["main", "high", "low", "playhd"]):
        c = counts[:, j]
        print(f"px[{k:6s}]: p50={np.percentile(c,50):7.0f} p90={np.percentile(c,90):7.0f} max={c.max():7.0f}")
    return events


analyze("v1", 67)
analyze("v2", 36)
