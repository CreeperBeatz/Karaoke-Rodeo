# Stage A: full-video scan. Records per-frame signals used to segment pages
# and locate bars: counter-crop diff, colored-pixel counts, playhead column.
import cv2
import numpy as np
import sys
import time

V1 = r"C:\Users\dani\Documents\karaokejiinica\【カラオケ練習用】マリーゴールド／あいみょん｜[Videoke] Mary Gold - Aimyon.mp4"
V2 = r"C:\Users\dani\Documents\karaokejiinica\【カラオケ練習用】残酷な天使のテーゼ／高橋洋子｜[Karaoke] title - _Neon Genesis EVANGELION_ Main Theme.mp4"

PROFILES = {
    "v1": {
        "counter": (175, 15, 320, 52),   # x0,y0,x1,y1 of section counter box
        "lane": (0, 55, 1280, 245),
        # HSV ranges (h,s,v) lo/hi
        "bar_main": ((94, 170, 170), (101, 255, 255)),    # cyan
        "bar_high": ((165, 200, 120), (178, 255, 255)),   # red
        "bar_low":  ((125, 120, 120), (155, 255, 255)),   # purple guess
        "playhead": ((102, 205, 170), (110, 255, 255)),
    },
    "v2": {
        "counter": (275, 14, 355, 42),
        "lane": (0, 50, 1280, 225),
        "bar_main": ((13, 170, 170), (24, 255, 255)),     # orange
        "bar_high": ((170, 200, 120), (180, 255, 255)),   # bright red guess
        "bar_low":  ((125, 120, 120), (155, 255, 255)),   # purple guess
        "playhead": ((6, 205, 140), (12, 255, 255)),
    },
}


def scan(path, profile_name, out_npz, step=1):
    p = PROFILES[profile_name]
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"{profile_name}: fps={fps:.3f} frames={n} dur={n/fps:.1f}s")
    cx0, cy0, cx1, cy1 = p["counter"]
    lx0, ly0, lx1, ly1 = p["lane"]

    counter_diff = np.zeros(n, np.float32)
    counts = np.zeros((n, 4), np.int32)  # main, high, low, playhead px counts
    ph_x = np.full(n, -1, np.int32)
    prev_counter = None
    t0 = time.time()
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        c = frame[cy0:cy1, cx0:cx1]
        if prev_counter is not None:
            counter_diff[i] = np.mean(cv2.absdiff(c, prev_counter))
        prev_counter = c

        lane = frame[ly0:ly1, lx0:lx1]
        hsv = cv2.cvtColor(lane, cv2.COLOR_BGR2HSV)
        for j, key in enumerate(["bar_main", "bar_high", "bar_low", "playhead"]):
            lo, hi = p[key]
            m = cv2.inRange(hsv, np.array(lo), np.array(hi))
            counts[i, j] = cv2.countNonZero(m)
            if key == "playhead":
                col = m.sum(axis=0) // 255
                x = int(np.argmax(col))
                if col[x] > (ly1 - ly0) * 0.5:
                    ph_x[i] = x
        i += 1
        if i % 2000 == 0:
            print(f"  {i}/{n}  {i/(time.time()-t0):.0f} fps")
    cap.release()
    np.savez_compressed(out_npz, counter_diff=counter_diff[:i], counts=counts[:i],
                        ph_x=ph_x[:i], fps=fps)
    print(f"saved {out_npz} ({i} frames, {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    scratch = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\571acd04-1726-45ca-8d3b-d943a190ed63\scratchpad"
    if which in ("v1", "both"):
        scan(V1, "v1", scratch + r"\scan_v1.npz")
    if which in ("v2", "both"):
        scan(V2, "v2", scratch + r"\scan_v2.npz")
