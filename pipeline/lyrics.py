# Pass 3: lyric line regions + wipe timing.
# Lyric text: upcoming = white, sung = pink/red wipe moving left->right.
import cv2
import numpy as np
import json
import sys
import time
from extract import VIDEOS, W, H
from paths import map_path

REGION = (0, 500, W, 720)  # generous bottom strip


def line_bands(mask, min_h=26, max_h=80, min_px=400):
    rows = mask.sum(axis=1) / 255
    bands = []
    y = 0
    inb = False
    for i, v in enumerate(rows):
        if v > 6 and not inb:
            y, inb = i, True
        elif v <= 6 and inb:
            inb = False
            if min_h <= i - y <= max_h and mask[y:i].sum() / 255 >= min_px:
                bands.append((y, i))
    if inb and min_h <= len(rows) - y <= max_h:
        bands.append((y, len(rows)))
    return bands


def run(which, step=2):
    sm_path = map_path(which)
    sm = json.load(open(sm_path, encoding="utf-8"))
    cap = cv2.VideoCapture(VIDEOS[which])
    fps = cap.get(cv2.CAP_PROP_FPS)
    x0r, y0r, x1r, y1r = REGION
    obs = []  # (frame, band_y0, band_y1, x0, x1, pink_front, pink_frac)
    f = -1
    t0 = time.time()
    while True:
        ok = cap.grab()
        if not ok:
            break
        f += 1
        if f % step:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            break
        if frame.shape[1] != W:
            frame = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)
        crop = frame[y0r:y1r, x0r:x1r]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hch, sch, vch = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        pink = ((sch > 120) & (vch > 140) &
                (((hch >= 160) & (hch <= 178)) | (hch <= 4))).astype(np.uint8) * 255
        white = ((sch < 70) & (vch > 205)).astype(np.uint8) * 255
        text = cv2.bitwise_or(pink, white)
        # text has dark outline: erode-ish check via morphology open to drop
        # large solid background areas (clouds/moon): text strokes are thin
        opened = cv2.morphologyEx(text, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
        text = cv2.subtract(text, opened)
        for (by0, by1) in line_bands(text):
            band = text[by0:by1]
            cols = np.where(band.sum(axis=0) > 0)[0]
            if len(cols) < 30:
                continue
            bx0, bx1 = int(cols[0]), int(cols[-1])
            if bx1 - bx0 < 60:
                continue
            pband = pink[by0:by1, :]
            pcols = np.where(pband.sum(axis=0) > 255 * 2)[0]
            front = int(pcols[-1]) if len(pcols) else -1
            frac = float(len(pcols)) / max(bx1 - bx0, 1)
            obs.append((f, by0 + y0r, by1 + y0r, bx0, bx1, front, round(frac, 3)))
    cap.release()
    print(f"{which}: {len(obs)} band observations in {time.time()-t0:.0f}s")

    # group observations into line events: same band y-range & x-range persisting
    lines = []
    cur = None
    for o in obs:
        f, y0, y1, x0, x1, front, frac = o
        match = None
        for L in lines:
            if L["alive"] and abs(L["y0"] - y0) < 12 and \
               f - L["last_f"] <= step * 4 and \
               min(L["x1"], x1) - max(L["x0"], x0) > 0.5 * (x1 - x0):
                match = L
                break
        if match:
            match["last_f"] = f
            match["x0"] = min(match["x0"], x0)
            match["x1"] = max(match["x1"], x1)
            if front >= 0:
                match["wipe"].append((round(f / fps, 2), front))
        else:
            lines.append(dict(first_f=f, last_f=f, y0=y0, y1=y1, x0=x0, x1=x1,
                              wipe=[(round(f / fps, 2), front)] if front >= 0 else [],
                              alive=True))
        for L in lines:
            if L["alive"] and f - L["last_f"] > step * 6:
                L["alive"] = False
    out = []
    for L in lines:
        if L["last_f"] - L["first_f"] < 8:
            continue
        out.append(dict(
            t_show=round(L["first_f"] / fps, 2), t_hide=round(L["last_f"] / fps, 2),
            bbox=[L["x0"], L["y0"], L["x1"], L["y1"]],
            wipe=L["wipe"][::3][:400],
        ))
    print(f"{which}: {len(out)} lyric lines")
    sm["lyrics"] = out
    json.dump(sm, open(sm_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", sm_path)


if __name__ == "__main__":
    run(sys.argv[1])
