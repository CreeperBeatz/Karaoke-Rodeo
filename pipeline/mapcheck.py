# Visual check: frame at time t with map notes of that page overlaid.
# green = note already started at t (should be colored on screen),
# yellow = upcoming note (should be pale on screen). Red dots = playhead x.
# Usage: python mapcheck.py v2 45.0 120.0 200.0
import json, sys, pickle
import cv2, numpy as np
import __main__
from extract import VIDEOS, Profile, Note, W, H
__main__.Profile = Profile; __main__.Note = Note
from paths import CACHE_DIR as SC  # noqa: E402
which = sys.argv[1]; base = which.split(".")[0]
sm = json.load(open(rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json", encoding="utf-8"))
raw = pickle.load(open(SC + f"/raw_{base}.pkl", "rb"))
prof = raw["prof"]; lx0, ly0 = prof.lane[0], prof.lane[1]
cap = cv2.VideoCapture(VIDEOS[base]); fps = cap.get(cv2.CAP_PROP_FPS)
flips = sorted(sm["page_flips"])
tiles = []
for t in map(float, sys.argv[2:]):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps)); ok, fr = cap.read()
    fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
    vis = fr[:270].copy()
    import bisect
    pg = bisect.bisect(flips, t)
    lo = flips[pg-1] if pg > 0 else 0; hi = flips[pg] if pg < len(flips) else sm["duration"]
    n_pg = 0
    for n in sm["notes"]:
        if lo - 0.05 <= n["t_start"] < hi - 0.05:
            n_pg += 1
            col = (0, 255, 0) if n["t_start"] <= t else (0, 220, 255)
            y = int(ly0 + n["cy"])
            cv2.rectangle(vis, (lx0 + n["x0"], y - 6), (lx0 + n["x1"], y + 6), col, 1)
    ph = raw["ph_xs"][int(t * fps)]
    if ph >= 0: cv2.line(vis, (lx0 + int(ph), ly0), (lx0 + int(ph), ly0 + 200), (255, 0, 255), 1)
    cv2.putText(vis, f"t={t:.1f}s page[{lo:.1f},{hi:.1f}] map notes on page={n_pg}", (10, 262),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    tiles.append(vis)
out = f"{SC}/mapcheck_{base}.jpg"
cv2.imwrite(out, np.vstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 88])
print("saved", out)
