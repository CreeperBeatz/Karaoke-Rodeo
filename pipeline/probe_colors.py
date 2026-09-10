# Exploration: probe pixel colors in sample frames to calibrate UI element detection.
import cv2
import numpy as np
import sys

FRAMES = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\571acd04-1726-45ca-8d3b-d943a190ed63\scratchpad\frames"


def probe(img_path, points):
    img = cv2.imread(img_path)
    print(f"--- {img_path.split(chr(92))[-1]}  shape={img.shape}")
    for label, (x, y) in points.items():
        b, g, r = img[y, x]
        hsv = cv2.cvtColor(np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2HSV)[0, 0]
        print(f"{label:24s} xy=({x:4d},{y:3d})  BGR=({b:3d},{g:3d},{r:3d})  HSV=({hsv[0]:3d},{hsv[1]:3d},{hsv[2]:3d})")


# v1 frame at t=40: cyan bars, red bar (highest), gray upcoming bar, playhead ~x=889
probe(FRAMES + r"\v1_40.jpg", {
    "cyan bar fill": (150, 194),
    "cyan bar fill2": (336, 166),
    "red bar fill": (748, 80),
    "gray bar fill": (985, 99),
    "playhead line": (889, 150),
    "playhead line2": (889, 220),
    "grid area bg (sky)": (600, 210),
    "grid line?": (600, 63),
})

# v1 frame at t=120
probe(FRAMES + r"\v1_120.jpg", {
    "cyan bar": (150, 194),
    "playhead": (489, 150),
    "gray bar": (692, 128),
    "gray bar2": (1123, 212),
})

# v2 frame at t=90: orange active bar, gray bars, dark-red bar, thick orange playhead
probe(FRAMES + r"\v2_90.jpg", {
    "orange bar fill": (140, 126),
    "gray bar": (310, 104),
    "darkred bar": (443, 89),
    "playhead thick": (192, 150),
    "playhead thick2": (192, 200),
})
