# Crop and enlarge label areas from sample frames for visual inspection.
import cv2

FRAMES = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\571acd04-1726-45ca-8d3b-d943a190ed63\scratchpad\frames"

jobs = [
    # (img, x0, y0, x1, y1, out)  regions around labels
    ("v1_40.jpg", 30, 155, 300, 210, "lab_v1_a.png"),   # シ + bar, レ label
    ("v1_40.jpg", 560, 90, 920, 180, "lab_v1_b.png"),   # シ (red bar), ラ labels
    ("v1_120.jpg", 250, 130, 460, 185, "lab_v1_c.png"), # ド# レ labels
    ("v2_90.jpg", 60, 75, 420, 140, "lab_v2_a.png"),    # ソ シ ド labels
    ("v2_90.jpg", 480, 100, 720, 160, "lab_v2_b.png"),  # ファ ミ + arrows
]
for img, x0, y0, x1, y1, out in jobs:
    im = cv2.imread(f"{FRAMES}\\{img}")
    crop = im[y0:y1, x0:x1]
    big = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(f"{FRAMES}\\{out}", big)
    print(out, big.shape)
