# 1:1 validation against the video's own note counter.
#
# The HUD shows a live cumulative played-note count (ノート n/total, 音数
# n/total). Every increment redraws the digits, producing a spike in
# counter_diff (mean absdiff of the counter crop between frames), which pass1
# already records. Spike events therefore give the TRUE number of notes and
# their end times, independent of bar tracking.
#
# Usage: python countercheck.py v2   (needs scratch/raw_v2.pkl + song_map)
import json
import pickle
import sys

import numpy as np

# raw pickles were written by extract.py running as __main__, so its classes
# must be visible there for unpickling
import __main__
from extract import Profile, Note
__main__.Profile = Profile
__main__.Note = Note

SCRATCH = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\1813b478-5196-4d97-b594-ec02a435b54a\scratchpad"


def counter_events(cd, fps):
    """Rising-edge spike times (seconds) in the counter-diff signal."""
    cd = np.asarray(cd, np.float64)
    base = np.median(cd)
    mad = np.median(np.abs(cd - base)) + 1e-6
    thr = base + max(6 * mad, 0.8)
    hot = cd > thr
    events = []
    f = 0
    gap = max(2, int(round(fps / 30)))  # min separation: ~2 frames @30fps
    last = -10 ** 9
    for f in range(len(hot)):
        if hot[f] and f - last > gap:
            events.append(f)
        if hot[f]:
            last = f
    return np.array(events) / fps, thr, base, mad


def run(which):
    raw = pickle.load(open(SCRATCH + f"\\raw_{which}.pkl", "rb"))
    sm = json.load(open(rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json",
                        encoding="utf-8"))
    fps = raw["fps"]
    ev, thr, base, mad = counter_events(raw["counter_diff"], fps)
    ends = np.array(sorted(n["t_end"] for n in sm["notes"]))
    print(f"{which}: counter events={len(ev)} map notes={len(ends)} "
          f"(thr={thr:.2f} base={base:.2f} mad={mad:.3f})")
    # cumulative curves sampled every 2s: where does the map fall behind?
    ts = np.arange(0, sm["duration"], 2.0)
    c_ev = np.searchsorted(ev, ts)
    c_map = np.searchsorted(ends, ts)
    diff = c_ev - c_map
    # report the intervals with the biggest growth in deficit
    d = np.diff(diff)
    worst = np.argsort(d)[::-1][:10]
    rows = [(float(ts[i]), int(d[i]), int(diff[i + 1])) for i in sorted(worst) if d[i] > 0]
    print("deficit growth (t, missing-in-window, cumulative-behind):")
    for r in rows:
        print("   t=%6.1fs  +%d  (cum %d)" % r)
    print(f"final: events {len(ev)} vs map {len(ends)}  ->  map missing "
          f"{len(ev) - len(ends)}")
    return ev


if __name__ == "__main__":
    run(sys.argv[1])
