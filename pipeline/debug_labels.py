# Dump a montage of label crops + white masks for inspection.
import cv2
import numpy as np
import json
import sys
from extract import VIDEOS, W, H, Profile

scratch = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\571acd04-1726-45ca-8d3b-d943a190ed63\scratchpad"
which = sys.argv[1]
sm = json.load(open(rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json", encoding="utf-8"))
prof = Profile(sm["family"])
lane_y0 = prof.lane[1]
notes = sm["notes"][:: max(1, len(sm["notes"]) // 24)][:24]
cap = cv2.VideoCapture(VIDEOS[which])
tiles = []
for nt in notes:
    f = min(nt["last_f"], nt["first_f"] + int((nt["t_end"] - nt["t_start"]) * sm["fps"]) + 2)
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, frame = cap.read()
    if not ok:
        continue
    if frame.shape[1] != W:
        frame = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)
    cy = nt["cy"] + lane_y0
    x0 = nt["x0"]
    crop = frame[max(0, int(cy - 32)):int(cy - 6), max(0, x0 - 10):x0 + 44]
    if not crop.size:
        continue
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = ((hsv[:, :, 1] < 80) & (hsv[:, :, 2] > 170)).astype(np.uint8) * 255
    ch, cw = crop.shape[:2]
    tile = np.zeros((ch, cw * 2 + 4, 3), np.uint8)
    tile[:, :cw] = crop
    tile[:, cw + 4:] = cv2.cvtColor(white, cv2.COLOR_GRAY2BGR)
    tiles.append(cv2.resize(tile, (tile.shape[1] * 3, tile.shape[0] * 3),
                            interpolation=cv2.INTER_NEAREST))
hmax = max(t.shape[0] for t in tiles)
wmax = max(t.shape[1] for t in tiles)
grid = np.zeros((hmax * 6, wmax * 4, 3), np.uint8)
for i, t in enumerate(tiles[:24]):
    r, c = divmod(i, 4)
    grid[r * hmax:r * hmax + t.shape[0], c * wmax:c * wmax + t.shape[1]] = t
out = scratch + f"\\frames\\labels_montage_{which}.png"
cv2.imwrite(out, grid)
print(out)
