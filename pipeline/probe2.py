# Probe upcoming vs passed color states of high/low (red/purple) bars in v1.
import cv2
import numpy as np
from extract import VIDEOS, W, H

cap = cv2.VideoCapture(VIDEOS["v1"])
fps = 30.0


def grab(t):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ok, fr = cap.read()
    return fr


def probe(fr, pts, label):
    hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
    for (x, y) in pts:
        h, s, v = hsv[y, x]
        print(f"{label} ({x:4d},{y:3d}) HSV=({h:3d},{s:3d},{v:3d})")


# purple lowest bar visible upcoming at t=41.5 at ~(1090-1158, y~233-247)
fr = grab(41.5)
probe(fr, [(1110, 240), (1130, 240), (1145, 240)], "purple upcoming t=41.5")
# same bar after wipe (page ends ~46s; try t=45.9)
for t in (45.5, 45.9, 46.2):
    fr = grab(t)
    probe(fr, [(1110, 240), (1130, 240)], f"purple maybe-passed t={t}")

# red highest bar: visible at t=40 (already passed) at (640-857, y=80)
# find its upcoming state earlier in the page: page with 区間9 spans ~36.5-41.3s;
# bar wiped around t~39.5; check t=37.5 (upcoming)
fr = grab(37.5)
probe(fr, [(700, 80), (750, 80), (820, 80)], "red upcoming t=37.5")
fr = grab(40.0)
probe(fr, [(700, 80), (750, 80), (820, 80)], "red passed   t=40.0")
