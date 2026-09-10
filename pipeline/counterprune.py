# Prune map notes not corroborated by the video's own note counter.
#
# For videos whose HUD counter increments PER NOTE (family-B layout: v2, v4),
# every real note's end coincides with a counter event (verified: median
# offset ~0.01s). A note whose end AND start are both far from every event is
# background junk that slipped through the color/lattice/geometry gates.
# Burst-merged events undercount, but bursts are dense, so real notes in a
# burst still sit within the window of SOME event.
#
# Usage: python counterprune.py v2 [window]
import json
import sys

import numpy as np

SCRATCH = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\1813b478-5196-4d97-b594-ec02a435b54a\scratchpad"


def run(which, window=0.5):
    sm_path = rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json"
    sm = json.load(open(sm_path, encoding="utf-8"))
    ev = np.array(json.load(open(SCRATCH + f"/counter_events_{which}.json"))["events"])
    keep, drop = [], []
    for n in sm["notes"]:
        d = min(np.min(np.abs(ev - n["t_end"])), np.min(np.abs(ev - n["t_start"])))
        (keep if d <= window else drop).append(n)
    sm["notes"] = keep
    sm["n_notes"] = len(keep)
    json.dump(sm, open(sm_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{which}: {len(keep) + len(drop)} -> {len(keep)} "
          f"(pruned {len(drop)} uncorroborated)")
    for n in drop[:15]:
        print(f"   dropped t={n['t_start']:.2f}-{n['t_end']:.2f} k={n['k']} "
              f"x={n['x0']}-{n['x1']} cls={n['cls']}")


if __name__ == "__main__":
    run(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 0.5)
