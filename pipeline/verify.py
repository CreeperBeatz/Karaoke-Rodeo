# Verification: overlay detected notes on frames + print outlier stats.
import cv2
import numpy as np
import pickle
import json
import sys
from extract import VIDEOS, W, H

scratch = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\571acd04-1726-45ca-8d3b-d943a190ed63\scratchpad"


def load(which):
    with open(scratch + f"\\tracks_{which}.pkl", "rb") as fh:
        d = pickle.load(fh)
    notes = [dict(first_f=t[0], last_f=t[1], x0=t[2], x1=t[3], cy=t[4],
                  h=t[5], cls=t[6], first_w=t[7], growth=t[8]) for t in d["kept"]]
    return d, notes


def stats(which):
    d, notes = load(which)
    fps = d["fps"]
    a, ph0 = d["lattice"]
    print(f"{which}: {len(notes)} notes, lattice a={a:.2f} ph={ph0:.2f}")
    ys = np.array([n["cy"] for n in notes])
    res = np.abs((ys - ph0 + a / 2) % a - a / 2)
    out = res > 1.8
    print(f"lattice outliers: {out.sum()}")
    dur = np.array([(n["growth"][-1][0] - n["first_f"]) / fps for n in notes])
    wid = np.array([n["x1"] - n["x0"] for n in notes])
    hgt = np.array([n["h"] for n in notes])
    life = np.array([(n["last_f"] - n["first_f"]) / fps for n in notes])
    print(f"dur:  p5={np.percentile(dur,5):.2f} p50={np.percentile(dur,50):.2f} p95={np.percentile(dur,95):.2f} max={dur.max():.2f}")
    print(f"wid:  p5={np.percentile(wid,5):.0f} p50={np.percentile(wid,50):.0f} p95={np.percentile(wid,95):.0f}")
    print(f"hgt:  min={hgt.min()} p50={np.percentile(hgt,50):.0f} max={hgt.max()}")
    print(f"life: p50={np.percentile(life,50):.2f} p95={np.percentile(life,95):.2f} max={life.max():.2f}")
    cls = [n["cls"] for n in notes]
    print(f"cls counts: main={cls.count(0)} high={cls.count(1)} low={cls.count(2)}")
    # suspicious: tiny growth
    grew = np.array([n["x1"] - (n["x0"] + n["first_w"]) for n in notes])
    print(f"grew<3px: {(grew<3).sum()}, height<10: {(hgt<10).sum()}, outlier&short: {(out & (wid<15)).sum()}")
    return d, notes


def annotate(which, times):
    d, notes = load(which)
    fps = d["fps"]
    cap = cv2.VideoCapture(VIDEOS[which])
    for t in times:
        f = int(t * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if frame.shape[1] != W:
            frame = cv2.resize(frame, (W, H))
        lane_y0 = 52 if d["family"] == "A" else 46
        # notes visible on screen at this frame (between first and last sighting)
        for n in notes:
            if n["first_f"] <= f <= n["last_f"] + 5:
                y = int(n["cy"]) + lane_y0
                color = [(0, 255, 255), (0, 0, 255), (255, 0, 255)][n["cls"]]
                cv2.rectangle(frame, (n["x0"], y - 9), (n["x1"], y + 9), color, 1)
                cv2.putText(frame, f"{n['first_f']}", (n["x0"], y - 12),
                            cv2.FONT_HERSHEY_PLAIN, 0.7, (255, 255, 0), 1)
        out = scratch + f"\\frames\\annot_{which}_{int(t)}.jpg"
        cv2.imwrite(out, frame)
        print("wrote", out)


if __name__ == "__main__":
    which = sys.argv[1]
    d, notes = stats(which)
    ts = [float(x) for x in sys.argv[2:]] or [40, 120]
    annotate(which, ts)
