# Fast scan of the video's live note counter (ノート n/total, 音数 n/total).
# Decode-only: crops the count digits at native resolution each frame and
# records the frame-to-frame diff; each increment redraws digits -> a spike.
# Spike count == the video's true note total; spike times == note END times.
#
# Usage: python notecounter.py v2   -> prints validation vs song_map, saves
# events to <scratch>/counter_events_<which>.json
import json
import sys
import time

import cv2
import numpy as np

from extract import VIDEOS

SCRATCH = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\1813b478-5196-4d97-b594-ec02a435b54a\scratchpad"
# note-count digit boxes in 1280x720 space, tightened to exclude box edges
# and label glyphs (their sub-pixel shimmer flaps the state hash)
CROPS = {"A": (55, 18, 150, 46), "B": (70, 16, 193, 39)}
# v4 uses the B-layout HUD with a dark box (family detection falls back to A)
VIDEO_CROPS = {"v4": (70, 16, 193, 39)}


def scan(which):
    sm = json.load(open(rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json",
                        encoding="utf-8"))
    cap = cv2.VideoCapture(VIDEOS[which])
    fps = cap.get(cv2.CAP_PROP_FPS)
    vw = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    vh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    sx, sy = vw / 1280.0, vh / 720.0
    x0, y0, x1, y1 = VIDEO_CROPS.get(which) or CROPS[sm["family"]]
    x0, x1 = int(x0 * sx), int(x1 * sx)
    y0, y1 = int(y0 * sy), int(y1 * sy)
    # count STABLE-STATE transitions of the binarized digit region: a counter
    # increment changes the white-digit pattern and the new pattern persists;
    # redraw animation frames are transient and never form a stable state
    states = []  # (start_frame, hash)
    prev_hash, run, run_start = None, 0, 0
    stable = []  # (frame, hash) of accepted stable states
    MIN_RUN = 3
    t0 = time.time()
    f = -1
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        f += 1
        c = fr[y0:y1, x0:x1]
        g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
        m = cv2.resize((g > 180).astype(np.uint8), (24, 8),
                       interpolation=cv2.INTER_AREA)
        hsh = (m > 0.5).tobytes()
        if hsh == prev_hash:
            run += 1
        else:
            prev_hash, run, run_start = hsh, 1, f
        if run == MIN_RUN:
            # require a real digit change (>=3 of 192 cells), not 1-cell shimmer
            if not stable:
                stable.append((run_start, hsh))
            elif stable[-1][1] != hsh:
                a = np.frombuffer(stable[-1][1], np.uint8)
                b = np.frombuffer(hsh, np.uint8)
                if int(np.sum(a != b)) >= 3:
                    stable.append((run_start, hsh))
    cap.release()
    print(f"{which}: scanned {f+1} frames in {time.time()-t0:.0f}s, "
          f"{len(stable)} stable counter states")
    ev = np.array([s[0] / fps for s in stable[1:]])  # transitions
    ends = np.array(sorted(n["t_end"] for n in sm["notes"]))
    # ignore events far outside the sung span (intro/outro HUD animations)
    lo, hi = ends[0] - 8, ends[-1] + 8
    ev_in = ev[(ev >= lo) & (ev <= hi)]
    print(f"{which}: counter events={len(ev_in)} (raw {len(ev)}), map notes={len(ends)}")
    ts = np.arange(0, sm["duration"], 2.0)
    d = np.searchsorted(ev_in, ts) - np.searchsorted(ends, ts)
    dd = np.diff(d)
    worst = [i for i in np.argsort(dd)[::-1][:12] if dd[i] > 1]
    print("deficit windows (t, missing, cumulative):")
    for i in sorted(worst):
        print("   t=%6.1fs  +%d  (cum %d)" % (ts[i], dd[i], d[i + 1]))
    json.dump(dict(events=[round(float(t), 3) for t in ev_in]),
              open(SCRATCH + f"\\counter_events_{which}.json", "w"))
    print(f"final: video says {len(ev_in)} notes, map has {len(ends)} "
          f"-> missing {len(ev_in) - len(ends)}")


if __name__ == "__main__":
    scan(sys.argv[1])
